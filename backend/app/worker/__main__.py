"""Entry point: `python -m app.worker` (spec §3)."""
from __future__ import annotations

import logging
import signal
import sys
from logging.handlers import RotatingFileHandler


def setup_logging(log_dir) -> None:  # noqa: ANN001
    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fh = RotatingFileHandler(log_dir / "worker.log", maxBytes=5 * 1024 * 1024, backupCount=4, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(fh)
    root.addHandler(sh)
    for noisy in ("urllib3", "httpx", "httpx2", "httpcore", "huggingface_hub", "filelock", "numba", "matplotlib"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def stop_signals() -> list[signal.Signals]:
    """SIGINT/SIGTERM everywhere; on Windows also SIGBREAK (what the launcher sends with
    CTRL_BREAK_EVENT, since SIGTERM cannot be delivered to another process there)."""
    sigs = [signal.SIGINT, signal.SIGTERM]
    if hasattr(signal, "SIGBREAK"):
        sigs.append(signal.SIGBREAK)
    return sigs


def main() -> int:
    from ..config import configure_model_env, get_paths

    paths = get_paths()
    configure_model_env(paths)  # before anything imports torch
    setup_logging(paths.logs)
    log = logging.getLogger("worker")

    from ..analysis.beats import BeatThisDetector
    from ..db import get_engine
    from .main import Worker
    from .pipeline import Deps
    from .separation import DemucsBackend

    deps = Deps(separator=DemucsBackend(), beat_detector=BeatThisDetector())

    def on_signal(signum, _frame) -> None:  # noqa: ANN001
        log.info("received %s; stopping (running job goes back to the queue)", signal.Signals(signum).name)
        deps.stop_event.set()
        # A second signal terminates immediately (recovery handles the rest on next start).
        for sig in stop_signals():
            signal.signal(sig, signal.SIG_DFL)

    for sig in stop_signals():
        signal.signal(sig, on_signal)

    log.info("worker starting; data dir %s", paths.root)
    try:
        Worker(get_engine(), deps).run_forever()
    except Exception:  # noqa: BLE001
        log.exception("worker crashed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
