"""Helpers shared by API routes: logging, id validation, song/job serialization."""
from __future__ import annotations

import json
import logging
import unicodedata
import uuid
from typing import Any, Iterable

from sqlalchemy import literal_column, select
from sqlalchemy.engine import Connection

from ..config import get_paths
from ..db import ACTIVE_JOB_STATUSES, get_engine, jobs, song_tags, songs, tags
from ..errors import AppError
from ..services import song_has_stems
from ..stems import STEM_MODES

log = logging.getLogger("music_tracks.api")

JOB_ROWID = literal_column("jobs.rowid")


def engine():
    return get_engine()


def check_uuid(value: str, what: str = "song") -> str:
    """Validate an id taken from the URL. Anything that is not a canonical UUID is a 404."""
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        raise AppError("NOT_FOUND", f"{what} not found") from None
    if str(parsed) != value.lower():
        raise AppError("NOT_FOUND", f"{what} not found")
    return str(parsed)


def normalize_text(value: str | None) -> str:
    """Case- and accent-insensitive form used for search and sorting (spec §11)."""
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


# ---------------------------------------------------------------- jobs


def job_to_dict(row: Any, song_title: str | None) -> dict:
    r = row._mapping if hasattr(row, "_mapping") else row
    return {
        "id": r["id"],
        "song_id": r["song_id"],
        "song_title": song_title,
        "stem_mode": r["stem_mode"],
        "status": r["status"],
        "step": r["step"],
        "step_detail": r["step_detail"],
        "step_index": r["step_index"],
        "step_count": r["step_count"],
        "step_progress": r["step_progress"],
        "error_code": r["error_code"],
        "error_detail": r["error_detail"],
        "attempts": r["attempts"],
        "created_at": r["created_at"],
        "started_at": r["started_at"],
        "finished_at": r["finished_at"],
    }


def get_job_dict(conn: Connection, job_id: str) -> dict:
    row = conn.execute(
        select(jobs, songs.c.title.label("song_title"))
        .select_from(jobs.join(songs, songs.c.id == jobs.c.song_id))
        .where(jobs.c.id == job_id)
    ).first()
    if row is None:
        raise AppError("NOT_FOUND", "job not found")
    return job_to_dict(row, row.song_title)


# ---------------------------------------------------------------- songs


def song_row_or_404(conn: Connection, song_id: str):
    song_id = check_uuid(song_id)
    row = conn.execute(select(songs).where(songs.c.id == song_id)).first()
    if row is None:
        raise AppError("NOT_FOUND", "song not found")
    return row


def current_stems(song_id: str, stem_mode: int) -> list[str]:
    if not song_has_stems(song_id):
        return []
    return list(STEM_MODES.get(stem_mode, []))


def _parse_player_state(raw: str | None) -> dict:
    try:
        value = json.loads(raw or "{}")
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def load_songs(conn: Connection, song_ids: Iterable[str] | None = None) -> list[dict]:
    """Return fully serialized Song objects (contract shape), unordered."""
    q = select(songs)
    ids = list(song_ids) if song_ids is not None else None
    if ids is not None:
        if not ids:
            return []
        q = q.where(songs.c.id.in_(ids))
    rows = conn.execute(q).mappings().all()

    tq = select(song_tags.c.song_id, tags.c.name).select_from(
        song_tags.join(tags, tags.c.id == song_tags.c.tag_id)
    )
    jq = select(jobs).order_by(jobs.c.created_at, JOB_ROWID)
    if ids is not None:
        tq = tq.where(song_tags.c.song_id.in_(ids))
        jq = jq.where(jobs.c.song_id.in_(ids))

    tag_map: dict[str, list[str]] = {}
    for sid, name in conn.execute(tq):
        tag_map.setdefault(sid, []).append(name)

    active: dict[str, Any] = {}
    last: dict[str, Any] = {}
    for j in conn.execute(jq).mappings():
        last[j["song_id"]] = j  # ordered ascending, so the final one wins
        if j["status"] in ACTIVE_JOB_STATUSES:
            active[j["song_id"]] = j

    out = []
    for r in rows:
        sid = r["id"]
        title = r["title"]
        aj = active.get(sid)
        lj = last.get(sid)
        out.append(
            {
                "id": sid,
                "title": title,
                "artist": r["artist"],
                "album": r["album"],
                "duration_s": r["duration_s"],
                "source_type": r["source_type"],
                "source_url": r["source_url"],
                "original_filename": r["original_filename"],
                "stem_mode": r["stem_mode"],
                "status": r["status"],
                "favorite": bool(r["favorite"]),
                "notes": r["notes"] or "",
                "has_cover": bool(r["has_cover"]),
                "cover_url": f"/api/songs/{sid}/cover?v={r['updated_at']}" if r["has_cover"] else None,
                "bpm": r["bpm"],
                "key_label": r["key_label"],
                "analysis_status": r["analysis_status"],
                "player_state": _parse_player_state(r["player_state"]),
                "tags": sorted(tag_map.get(sid, []), key=str.casefold),
                "stems": current_stems(sid, r["stem_mode"]),
                "active_job": job_to_dict(aj, title) if aj is not None else None,
                "last_job": job_to_dict(lj, title) if lj is not None else None,
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
        )
    return out


def song_dict(conn: Connection, song_id: str) -> dict:
    found = load_songs(conn, [song_id])
    if not found:
        raise AppError("NOT_FOUND", "song not found")
    return found[0]


def song_dir(song_id: str):
    return get_paths().song_dir(song_id)
