"""Beat/downbeat detection (spec §7.4). Real detector: beat_this, loaded once and cached."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Protocol

import numpy as np

MIN_BEATS = 8


class BeatDetector(Protocol):
    def detect(self, wav_path: Path) -> tuple[list[float], list[float]]:
        """Returns (beats, downbeats) in seconds."""
        ...


class BeatThisDetector:
    """beat_this File2Beats(checkpoint_path="final0", device="cpu", dbn=False), lazily loaded."""

    _model = None
    _lock = threading.Lock()

    @classmethod
    def _get_model(cls):  # noqa: ANN206
        with cls._lock:
            if cls._model is None:
                from beat_this.inference import File2Beats

                cls._model = File2Beats(checkpoint_path="final0", device="cpu", dbn=False)
            return cls._model

    def detect(self, wav_path: Path) -> tuple[list[float], list[float]]:
        import soundfile as sf
        import torch
        from beat_this.inference import Audio2Beats

        model = self._get_model()
        data, sr = sf.read(str(wav_path), dtype="float32", always_2d=True)
        mono = data.mean(axis=1)
        with torch.inference_mode():
            # File2Beats.__call__ only loads the file; feed the mono mix directly.
            beats, downbeats = Audio2Beats.__call__(model, mono, sr)
        return [float(b) for b in beats], [float(d) for d in downbeats]


def compute_bpm(beats: list[float]) -> float | None:
    if len(beats) < MIN_BEATS:
        return None
    diffs = np.diff(np.asarray(beats, dtype=float))
    diffs = diffs[diffs > 0]
    if diffs.size == 0:
        return None
    return round(60.0 / float(np.median(diffs)), 1)
