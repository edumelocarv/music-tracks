"""yt-dlp download step (spec §7.2 step 1)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..config import MAX_FILE_BYTES
from ..errors import AppError, JobCanceled
from .context import StopRequested

log = logging.getLogger("worker.download")

# Tests replace this with a fake class exposing the YoutubeDL interface.
YDL_FACTORY: Callable[[dict], Any] | None = None

THUMB_EXTS = {"jpg", "jpeg", "png", "webp", "gif", "image"}


@dataclass
class DownloadResult:
    audio_path: Path
    thumbnail_path: Path | None
    info: dict


class _YdlLogger:
    def debug(self, msg: str) -> None:
        if not msg.startswith("[download]"):
            log.debug(msg)

    def info(self, msg: str) -> None:
        log.debug(msg)

    def warning(self, msg: str) -> None:
        log.warning("yt-dlp: %s", msg)

    def error(self, msg: str) -> None:
        log.error("yt-dlp: %s", msg)


def _factory() -> Callable[[dict], Any]:
    if YDL_FACTORY is not None:
        return YDL_FACTORY
    import yt_dlp

    return yt_dlp.YoutubeDL


def download_audio(
    url: str,
    work_dir: Path,
    on_progress: Callable[[float], None],
) -> DownloadResult:
    """Downloads the audio into work_dir/download.<ext>. `on_progress(pct)` may raise to abort."""
    aborted: list[BaseException] = []

    def hook(d: dict) -> None:
        if aborted:
            raise aborted[0]
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes") or 0
            pct = (done / total * 100) if total else 0
            try:
                on_progress(min(99.0, pct))
            except BaseException as exc:
                aborted.append(exc)
                raise

    opts = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "max_filesize": MAX_FILE_BYTES,
        "js_runtimes": {"node": {}},
        "outtmpl": str(work_dir / "download.%(ext)s"),
        "writethumbnail": True,
        "quiet": True,
        "no_warnings": False,
        "noprogress": True,
        "socket_timeout": 30,
        "progress_hooks": [hook],
        "logger": _YdlLogger(),
    }
    try:
        with _factory()(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info is not None and hasattr(ydl, "sanitize_info"):
                info = ydl.sanitize_info(info)
    except BaseException as exc:  # noqa: BLE001
        if aborted:
            raise aborted[0] from None
        if isinstance(exc, (JobCanceled, StopRequested, KeyboardInterrupt)):
            raise
        if isinstance(exc, OSError) and getattr(exc, "errno", None) is not None:
            raise
        raise AppError("DOWNLOAD_FAILED", f"{type(exc).__name__}: {exc}"[:1000]) from exc
    if aborted:
        raise aborted[0]
    info = info or {}
    if info.get("_type") == "playlist":
        entries = [e for e in (info.get("entries") or []) if e]
        info = entries[0] if len(entries) == 1 else info

    audio = _find_audio(info, work_dir)
    size_hint = info.get("filesize") or info.get("filesize_approx") or 0
    if audio is None or (size_hint and size_hint > MAX_FILE_BYTES) or (
        audio is not None and audio.stat().st_size > MAX_FILE_BYTES
    ):
        raise AppError("FILE_TOO_LARGE", "download skipped or larger than 500 MB")
    return DownloadResult(audio_path=audio, thumbnail_path=_find_thumbnail(work_dir, audio), info=info)


def _find_audio(info: dict, work_dir: Path) -> Path | None:
    for rd in info.get("requested_downloads") or []:
        fp = rd.get("filepath")
        if fp and Path(fp).is_file():
            return Path(fp)
    for p in sorted(work_dir.glob("download.*")):
        ext = p.suffix.lower().lstrip(".")
        if p.is_file() and ext not in THUMB_EXTS and ext not in {"part", "ytdl", "json"}:
            return p
    return None


def _find_thumbnail(work_dir: Path, audio: Path) -> Path | None:
    for p in sorted(work_dir.glob("download.*")):
        if p != audio and p.suffix.lower().lstrip(".") in THUMB_EXTS:
            return p
    return None
