"""Job queue endpoints (spec §7.1)."""
from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import select, update

from .. import services
from ..db import ACTIVE_JOB_STATUSES, jobs, now_iso, songs
from ..errors import AppError
from .common import JOB_ROWID, check_uuid, engine, get_job_dict, job_to_dict, log

router = APIRouter()


@router.get("/jobs")
def list_jobs(limit: int = Query(20, ge=0, le=500)):
    base = select(jobs, songs.c.title.label("song_title")).select_from(
        jobs.join(songs, songs.c.id == jobs.c.song_id)
    )
    with engine().connect() as conn:
        active = conn.execute(
            base.where(jobs.c.status.in_(ACTIVE_JOB_STATUSES)).order_by(jobs.c.created_at, JOB_ROWID)
        ).all()
        finished = conn.execute(
            base.where(jobs.c.status.not_in(ACTIVE_JOB_STATUSES))
            .order_by(jobs.c.finished_at.desc(), JOB_ROWID.desc())
            .limit(limit)
        ).all()
    return {"jobs": [job_to_dict(r, r.song_title) for r in [*active, *finished]]}


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    jid = check_uuid(job_id, "job")
    with engine().begin() as conn:
        row = conn.execute(select(jobs).where(jobs.c.id == jid)).first()
        if row is None:
            raise AppError("NOT_FOUND", "job not found")
        if row.status == "queued":
            # Conditional update: the worker may claim the job concurrently.
            res = conn.execute(
                update(jobs)
                .where(jobs.c.id == jid, jobs.c.status == "queued")
                .values(status="canceled", finished_at=now_iso(), cancel_requested=1)
            )
            if res.rowcount == 1:
                status = "ready" if services.song_has_stems(row.song_id) else "failed"
                conn.execute(
                    update(songs).where(songs.c.id == row.song_id).values(status=status, updated_at=now_iso())
                )
                log.info("job %s canceled while queued", jid)
                return get_job_dict(conn, jid)
            row = conn.execute(select(jobs).where(jobs.c.id == jid)).first()
        if row.status == "running":
            conn.execute(update(jobs).where(jobs.c.id == jid).values(cancel_requested=1))
            log.info("job %s cancel requested", jid)
            return get_job_dict(conn, jid)
    raise AppError("INVALID_STATE", f"job is {row.status}", status=row.status)


@router.post("/jobs/{job_id}/retry", status_code=201)
def retry_job(job_id: str):
    jid = check_uuid(job_id, "job")
    with engine().connect() as conn:
        row = conn.execute(select(jobs).where(jobs.c.id == jid)).first()
    if row is None:
        raise AppError("NOT_FOUND", "job not found")
    if row.status not in ("failed", "canceled"):
        raise AppError("INVALID_STATE", f"job is {row.status}", status=row.status)
    job = services.create_job(engine(), row.song_id, row.stem_mode)
    log.info("retry job %s -> %s", jid, job["id"])
    with engine().connect() as conn:
        return {"job": get_job_dict(conn, job["id"])}
