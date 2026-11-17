"""Job pipeline: download -> prepare -> separate -> analyze -> peaks -> swap (spec §7)."""
from __future__ import annotations

import errno
import json
import logging
import os
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from sqlalchemy import select, update
from sqlalchemy.engine import Engine

from .. import audio
from ..analysis.beats import BeatDetector
from ..analysis.peaks import SAMPLES_PER_PEAK, compute_peaks
from ..analysis.runner import run_analysis
from ..config import MAX_DURATION_S, MIN_DURATION_S, MIN_FREE_BYTES, get_paths
from ..db import jobs, now_iso, songs
from ..errors import AppError, JobCanceled
from ..services import original_path, song_has_stems
from ..stems import stems_for
from . import download as download_mod
from .context import JobContext, SongGone, StopRequested
from .metadata import ExtractedMetadata, info_metadata, read_tags, save_cover
from .separation import SeparatorBackend, combine_stems, model_for, rescale_common, run_separator, save_stem

log = logging.getLogger("worker.pipeline")

SWAP_ITEMS = ("stems", "peaks.json", "analysis.json")


@dataclass
class Deps:
    separator: SeparatorBackend
    beat_detector: BeatDetector
    stop_event: threading.Event = field(default_factory=threading.Event)


# ---------------------------------------------------------------------------
# helpers


def is_enospc(exc: BaseException | None) -> bool:
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
            return True
        if isinstance(exc, audio.AudioError) and exc.no_space:
            return True
        exc = exc.__cause__ or exc.__context__
    return False


def work_dir_for(job_id: str) -> Path:
    return get_paths().tmp / "jobs" / job_id


def _load_song(engine: Engine, song_id: str):  # noqa: ANN202
    with engine.connect() as conn:
        return conn.execute(select(songs).where(songs.c.id == song_id)).first()


def _song_dir_checked(ctx: JobContext) -> Path:
    """songs/<id>/ — only if the song row and folder still exist (the worker never creates it)."""
    d = get_paths().song_dir(ctx.song_id)
    if not ctx.song_exists() or not d.is_dir():
        if not ctx.song_exists():
            raise SongGone("song deleted")
        raise FileNotFoundError(errno.ENOENT, "song folder missing", str(d))
    return d


def _check_duration(duration: float | None) -> None:
    if duration is None:
        return
    if duration > MAX_DURATION_S:
        raise AppError("TOO_LONG", f"duration {duration:.1f}s exceeds {MAX_DURATION_S}s")
    if duration < MIN_DURATION_S:
        raise AppError("TOO_SHORT", f"duration {duration:.1f}s is below {MIN_DURATION_S}s")


def _apply_metadata(ctx: JobContext, meta: ExtractedMetadata, work: Path, extra: dict | None = None) -> None:
    """Writes title/artist/album (only if metadata_edited=0) and cover (only if has_cover=0)."""
    engine = ctx.engine
    cover_tmp: Path | None = None
    if meta.cover is not None:
        cover_tmp = work / "cover.jpg"
        try:
            save_cover(meta.cover if isinstance(meta.cover, (bytes, bytearray)) else Path(meta.cover), cover_tmp)
        except Exception as exc:  # noqa: BLE001
            if is_enospc(exc):
                raise
            log.warning("job %s: invalid cover image ignored (%s)", ctx.job_id, exc)
            cover_tmp = None
    with engine.connect() as conn:
        row = conn.execute(
            select(songs.c.metadata_edited, songs.c.has_cover).where(songs.c.id == ctx.song_id)
        ).first()
    if row is None:
        raise SongGone("song deleted")
    # Write first (no read-then-write upgrade inside the transaction); the conditions are
    # re-checked in SQL so a concurrent PATCH/cover upload always wins.
    with engine.begin() as conn:
        base = dict(extra or {})
        base["updated_at"] = now_iso()
        res = conn.execute(update(songs).where(songs.c.id == ctx.song_id).values(**base))
        if res.rowcount == 0:
            raise SongGone("song deleted")
        text_values = {k: v for k, v in (("title", meta.title), ("artist", meta.artist), ("album", meta.album)) if v}
        if text_values and not row.metadata_edited:
            conn.execute(
                update(songs)
                .where(songs.c.id == ctx.song_id, songs.c.metadata_edited == 0)
                .values(**text_values)
            )
        if cover_tmp is not None and not row.has_cover:
            dest = _song_dir_checked(ctx) / "cover.jpg"
            res = conn.execute(
                update(songs).where(songs.c.id == ctx.song_id, songs.c.has_cover == 0).values(has_cover=1)
            )
            if res.rowcount:
                os.replace(cover_tmp, dest)


# ---------------------------------------------------------------------------
# steps


def step_download(ctx: JobContext, song, work: Path) -> None:  # noqa: ANN001
    first_job = song.duration_s is None
    res = download_mod.download_audio(song.source_url, work, ctx.progress)
    ctx.check_cancel()
    ext = res.audio_path.suffix.lower().lstrip(".") or "bin"
    meta = info_metadata(res.info) if first_job else ExtractedMetadata()
    if first_job and res.thumbnail_path is not None:
        meta.cover = res.thumbnail_path.read_bytes()
    song_dir = _song_dir_checked(ctx)
    for old in song_dir.glob("original.*"):
        old.unlink()
    shutil.move(str(res.audio_path), str(song_dir / f"original.{ext}"))
    if not ctx.song_exists():
        raise SongGone("song deleted")
    _apply_metadata(ctx, meta, work, extra={"original_ext": ext})


def step_prepare(ctx: JobContext, song, work: Path) -> Path:  # noqa: ANN001
    src = original_path(ctx.song_id)
    if src is None:
        if not ctx.song_exists():
            raise SongGone("song deleted")
        raise AppError("INVALID_AUDIO", "original file missing")
    try:
        info = audio.probe(src)
    except audio.AudioError as exc:
        raise AppError("INVALID_AUDIO", str(exc)) from exc
    _check_duration(info.duration_s)
    ctx.progress(5)

    dst = work / "source.wav"

    def on_progress(frac: float) -> None:
        if frac < 0:
            ctx.maybe_check_cancel()
        else:
            ctx.progress(5 + frac * 85)

    try:
        audio.convert_to_wav(src, dst, duration_hint=info.duration_s, on_progress=on_progress)
    except audio.AudioError as exc:
        if exc.no_space:
            raise OSError(errno.ENOSPC, str(exc)) from exc
        raise AppError("INVALID_AUDIO", str(exc)) from exc
    try:
        duration = audio.audio_duration(dst)
    except Exception as exc:  # noqa: BLE001
        raise AppError("INVALID_AUDIO", f"converted audio unreadable: {exc}") from exc
    _check_duration(duration)
    ctx.progress(95)

    fresh = _load_song(ctx.engine, ctx.song_id)
    if fresh is None:
        raise SongGone("song deleted")
    meta = ExtractedMetadata()
    if fresh.duration_s is None and fresh.source_type in ("file", "watch"):
        meta = read_tags(src)
    if fresh.duration_s is None:
        _apply_metadata(ctx, meta, work, extra={"duration_s": round(duration, 3)})
    return dst


def step_separate(ctx: JobContext, deps: Deps, source_wav: Path, stem_mode: int, work: Path) -> Path:
    backend = deps.separator
    model = model_for(stem_mode)
    if not backend.is_model_cached(model):
        ctx.detail("downloading_model")
        log.info("job %s: downloading model %s", ctx.job_id, model)
    try:
        backend.load(model)
    except (AppError, JobCanceled, StopRequested):
        raise
    except Exception as exc:  # noqa: BLE001
        if is_enospc(exc):
            raise
        raise AppError("SEPARATION_FAILED", f"could not load model {model}: {type(exc).__name__}: {exc}") from exc
    ctx.detail(None)
    ctx.check_cancel()

    data, _sr = audio.read_audio(source_wav)
    wav = np.ascontiguousarray(data.T)
    del data

    def callback(d: dict) -> None:
        if d.get("state") == "end":
            length = d.get("audio_length") or 1
            models = d.get("models") or 1
            done = (d.get("model_idx_in_bag", 0) + d.get("segment_offset", 0) / length) / models
            ctx.progress(min(99, int(done * 100)))
        else:
            ctx.maybe_check_cancel()

    t0 = time.monotonic()
    sources = run_separator(backend, model, wav, callback)
    log.info("job %s: separation (%s) took %.1fs", ctx.job_id, model, time.monotonic() - t0)
    del wav
    stems = combine_stems(sources, stem_mode)
    del sources
    factor = rescale_common(stems)
    if factor != 1.0:
        log.info("job %s: stems rescaled by %.4f", ctx.job_id, factor)
    ctx.check_cancel()
    out = work / "stems"
    out.mkdir(parents=True, exist_ok=True)
    for name in stems_for(stem_mode):
        save_stem(stems[name], out / f"{name}.flac")
    return out


def step_analyze(ctx: JobContext, deps: Deps, source_wav: Path, stems_dir: Path, stem_mode: int, work: Path) -> dict | None:
    """All-or-nothing. Returns the analysis dict, or None on failure (job continues)."""
    target = work / "analysis.json"
    try:
        result = run_analysis(source_wav, stems_dir, stem_mode, deps.beat_detector, ctx.progress)
        target.write_text(json.dumps(result, separators=(",", ":")))
        return result
    except (JobCanceled, StopRequested):
        raise
    except Exception as exc:  # noqa: BLE001
        if is_enospc(exc):
            raise
        log.exception("job %s: analysis failed", ctx.job_id)
        target.unlink(missing_ok=True)
        return None


def step_peaks(ctx: JobContext, stems_dir: Path, stem_mode: int, work: Path) -> Path:
    names = stems_for(stem_mode)
    out: dict[str, list[int]] = {}
    for i, name in enumerate(names):
        mono, _sr = audio.read_mono(stems_dir / f"{name}.flac")
        out[name] = compute_peaks(mono)
        ctx.progress((i + 1) * 100 / len(names))
    target = work / "peaks.json"
    payload = {"samples_per_peak": SAMPLES_PER_PEAK, "sample_rate": audio.SAMPLE_RATE, "stems": out}
    target.write_text(json.dumps(payload, separators=(",", ":")))
    return target


# ---------------------------------------------------------------------------
# swap


def swap_results(ctx: JobContext, work: Path, stem_mode: int, analysis: dict | None) -> None:
    """Rename old -> .old, move new in, commit songs+jobs in one transaction, delete .old (§7.2)."""
    ctx.check_cancel()
    song_dir = _song_dir_checked(ctx)
    renamed: list[str] = []
    moved: list[str] = []
    try:
        for name in SWAP_ITEMS:
            cur = song_dir / name
            if cur.exists():
                old = song_dir / f"{name}.old"
                _remove(old)
                os.replace(cur, old)
                renamed.append(name)
        for name in SWAP_ITEMS:
            src = work / name
            if src.exists():
                shutil.move(str(src), str(song_dir / name))
                moved.append(name)
        key = (analysis or {}).get("key") or {}
        with ctx.engine.begin() as conn:
            res = conn.execute(
                update(songs).where(songs.c.id == ctx.song_id).values(
                    stem_mode=stem_mode,
                    bpm=analysis.get("bpm") if analysis else None,
                    key_label=key.get("label"),
                    analysis_status="ok" if analysis is not None else "failed",
                    status="ready",
                    updated_at=now_iso(),
                )
            )
            if res.rowcount == 0:
                raise SongGone("song deleted")
            res = conn.execute(
                update(jobs).where(jobs.c.id == ctx.job_id, jobs.c.status == "running").values(
                    status="done", step_progress=100, step_detail=None, finished_at=now_iso()
                )
            )
            if res.rowcount == 0:
                raise SongGone("job row vanished")
    except BaseException:
        # Undo: drop what was moved in and restore the previous files.
        for name in moved:
            _remove(song_dir / name)
        for name in renamed:
            try:
                os.replace(song_dir / f"{name}.old", song_dir / name)
            except OSError:
                log.exception("job %s: could not restore %s.old", ctx.job_id, name)
        raise
    for name in renamed:
        _remove(song_dir / f"{name}.old")


def _remove(p: Path) -> None:
    if p.is_dir() and not p.is_symlink():
        shutil.rmtree(p, ignore_errors=True)
    else:
        try:
            p.unlink()
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------------------
# job runner


def run_job(engine: Engine, job_id: str, deps: Deps) -> str:
    """Runs a claimed (running) job to completion. Returns the final job status."""
    with engine.connect() as conn:
        job = conn.execute(select(jobs).where(jobs.c.id == job_id)).first()
    if job is None:
        return "gone"
    song_id = job.song_id
    ctx = JobContext(engine, job_id, song_id, deps.stop_event)
    work = work_dir_for(job_id)
    t0 = time.monotonic()
    log.info("job %s start (song %s, mode %d, attempt %d)", job_id, song_id, job.stem_mode, job.attempts)
    try:
        song = _load_song(engine, song_id)
        if song is None:
            raise SongGone("song deleted")
        if shutil.disk_usage(get_paths().root).free < MIN_FREE_BYTES:
            raise AppError("DISK_FULL", "less than 2 GB free in the data folder")
        work.mkdir(parents=True, exist_ok=True)
        needs_download = song.source_type == "url" and original_path(song_id) is None
        ctx.set_step_count(5 if needs_download else 4)

        if needs_download:
            if not song.source_url:
                raise AppError("DOWNLOAD_FAILED", "song has no source URL")
            with ctx.step("download"):
                step_download(ctx, song, work)
        with ctx.step("prepare"):
            source_wav = step_prepare(ctx, song, work)
        with ctx.step("separate"):
            stems_dir = step_separate(ctx, deps, source_wav, job.stem_mode, work)
        with ctx.step("analyze"):
            analysis = step_analyze(ctx, deps, source_wav, stems_dir, job.stem_mode, work)
        with ctx.step("peaks"):
            step_peaks(ctx, stems_dir, job.stem_mode, work)
        swap_results(ctx, work, job.stem_mode, analysis)
        status = "done"
        log.info("job %s done in %.1fs", job_id, time.monotonic() - t0)
    except SongGone:
        status = "gone"
        log.info("job %s: song %s was deleted; results discarded", job_id, song_id)
    except JobCanceled:
        status = "canceled"
        _finish(engine, job_id, song_id, "canceled")
        log.info("job %s canceled", job_id)
    except StopRequested:
        status = "queued"
        _requeue_on_stop(engine, job_id, song_id)
        log.info("job %s interrupted by shutdown; back to queue", job_id)
    except AppError as exc:
        status = "failed"
        log.warning("job %s failed: %s %s", job_id, exc.code, exc.detail)
        _finish(engine, job_id, song_id, "failed", exc.code, exc.detail)
    except Exception as exc:  # noqa: BLE001
        status = "failed"
        if is_enospc(exc):
            log.error("job %s: disk full", job_id, exc_info=exc)
            _finish(engine, job_id, song_id, "failed", "DISK_FULL", f"{type(exc).__name__}: {exc}")
        else:
            log.exception("job %s: unexpected error", job_id)
            _finish(engine, job_id, song_id, "failed", "INTERNAL_ERROR", f"{type(exc).__name__}: {exc}"[:2000])
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if _load_song(engine, song_id) is None:
        # Deleted through the API: never leave a recreated folder behind.
        shutil.rmtree(get_paths().song_dir(song_id), ignore_errors=True)
        status = "gone"
    return status


def _finish(engine: Engine, job_id: str, song_id: str, status: str, code: str | None = None, detail: str | None = None) -> None:
    """Final failed/canceled state; the song is ready if it still has stems, else failed."""
    try:
        with engine.begin() as conn:
            conn.execute(
                update(jobs).where(jobs.c.id == job_id, jobs.c.status == "running").values(
                    status=status, error_code=code, error_detail=detail, step_detail=None,
                    finished_at=now_iso(),
                )
            )
            conn.execute(
                update(songs).where(songs.c.id == song_id).values(
                    status="ready" if song_has_stems(song_id) else "failed", updated_at=now_iso()
                )
            )
    except Exception:  # noqa: BLE001
        log.exception("job %s: could not record final state", job_id)


def _requeue_on_stop(engine: Engine, job_id: str, song_id: str) -> None:
    with engine.begin() as conn:
        res = conn.execute(
            update(jobs).where(jobs.c.id == job_id, jobs.c.status == "running").values(
                status="queued", attempts=jobs.c.attempts - 1, step=None, step_detail=None,
                step_index=0, step_progress=0, started_at=None,
            )
        )
        if res.rowcount and not song_has_stems(song_id):
            conn.execute(update(songs).where(songs.c.id == song_id).values(status="pending", updated_at=now_iso()))
