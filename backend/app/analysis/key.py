"""Key detection with essentia KeyExtractor (spec §7.4)."""
from __future__ import annotations

import numpy as np

FLAT_TO_SHARP = {
    "Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#",
    "Cb": "B", "Fb": "E", "E#": "F", "B#": "C",
}

_extractor = None


def _get_extractor():  # noqa: ANN202
    global _extractor
    if _extractor is None:
        import essentia.standard as es

        _extractor = es.KeyExtractor(profileType="bgate", sampleRate=44100)
    return _extractor


def normalize_tonic(tonic: str) -> str:
    return FLAT_TO_SHARP.get(tonic, tonic)


def detect_key(mono: np.ndarray, sr: int = 44100) -> dict | None:
    """Returns {"label", "tonic", "scale", "confidence"} or None for silent input."""
    y = np.ascontiguousarray(mono, dtype=np.float32)
    if sr != 44100:
        import soxr

        y = np.ascontiguousarray(soxr.resample(y, sr, 44100), dtype=np.float32)
    if y.size == 0 or float(np.max(np.abs(y))) < 1e-6:
        return None
    key, scale, strength = _get_extractor()(y)
    tonic = normalize_tonic(str(key))
    scale = str(scale)
    return {
        "label": f"{tonic} {scale}",
        "tonic": tonic,
        "scale": scale,
        "confidence": round(float(strength), 3),
    }
