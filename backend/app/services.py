"""Shared domain operations used by both the API and the worker (spec §7.1, §8)."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from . import fsutil
from .config import get_paths
from .db import ACTIVE_JOB_STATUSES, jobs, new_id, now_iso, songs
from .errors import AppError
from .stems import STEM_MODES


def song_has_stems(song_id: str) -> bool:
    d = get_paths().song_dir(song_id) / "stems"
    return d.is_dir() and any(d.glob("*.flac"))


def _is_active_job_violation(exc: IntegrityError) -> bool:
    msg = str(exc.orig).lower()
    return "jobs.song_id" in msg or "jobs_one_active" in msg


def _is_source_key_violation(exc: IntegrityError) -> bool:
    return "source_key" in str(exc.orig).lower()


def insert_job(conn: Connection, song_id: str, stem_mode: int) -> dict:
    """Insert a queued job. Caller handles the transaction. Raises AppError(JOB_ALREADY_ACTIVE)."""
    if stem_mode not in STEM_MODES:
        raise AppError("VALIDATION_ERROR", f"invalid stem_mode {stem_mode}")
    active = conn.execute(
        select(jobs.c.id).where(jobs.c.song_id == song_id, jobs.c.status.in_(ACTIVE_JOB_STATUSES))
    ).first()
    if active is not None:
        raise AppError("JOB_ALREADY_ACTIVE", "song already has an active job", job_id=active.id)
    job = {
        "id": new_id(),
        "song_id": song_id,
        "stem_mode": stem_mode,
        "status": "queued",
        "step_index": 0,
        "step_count": 0,
        "step_progress": 0,
        "cancel_requested": 0,
        "attempts": 0,
        "created_at": now_iso(),
    }
    conn.execute(insert(jobs).values(**job))
    has_stems = song_has_stems(song_id)
    values: dict = {"updated_at": now_iso()}
    if not has_stems:
        values.update(status="pending", stem_mode=stem_mode)
    conn.execute(update(songs).where(songs.c.id == song_id).values(**values))
    return job


def create_job(engine, song_id: str, stem_mode: int) -> dict:  # noqa: ANN001
    """Create a job for an existing song in its own transaction (reprocess / retry)."""
    try:
        with engine.begin() as conn:
            if conn.execute(select(songs.c.id).where(songs.c.id == song_id)).first() is None:
                raise AppError("NOT_FOUND", "song not found")
            return insert_job(conn, song_id, stem_mode)
    except IntegrityError as exc:
        if _is_active_job_violation(exc):
            raise AppError("JOB_ALREADY_ACTIVE", "song already has an active job") from exc
        raise


def create_song_with_job(
    engine,  # noqa: ANN001
    *,
    song_id: str,
    title: str,
    source_type: str,
    original_ext: str,
    stem_mode: int,
    source_key: str | None,
    source_url: str | None = None,
    original_filename: str | None = None,
) -> tuple[dict, dict]:
    """Insert song (pending) + queued job in a single transaction.

    For files, the caller must already have moved the original into songs/<id>/.
    On failure the caller is responsible for removing songs/<id>/ (see cleanup_song_dir).
    Raises AppError(DUPLICATE, existing_song_id=...) on source_key collision.
    """
    if stem_mode not in STEM_MODES:
        raise AppError("VALIDATION_ERROR", f"invalid stem_mode {stem_mode}")
    ts = now_iso()
    song = {
        "id": song_id,
        "title": title[:200] or "Untitled",
        "source_type": source_type,
        "source_url": source_url,
        "source_key": source_key,
        "original_filename": original_filename,
        "original_ext": original_ext,
        "stem_mode": stem_mode,
        "status": "pending",
        "created_at": ts,
        "updated_at": ts,
    }
    try:
        with engine.begin() as conn:
            conn.execute(insert(songs).values(**song))
            job = insert_job(conn, song_id, stem_mode)
    except IntegrityError as exc:
        if source_key and _is_source_key_violation(exc):
            existing = find_by_source_key(engine, source_key)
            raise AppError("DUPLICATE", "song already exists", existing_song_id=existing) from exc
        raise
    return song, job


def find_by_source_key(engine, source_key: str) -> str | None:  # noqa: ANN001
    with engine.connect() as conn:
        row = conn.execute(select(songs.c.id).where(songs.c.source_key == source_key)).first()
    return row.id if row else None


def cleanup_song_dir(song_id: str) -> None:
    fsutil.remove_path(get_paths().song_dir(song_id))


def original_path(song_id: str) -> Path | None:
    d = get_paths().song_dir(song_id)
    for p in d.glob("original.*"):
        return p
    return None
