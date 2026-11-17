"""Worker process: recovery, job loop and watch-folder thread (spec §3, §7.1, §8.3)."""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import threading
import time
from pathlib import Path

from sqlalchemy import literal_column, select, update
from sqlalchemy.engine import Engine

from ..config import ACCEPTED_EXTS, MAX_FILE_BYTES, get_paths
from ..db import get_setting, jobs, new_id, now_iso, songs
from ..errors import AppError
from ..services import create_song_with_job, find_by_source_key, song_has_stems
from .pipeline import SWAP_ITEMS, Deps, _remove, run_job

log = logging.getLogger("worker")

MAX_ATTEMPTS = 2
POLL_INTERVAL = 1.0
WATCH_INTERVAL = 5.0


# ---------------------------------------------------------------------------
# recovery (§7.1)


def recover_swaps(engine: Engine) -> None:
    songs_root = get_paths().songs
    if not songs_root.is_dir():
        return
    for song_dir in songs_root.iterdir():
        if not song_dir.is_dir():
            continue
        olds = [n for n in SWAP_ITEMS if (song_dir / f"{n}.old").exists()]
        if not olds:
            continue
        with engine.connect() as conn:
            latest = conn.execute(
                select(jobs.c.status)
                .where(jobs.c.song_id == song_dir.name)
                .order_by(jobs.c.created_at.desc(), literal_column("jobs.rowid").desc())
                .limit(1)
            ).first()
        if latest is not None and latest.status == "running":
            log.warning("recovery: unconfirmed swap in %s; restoring previous files", song_dir.name)
            for name in SWAP_ITEMS:
                _remove(song_dir / name)
            for name in olds:
                os.replace(song_dir / f"{name}.old", song_dir / name)
        else:
            log.info("recovery: confirmed swap in %s; deleting .old files", song_dir.name)
            for name in olds:
                _remove(song_dir / f"{name}.old")


def recover_jobs(engine: Engine) -> None:
    with engine.connect() as conn:
        running = conn.execute(
            select(jobs.c.id, jobs.c.song_id, jobs.c.attempts, jobs.c.cancel_requested).where(
                jobs.c.status == "running"
            )
        ).all()
    for job in running:
        with engine.begin() as conn:
            if job.cancel_requested:
                conn.execute(
                    update(jobs).where(jobs.c.id == job.id).values(
                        status="canceled", step_detail=None, finished_at=now_iso()
                    )
                )
                song_status = "ready" if song_has_stems(job.song_id) else "failed"
                log.warning("recovery: job %s had a pending cancel -> canceled", job.id)
            elif job.attempts < MAX_ATTEMPTS:
                conn.execute(
                    update(jobs).where(jobs.c.id == job.id).values(
                        status="queued", step=None, step_detail=None, step_index=0,
                        step_progress=0, started_at=None,
                    )
                )
                song_status = "ready" if song_has_stems(job.song_id) else "pending"
                log.warning("recovery: job %s requeued (attempts=%d)", job.id, job.attempts)
            else:
                conn.execute(
                    update(jobs).where(jobs.c.id == job.id).values(
                        status="failed", error_code="INTERNAL_ERROR",
                        error_detail="worker crashed twice", step_detail=None, finished_at=now_iso(),
                    )
                )
                song_status = "ready" if song_has_stems(job.song_id) else "failed"
                log.error("recovery: job %s failed after %d attempts", job.id, job.attempts)
            conn.execute(
                update(songs).where(songs.c.id == job.song_id).values(status=song_status, updated_at=now_iso())
            )


def clean_tmp_jobs() -> None:
    d = get_paths().tmp / "jobs"
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)


def recover(engine: Engine) -> None:
    recover_swaps(engine)
    recover_jobs(engine)
    clean_tmp_jobs()


# ---------------------------------------------------------------------------
# queue


def claim_next(engine: Engine) -> str | None:
    """Atomically claims the oldest queued job. Returns its id or None."""
    with engine.connect() as conn:
        row = conn.execute(
            select(jobs.c.id, jobs.c.song_id)
            .where(jobs.c.status == "queued")
            .order_by(jobs.c.created_at.asc(), literal_column("jobs.rowid").asc())
            .limit(1)
        ).first()
    if row is None:
        return None
    with engine.begin() as conn:
        res = conn.execute(
            update(jobs).where(jobs.c.id == row.id, jobs.c.status == "queued").values(
                status="running", attempts=jobs.c.attempts + 1, started_at=now_iso(),
                step=None, step_detail=None, step_index=0, step_count=0, step_progress=0,
                error_code=None, error_detail=None, finished_at=None,
            )
        )
        if res.rowcount != 1:
            return None
        if not song_has_stems(row.song_id):
            conn.execute(
                update(songs).where(songs.c.id == row.song_id).values(status="processing", updated_at=now_iso())
            )
    return row.id


# ---------------------------------------------------------------------------
# watch folder (§8.3)


def _unique_target(directory: Path, name: str) -> Path:
    p = Path(name)
    stem, suffix = p.stem, p.suffix
    candidate = directory / name
    n = 2
    while candidate.exists() or (directory / f"{candidate.name}.erro.txt").exists():
        candidate = directory / f"{stem} ({n}){suffix}"
        n += 1
    return candidate


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


class WatchScanner:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._seen: dict[str, tuple[int, int]] = {}

    def scan_once(self) -> list[str]:
        """One scan. Returns the ids of songs created."""
        paths = get_paths()
        inbox = paths.inbox
        inbox.mkdir(parents=True, exist_ok=True)
        paths.ignored.mkdir(parents=True, exist_ok=True)
        current: dict[str, tuple[int, int]] = {}
        created: list[str] = []
        for entry in os.scandir(inbox):
            name = entry.name
            if name.startswith(".") or name == paths.ignored.name:
                continue
            try:
                if not entry.is_file(follow_symlinks=False):
                    continue
                st = entry.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
            sig = (st.st_size, st.st_mtime_ns)
            if self._seen.get(name) == sig:
                try:
                    song_id = self._import(Path(entry.path), st.st_size)
                    if song_id:
                        created.append(song_id)
                except Exception:  # noqa: BLE001
                    log.exception("watch: failed to import %s", name)
            else:
                current[name] = sig
        self._seen = current
        return created

    def _reject(self, path: Path, code: str, detail: str = "") -> None:
        ignored = get_paths().ignored
        target = _unique_target(ignored, path.name)
        shutil.move(str(path), str(target))
        (ignored / f"{target.name}.erro.txt").write_text(f"{code}\n{detail}\n".rstrip() + "\n")
        log.info("watch: %s -> _ignorados (%s)", path.name, code)

    def _import(self, path: Path, size: int) -> str | None:
        name = path.name
        ext = path.suffix.lower().lstrip(".")
        if ext not in ACCEPTED_EXTS:
            self._reject(path, "UNSUPPORTED_FORMAT", f"extension .{ext} is not accepted")
            return None
        if size > MAX_FILE_BYTES:
            self._reject(path, "FILE_TOO_LARGE", "file larger than 500 MB")
            return None
        key = f"sha256:{_sha256(path)}"
        existing = find_by_source_key(self.engine, key)
        if existing:
            self._reject(path, "DUPLICATE", f"existing_song_id={existing}")
            return None
        with self.engine.connect() as conn:
            stem_mode = int(get_setting(conn, "default_stem_mode") or 4)
        song_id = new_id()
        song_dir = get_paths().song_dir(song_id)
        song_dir.mkdir(parents=True, exist_ok=False)
        dest = song_dir / f"original.{ext}"
        shutil.move(str(path), str(dest))
        try:
            create_song_with_job(
                self.engine, song_id=song_id, title=Path(name).stem, source_type="watch",
                original_ext=ext, stem_mode=stem_mode, source_key=key, original_filename=name,
            )
        except AppError as exc:
            shutil.move(str(dest), str(path))
            shutil.rmtree(song_dir, ignore_errors=True)
            detail = exc.detail
            if exc.extra.get("existing_song_id"):
                detail = f"existing_song_id={exc.extra['existing_song_id']}"
            self._reject(path, exc.code, detail)
            return None
        except Exception as exc:  # noqa: BLE001
            log.exception("watch: could not create song for %s", name)
            shutil.move(str(dest), str(path))
            shutil.rmtree(song_dir, ignore_errors=True)
            self._reject(path, "INTERNAL_ERROR", f"{type(exc).__name__}: {exc}")
            return None
        log.info("watch: imported %s as song %s (mode %d)", name, song_id, stem_mode)
        return song_id


# ---------------------------------------------------------------------------
# worker


class Worker:
    def __init__(
        self,
        engine: Engine,
        deps: Deps,
        poll_interval: float = POLL_INTERVAL,
        watch_interval: float = WATCH_INTERVAL,
    ) -> None:
        self.engine = engine
        self.deps = deps
        self.stop_event = deps.stop_event
        self.poll_interval = poll_interval
        self.watch_interval = watch_interval
        self.scanner = WatchScanner(engine)
        self._watch_thread: threading.Thread | None = None

    def run_once(self) -> str | None:
        """Claims and runs one job. Returns its final status, or None if the queue is empty."""
        job_id = claim_next(self.engine)
        if job_id is None:
            return None
        return run_job(self.engine, job_id, self.deps)

    def _watch_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.scanner.scan_once()
            except Exception:  # noqa: BLE001
                log.exception("watch: scan failed")
            self.stop_event.wait(self.watch_interval)

    def start_watch_thread(self) -> None:
        self._watch_thread = threading.Thread(target=self._watch_loop, name="watch-folder", daemon=True)
        self._watch_thread.start()

    def run_forever(self) -> None:
        recover(self.engine)
        self.start_watch_thread()
        log.info("worker ready; polling queue every %.1fs", self.poll_interval)
        while not self.stop_event.is_set():
            try:
                status = self.run_once()
            except Exception:  # noqa: BLE001
                log.exception("worker loop error")
                status = None
            if status is None:
                self.stop_event.wait(self.poll_interval)
        if self._watch_thread is not None:
            self._watch_thread.join(timeout=2)
        log.info("worker stopped")
