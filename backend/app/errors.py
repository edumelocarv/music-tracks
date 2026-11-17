"""Error codes and HTTP mapping (spec §8.3)."""
from __future__ import annotations

from typing import Any

HTTP_STATUS: dict[str, int] = {
    "UNSUPPORTED_FORMAT": 422,
    "TOO_LONG": 422,
    "TOO_SHORT": 422,
    "INVALID_URL": 422,
    "PLAYLIST_NOT_SUPPORTED": 422,
    "VALIDATION_ERROR": 422,
    "FILE_TOO_LARGE": 413,
    "DUPLICATE": 409,
    "JOB_ALREADY_ACTIVE": 409,
    "SONG_NOT_READY": 409,
    "INVALID_STATE": 409,
    "NOT_FOUND": 404,
    "FORBIDDEN": 403,
    "INTERNAL_ERROR": 500,
}

# Codes that only appear inside jobs (jobs.error_code).
JOB_ONLY_CODES = {"INVALID_AUDIO", "DOWNLOAD_FAILED", "SEPARATION_FAILED", "OUT_OF_MEMORY", "DISK_FULL"}


class AppError(Exception):
    """Raised by API and pipeline code. `extra` is merged into the error payload."""

    def __init__(self, code: str, detail: str = "", **extra: Any) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.extra = extra

    @property
    def status(self) -> int:
        return HTTP_STATUS.get(self.code, 500)

    def payload(self) -> dict:
        return {"error": {"code": self.code, "detail": self.detail, **self.extra}}


class JobCanceled(Exception):
    """Raised inside the pipeline when cancel_requested is set."""
