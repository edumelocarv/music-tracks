"""Export endpoints (spec §10)."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from .. import exporting
from ..errors import AppError
from ..stems import STEM_MODES
from .common import check_uuid, engine, log, song_row_or_404

router = APIRouter()


def _ready_song(song_id: str):
    sid = check_uuid(song_id)
    with engine().connect() as conn:
        row = song_row_or_404(conn, sid)
    if row.status != "ready":
        raise AppError("SONG_NOT_READY", "song is not ready")
    return row


def _send(path: Path, filename: str, media_type: str) -> FileResponse:
    return FileResponse(
        path,
        media_type=media_type,
        headers={"Content-Disposition": exporting.content_disposition(filename), "Cache-Control": "no-store"},
        background=BackgroundTask(path.unlink, missing_ok=True),
    )


@router.get("/songs/{song_id}/export/stem/{stem}")
def export_stem(song_id: str, stem: str, format: str | None = None):  # noqa: A002
    song = _ready_song(song_id)
    if stem not in STEM_MODES[song.stem_mode]:
        raise AppError("NOT_FOUND", "stem not found")
    fmt = exporting.check_format(format)
    t0 = time.monotonic()
    path = exporting.export_stem(song, stem, fmt)
    log.info("export stem %s/%s %s in %.1fs", song.id, stem, fmt, time.monotonic() - t0)
    return _send(path, exporting.export_filename(song.artist, song.title, stem, fmt), exporting.MEDIA_TYPES[fmt])


@router.get("/songs/{song_id}/export/zip")
def export_zip(song_id: str, format: str | None = None):  # noqa: A002
    song = _ready_song(song_id)
    fmt = exporting.check_format(format)
    t0 = time.monotonic()
    path = exporting.export_zip(song, fmt)
    log.info("export zip %s %s in %.1fs", song.id, fmt, time.monotonic() - t0)
    return _send(path, exporting.export_filename(song.artist, song.title, "stems", "zip"), exporting.MEDIA_TYPES["zip"])


@router.post("/songs/{song_id}/export/mix")
def export_mix(song_id: str, body: Any = Body(...)):
    song = _ready_song(song_id)
    if not isinstance(body, dict):
        raise AppError("VALIDATION_ERROR", "body must be an object")
    params = exporting.validate_mix(song, body)
    t0 = time.monotonic()
    path = exporting.export_mix(song, params)
    log.info(
        "export mix %s %s speed=%s semitones=%s in %.1fs",
        song.id, params["format"], params["speed"], params["semitones"], time.monotonic() - t0,
    )
    fmt = params["format"]
    return _send(path, exporting.export_filename(song.artist, song.title, "mix", fmt), exporting.MEDIA_TYPES[fmt])
