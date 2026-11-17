"""Markers and saved loops (spec §6.2 markers)."""
from __future__ import annotations

import math
from typing import Any

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import delete, func, insert, select, update

from ..config import MAX_MARKERS
from ..db import markers, new_id, now_iso
from ..errors import AppError
from .common import check_uuid, engine, song_row_or_404

router = APIRouter()


def marker_to_dict(r: Any) -> dict:
    m = r._mapping if hasattr(r, "_mapping") else r
    return {
        "id": m["id"],
        "song_id": m["song_id"],
        "kind": m["kind"],
        "name": m["name"],
        "start_s": m["start_s"],
        "end_s": m["end_s"],
        "created_at": m["created_at"],
    }


def _ready_song(conn, song_id: str):  # noqa: ANN001
    row = song_row_or_404(conn, song_id)
    if row.status != "ready" or row.duration_s is None:
        raise AppError("SONG_NOT_READY", "song is not ready")
    return row


def _num(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise AppError("VALIDATION_ERROR", f"{name} must be a number")
    return float(value)


def _validate(kind: str, name: Any, start_s: Any, end_s: Any, duration: float) -> tuple[str, float, float | None]:
    if kind not in ("marker", "loop"):
        raise AppError("VALIDATION_ERROR", "kind must be marker or loop")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60:
        raise AppError("VALIDATION_ERROR", "name must have 1-60 characters")
    start = _num(start_s, "start_s")
    if not 0 <= start <= duration:
        raise AppError("VALIDATION_ERROR", "start_s out of range")
    end: float | None = None
    if kind == "loop":
        if end_s is None:
            raise AppError("VALIDATION_ERROR", "end_s required for loop")
        end = _num(end_s, "end_s")
        if not 0 <= end <= duration:
            raise AppError("VALIDATION_ERROR", "end_s out of range")
        if end <= start:
            raise AppError("VALIDATION_ERROR", "end_s must be greater than start_s")
    elif end_s is not None:
        raise AppError("VALIDATION_ERROR", "end_s must be null for marker")
    return name.strip(), start, end


@router.get("/songs/{song_id}/markers")
def list_markers(song_id: str):
    sid = check_uuid(song_id)
    with engine().connect() as conn:
        song_row_or_404(conn, sid)
        rows = conn.execute(
            select(markers).where(markers.c.song_id == sid).order_by(markers.c.start_s, markers.c.created_at)
        ).all()
    return {"markers": [marker_to_dict(r) for r in rows]}


class MarkerCreate(BaseModel):
    kind: Any = None
    name: Any = None
    start_s: Any = None
    end_s: Any = None


@router.post("/songs/{song_id}/markers", status_code=201)
def create_marker(song_id: str, body: MarkerCreate):
    sid = check_uuid(song_id)
    with engine().begin() as conn:
        song = _ready_song(conn, sid)
        name, start, end = _validate(body.kind, body.name, body.start_s, body.end_s, song.duration_s)
        count = conn.execute(select(func.count()).select_from(markers).where(markers.c.song_id == sid)).scalar()
        if count >= MAX_MARKERS:
            raise AppError("VALIDATION_ERROR", f"at most {MAX_MARKERS} markers per song")
        row = {
            "id": new_id(),
            "song_id": sid,
            "kind": body.kind,
            "name": name,
            "start_s": start,
            "end_s": end,
            "created_at": now_iso(),
        }
        conn.execute(insert(markers).values(**row))
    return row


class MarkerPatch(BaseModel):
    name: Any = None
    start_s: Any = None
    end_s: Any = None


def _marker_or_404(conn, song_id: str, marker_id: str):  # noqa: ANN001
    mid = check_uuid(marker_id, "marker")
    row = conn.execute(select(markers).where(markers.c.id == mid, markers.c.song_id == song_id)).first()
    if row is None:
        raise AppError("NOT_FOUND", "marker not found")
    return row


@router.patch("/songs/{song_id}/markers/{marker_id}")
def patch_marker(song_id: str, marker_id: str, body: MarkerPatch):
    sid = check_uuid(song_id)
    fields = body.model_fields_set
    with engine().begin() as conn:
        song = _ready_song(conn, sid)
        cur = _marker_or_404(conn, sid, marker_id)
        name = body.name if "name" in fields else cur.name
        start = body.start_s if "start_s" in fields else cur.start_s
        end = body.end_s if "end_s" in fields else cur.end_s
        name, start, end = _validate(cur.kind, name, start, end, song.duration_s)
        conn.execute(update(markers).where(markers.c.id == cur.id).values(name=name, start_s=start, end_s=end))
        row = conn.execute(select(markers).where(markers.c.id == cur.id)).first()
    return marker_to_dict(row)


@router.delete("/songs/{song_id}/markers/{marker_id}", status_code=204)
def delete_marker(song_id: str, marker_id: str):
    sid = check_uuid(song_id)
    with engine().begin() as conn:
        song_row_or_404(conn, sid)
        cur = _marker_or_404(conn, sid, marker_id)
        conn.execute(delete(markers).where(markers.c.id == cur.id))
    return Response(status_code=204)
