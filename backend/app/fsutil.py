"""File operations that behave the same on POSIX and Windows.

On Windows a file that another handle has open (the API streaming a stem, an antivirus
scan, a file still being copied into the inbox) cannot be renamed or deleted, and neither
can a directory containing it: the call fails with PermissionError (sharing violation).
These helpers retry for a short while on Windows; on POSIX a PermissionError is a real
permission problem and is raised immediately.
"""
from __future__ import annotations

import logging
import os
import shutil
import time
from pathlib import Path
from typing import Callable, TypeVar

log = logging.getLogger("fsutil")

T = TypeVar("T")
IS_WINDOWS = os.name == "nt"


def _retry(fn: Callable[[], T], timeout: float) -> T:
    deadline = time.monotonic() + timeout
    delay = 0.05
    while True:
        try:
            return fn()
        except PermissionError:
            if not IS_WINDOWS or time.monotonic() >= deadline:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 0.5)


def replace(src: Path | str, dst: Path | str, timeout: float = 10.0) -> None:
    """os.replace (atomic; overwrites an existing destination *file*) with Windows retries.

    A directory can only be moved onto a path that does not exist (remove it first).
    """
    _retry(lambda: os.replace(src, dst), timeout)


def _remove_once(p: Path) -> None:
    if p.is_dir() and not p.is_symlink():
        shutil.rmtree(p)
    else:
        p.unlink(missing_ok=True)


def remove_path(p: Path | str, timeout: float = 5.0) -> bool:
    """Deletes a file or directory tree; missing is fine. Returns False (and logs) if it
    could not be removed, instead of raising."""
    path = Path(p)
    try:
        _retry(lambda: _remove_once(path), timeout)
        return True
    except FileNotFoundError:
        return True
    except OSError as exc:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)  # remove whatever is not locked
        log.warning("could not remove %s: %s", path, exc)
        return not path.exists()
