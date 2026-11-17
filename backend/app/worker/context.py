"""Per-job progress/cancellation context."""
from __future__ import annotations

import contextlib
import logging
import threading
import time
from collections.abc import Iterator

from sqlalchemy import select, update
from sqlalchemy.engine import Engine

from ..db import jobs, songs
from ..errors import JobCanceled

log = logging.getLogger("worker.job")

CANCEL_CHECK_INTERVAL = 0.5


class SongGone(JobCanceled):
    """The job/song row vanished (song deleted through the API). Treated as cancellation."""


class StopRequested(Exception):
    """The worker is shutting down (SIGTERM/SIGINT); the job goes back to the queue."""


class JobContext:
    def __init__(
        self,
        engine: Engine,
        job_id: str,
        song_id: str,
        stop_event: threading.Event | None = None,
    ) -> None:
        self.engine = engine
        self.job_id = job_id
        self.song_id = song_id
        self.stop_event = stop_event or threading.Event()
        self.step_index = 0
        self.step_count = 0
        self.step_name: str | None = None
        self._progress = -1
        self._last_check = 0.0

    # -- DB helpers -------------------------------------------------------------
    def update_job(self, **values) -> None:  # noqa: ANN003
        with self.engine.begin() as conn:
            res = conn.execute(update(jobs).where(jobs.c.id == self.job_id).values(**values))
        if res.rowcount == 0:
            raise SongGone("job row vanished")

    def song_exists(self) -> bool:
        with self.engine.connect() as conn:
            return conn.execute(select(songs.c.id).where(songs.c.id == self.song_id)).first() is not None

    # -- cancellation -----------------------------------------------------------
    def check_cancel(self) -> None:
        self._last_check = time.monotonic()
        if self.stop_event.is_set():
            raise StopRequested()
        with self.engine.connect() as conn:
            row = conn.execute(
                select(jobs.c.cancel_requested).where(jobs.c.id == self.job_id)
            ).first()
        if row is None:
            raise SongGone("job row vanished")
        if row.cancel_requested:
            raise JobCanceled()

    def maybe_check_cancel(self) -> None:
        if self.stop_event.is_set():
            raise StopRequested()
        if time.monotonic() - self._last_check >= CANCEL_CHECK_INTERVAL:
            self.check_cancel()

    # -- progress ---------------------------------------------------------------
    def set_step_count(self, n: int) -> None:
        self.step_count = n
        self.update_job(step_count=n)

    @contextlib.contextmanager
    def step(self, name: str) -> Iterator[None]:
        self.check_cancel()
        self.step_index += 1
        self.step_name = name
        self._progress = 0
        self.update_job(step=name, step_index=self.step_index, step_progress=0, step_detail=None)
        t0 = time.monotonic()
        log.info("job %s step %s (%d/%d) start", self.job_id, name, self.step_index, self.step_count)
        ok = False
        try:
            yield
            ok = True
        finally:
            log.info(
                "job %s step %s %s in %.2fs",
                self.job_id, name, "done" if ok else "aborted", time.monotonic() - t0,
            )
        self.progress(100)

    def progress(self, pct: float) -> None:
        """Updates step_progress (0..100) when the integer value changes; checks cancellation."""
        value = max(0, min(100, int(pct)))
        if value != self._progress:
            self._progress = value
            self.update_job(step_progress=value)
        self.maybe_check_cancel()

    def detail(self, value: str | None) -> None:
        self.update_job(step_detail=value)
