"""Library endpoints: list/get/patch/delete, cover, reprocess, stem files, peaks, analysis."""
from __future__ import annotations

import io
import json
import os
import time
from typing import Any

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import FileResponse, Response
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel
from sqlalchemy import delete, insert, select, update

from .. import fsutil, services
from ..config import MAX_COVER_BYTES
from ..db import ACTIVE_JOB_STATUSES, jobs, now_iso, song_tags, songs, tags
from ..errors import AppError
from ..stems import STEM_MODES
from .common import (
    check_uuid,
    engine,
    get_job_dict,
    load_songs,
    log,
    normalize_text,
    song_dict,
    song_dir,
    song_row_or_404,
)

router = APIRouter()

SORT_FIELDS = {"created_at", "title", "artist", "bpm", "duration_s"}
SONG_STATUSES = {"pending", "processing", "ready", "failed"}
COVER_MAX_SIDE = 600

# Overridable by tests.
DELETE_WAIT_S = 10.0
DELETE_POLL_S = 0.2


# ---------------------------------------------------------------- list / get


def _parse_bool(value: str | None, name: str) -> bool | None:
    if value is None or value == "":
        return None
    v = value.lower()
    if v in ("true", "1"):
        return True
    if v in ("false", "0"):
        return False
    raise AppError("VALIDATION_ERROR", f"invalid {name}")


@router.get("/songs")
def list_songs(
    q: str | None = None,
    tag: str | None = None,
    favorite: str | None = None,
    status: str | None = None,
    sort: str = "created_at",
    order: str | None = None,
):
    if sort not in SORT_FIELDS:
        raise AppError("VALIDATION_ERROR", f"invalid sort {sort!r}")
    if order is None:
        order = "desc" if sort == "created_at" else "asc"
    if order not in ("asc", "desc"):
        raise AppError("VALIDATION_ERROR", f"invalid order {order!r}")
    fav = _parse_bool(favorite, "favorite")
    if status and status not in SONG_STATUSES:
        raise AppError("VALIDATION_ERROR", f"invalid status {status!r}")

    with engine().connect() as conn:
        items = load_songs(conn)

    if fav is not None:
        items = [s for s in items if s["favorite"] == fav]
    if status:
        items = [s for s in items if s["status"] == status]
    if tag:
        t = tag.strip().casefold()
        items = [s for s in items if any(x.casefold() == t for x in s["tags"])]
    if q and q.strip():
        needle = normalize_text(q.strip())
        items = [
            s
            for s in items
            if needle
            in normalize_text(
                "\n".join(
                    [s["title"], s["artist"] or "", s["album"] or "", s["notes"] or "", *s["tags"]]
                )
            )
        ]

    def key(s: dict) -> Any:
        v = s[sort]
        if sort in ("title", "artist"):
            return normalize_text(v)
        return v

    present = [s for s in items if s[sort] not in (None, "")]
    missing = [s for s in items if s[sort] in (None, "")]
    # Stable tie-break: newest first.
    present.sort(key=lambda s: s["created_at"], reverse=True)
    present.sort(key=key, reverse=(order == "desc"))
    missing.sort(key=lambda s: s["created_at"], reverse=True)
    return {"songs": present + missing}


@router.get("/songs/{song_id}")
def get_song(song_id: str):
    sid = check_uuid(song_id)
    with engine().connect() as conn:
        return song_dict(conn, sid)


# ---------------------------------------------------------------- patch


class SongPatch(BaseModel):
    title: Any = None
    artist: Any = None
    album: Any = None
    favorite: Any = None
    notes: Any = None
    tags: Any = None
    player_state: Any = None


def _opt_text(value: Any, name: str, max_len: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise AppError("VALIDATION_ERROR", f"{name} must be a string")
    value = value.strip()
    if len(value) > max_len:
        raise AppError("VALIDATION_ERROR", f"{name} longer than {max_len}")
    return value or None


def clean_tags(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise AppError("VALIDATION_ERROR", "tags must be a list")
    seen: dict[str, str] = {}
    for item in value:
        if not isinstance(item, str):
            raise AppError("VALIDATION_ERROR", "tag must be a string")
        name = item.strip()
        if not 1 <= len(name) <= 40:
            raise AppError("VALIDATION_ERROR", "tag must have 1-40 characters")
        seen.setdefault(name.casefold(), name)
    return list(seen.values())


def delete_orphan_tags(conn) -> None:  # noqa: ANN001
    conn.execute(delete(tags).where(tags.c.id.not_in(select(song_tags.c.tag_id))))


@router.patch("/songs/{song_id}")
def patch_song(song_id: str, body: SongPatch):
    sid = check_uuid(song_id)
    fields = body.model_fields_set
    values: dict[str, Any] = {}

    if "title" in fields:
        if not isinstance(body.title, str) or not 1 <= len(body.title.strip()) <= 200:
            raise AppError("VALIDATION_ERROR", "title must have 1-200 characters")
        values["title"] = body.title.strip()
    if "artist" in fields:
        values["artist"] = _opt_text(body.artist, "artist", 200)
    if "album" in fields:
        values["album"] = _opt_text(body.album, "album", 200)
    if "favorite" in fields:
        if not isinstance(body.favorite, bool):
            raise AppError("VALIDATION_ERROR", "favorite must be a boolean")
        values["favorite"] = int(body.favorite)
    if "notes" in fields:
        notes = body.notes if body.notes is not None else ""
        if not isinstance(notes, str) or len(notes) > 20000:
            raise AppError("VALIDATION_ERROR", "notes must be a string up to 20000 characters")
        values["notes"] = notes
    if "player_state" in fields:
        if not isinstance(body.player_state, dict):
            raise AppError("VALIDATION_ERROR", "player_state must be an object")
        encoded = json.dumps(body.player_state)
        if len(encoded) > 100_000:
            raise AppError("VALIDATION_ERROR", "player_state too large")
        values["player_state"] = encoded
    new_tags = clean_tags(body.tags) if "tags" in fields else None

    with engine().begin() as conn:
        row = song_row_or_404(conn, sid)
        if any(k in values and values[k] != row._mapping[k] for k in ("title", "artist", "album")):
            values["metadata_edited"] = 1
        values["updated_at"] = now_iso()
        conn.execute(update(songs).where(songs.c.id == sid).values(**values))
        if new_tags is not None:
            conn.execute(delete(song_tags).where(song_tags.c.song_id == sid))
            for name in new_tags:
                tag_row = conn.execute(select(tags.c.id).where(tags.c.name == name)).first()
                if tag_row is None:
                    tag_id = conn.execute(insert(tags).values(name=name)).inserted_primary_key[0]
                else:
                    tag_id = tag_row.id
                conn.execute(insert(song_tags).values(song_id=sid, tag_id=tag_id))
            delete_orphan_tags(conn)
        return song_dict(conn, sid)


# ---------------------------------------------------------------- delete


@router.delete("/songs/{song_id}", status_code=204)
def delete_song(song_id: str):
    sid = check_uuid(song_id)
    eng = engine()
    with eng.begin() as conn:
        song_row_or_404(conn, sid)
        ts = now_iso()
        conn.execute(
            update(jobs)
            .where(jobs.c.song_id == sid, jobs.c.status == "queued")
            .values(status="canceled", finished_at=ts)
        )
        conn.execute(
            update(jobs).where(jobs.c.song_id == sid, jobs.c.status == "running").values(cancel_requested=1)
        )

    deadline = time.monotonic() + DELETE_WAIT_S
    while True:
        with eng.connect() as conn:
            running = conn.execute(
                select(jobs.c.id).where(jobs.c.song_id == sid, jobs.c.status.in_(ACTIVE_JOB_STATUSES))
            ).first()
        if running is None or time.monotonic() >= deadline:
            break
        time.sleep(DELETE_POLL_S)
    if running is not None:
        log.warning("delete song %s: job %s still active after %.0fs; deleting anyway", sid, running.id, DELETE_WAIT_S)

    with eng.begin() as conn:
        conn.execute(delete(jobs).where(jobs.c.song_id == sid))
        conn.execute(delete(songs).where(songs.c.id == sid))
        delete_orphan_tags(conn)
    services.cleanup_song_dir(sid)
    log.info("deleted song %s", sid)
    return Response(status_code=204)


# ---------------------------------------------------------------- cover


def _read_limited(upload: UploadFile, limit: int) -> bytes:
    buf = io.BytesIO()
    while True:
        chunk = upload.file.read(1024 * 1024)
        if not chunk:
            break
        buf.write(chunk)
        if buf.tell() > limit:
            raise AppError("FILE_TOO_LARGE", f"cover larger than {limit} bytes")
    return buf.getvalue()


def save_cover_image(data: bytes, dest) -> None:  # noqa: ANN001
    try:
        img = Image.open(io.BytesIO(data))
        fmt = img.format
    except (UnidentifiedImageError, OSError, ValueError):
        raise AppError("UNSUPPORTED_FORMAT", "cover must be JPEG or PNG") from None
    if fmt not in ("JPEG", "PNG"):
        raise AppError("UNSUPPORTED_FORMAT", f"cover format {fmt} not supported")
    try:
        img.load()
        img = ImageOps.exif_transpose(img)
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            bg = Image.new("RGB", img.size, (0, 0, 0))
            bg.paste(img, mask=img.getchannel("A"))
            img = bg
        else:
            img = img.convert("RGB")
        img.thumbnail((COVER_MAX_SIDE, COVER_MAX_SIDE), Image.Resampling.LANCZOS)
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise AppError("UNSUPPORTED_FORMAT", f"invalid image: {exc}") from None
    tmp = dest.with_name(dest.name + ".tmp")
    img.save(tmp, "JPEG", quality=90)
    fsutil.replace(tmp, dest)


@router.put("/songs/{song_id}/cover")
def put_cover(song_id: str, file: UploadFile = File(...)):
    sid = check_uuid(song_id)
    with engine().connect() as conn:
        song_row_or_404(conn, sid)
    data = _read_limited(file, MAX_COVER_BYTES)
    d = song_dir(sid)
    d.mkdir(parents=True, exist_ok=True)
    save_cover_image(data, d / "cover.jpg")
    with engine().begin() as conn:
        conn.execute(update(songs).where(songs.c.id == sid).values(has_cover=1, updated_at=now_iso()))
        return song_dict(conn, sid)


@router.get("/songs/{song_id}/cover")
def get_cover(song_id: str):
    sid = check_uuid(song_id)
    path = song_dir(sid) / "cover.jpg"
    if not path.is_file():
        raise AppError("NOT_FOUND", "cover not found")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "no-cache"})


@router.delete("/songs/{song_id}/cover")
def delete_cover(song_id: str):
    sid = check_uuid(song_id)
    with engine().begin() as conn:
        song_row_or_404(conn, sid)
        fsutil.remove_path(song_dir(sid) / "cover.jpg")
        conn.execute(update(songs).where(songs.c.id == sid).values(has_cover=0, updated_at=now_iso()))
        return song_dict(conn, sid)


# ---------------------------------------------------------------- reprocess


class ReprocessBody(BaseModel):
    stem_mode: int


@router.post("/songs/{song_id}/reprocess", status_code=201)
def reprocess(song_id: str, body: ReprocessBody):
    sid = check_uuid(song_id)
    if body.stem_mode not in STEM_MODES:
        raise AppError("VALIDATION_ERROR", "stem_mode must be 2, 4 or 6")
    job = services.create_job(engine(), sid, body.stem_mode)
    log.info("reprocess song %s mode %s -> job %s", sid, body.stem_mode, job["id"])
    with engine().connect() as conn:
        return {"job": get_job_dict(conn, job["id"])}


# ---------------------------------------------------------------- files


@router.get("/songs/{song_id}/stems/{stem}.flac")
def get_stem(song_id: str, stem: str, request: Request):
    sid = check_uuid(song_id)
    with engine().connect() as conn:
        row = song_row_or_404(conn, sid)
    if stem not in STEM_MODES.get(row.stem_mode, []):
        raise AppError("NOT_FOUND", "stem not found")
    path = song_dir(sid) / "stems" / f"{stem}.flac"
    if not path.is_file():
        raise AppError("NOT_FOUND", "stem not found")
    resp = FileResponse(
        path, media_type="audio/flac", headers={"Cache-Control": "no-cache"}, stat_result=os.stat(path)
    )
    etag = resp.headers.get("etag")
    inm = request.headers.get("if-none-match")
    if etag and inm and etag in [t.strip() for t in inm.split(",")]:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "no-cache"})
    return resp


def _json_file(song_id: str, name: str):
    sid = check_uuid(song_id)
    path = song_dir(sid) / name
    if not path.is_file():
        raise AppError("NOT_FOUND", f"{name} not found")
    return FileResponse(path, media_type="application/json", headers={"Cache-Control": "no-cache"})


@router.get("/songs/{song_id}/peaks")
def get_peaks(song_id: str):
    return _json_file(song_id, "peaks.json")


@router.get("/songs/{song_id}/analysis")
def get_analysis(song_id: str):
    return _json_file(song_id, "analysis.json")

