"""Key detection (spec §7.4): chroma + key-profile correlation, numpy/librosa only.

Method: constant-Q chroma (`librosa.feature.chroma_cqt`, 22.05 kHz, hop 4096, 36 bins per
octave, no per-frame normalization) of the non-drum mix; each bin is square-rooted (soft
compression, so loud passages do not dominate) and summed over time. The 12-bin vector is
correlated (Pearson) with the 24 rotations of a major and a minor key profile; the best
match is the key and its correlation (clipped to 0..1) is the confidence.

Profile: the "bgate" major/minor profile (the profile type this project used with
Essentia's KeyExtractor before Essentia was dropped for portability/licensing). Validated
against `essentia.standard.KeyExtractor(profileType="bgate")` on synthetic progressions in
all 24 keys and on real separated stems; Krumhansl-Kessler, Temperley, Aarden and EDMA
profiles agreed less often.
"""
from __future__ import annotations

import numpy as np

FLAT_TO_SHARP = {
    "Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#",
    "Cb": "B", "Fb": "E", "E#": "F", "B#": "C",
}
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

SR = 22050
HOP = 4096
BINS_PER_OCTAVE = 36

# Index 0 = tonic, then ascending semitones.
MAJOR_PROFILE = np.array([1.00, 0.00, 0.42, 0.00, 0.53, 0.37, 0.00, 0.77, 0.00, 0.38, 0.21, 0.30])
MINOR_PROFILE = np.array([1.00, 0.00, 0.36, 0.39, 0.00, 0.38, 0.00, 0.74, 0.27, 0.00, 0.42, 0.23])


def normalize_tonic(tonic: str) -> str:
    return FLAT_TO_SHARP.get(tonic, tonic)


def key_chroma(mono: np.ndarray, sr: int) -> np.ndarray:
    """12-bin pitch-class energy vector (C..B) summarizing the whole signal."""
    import librosa
    import soxr

    y = np.ascontiguousarray(mono, dtype=np.float32)
    if sr != SR:
        y = np.ascontiguousarray(soxr.resample(y, sr, SR), dtype=np.float32)
    chroma = librosa.feature.chroma_cqt(
        y=y, sr=SR, hop_length=HOP, bins_per_octave=BINS_PER_OCTAVE, norm=None
    )
    return np.sqrt(np.maximum(chroma, 0.0)).sum(axis=1)


def _correlate(vec: np.ndarray, profile: np.ndarray) -> np.ndarray:
    """Pearson correlation of `vec` with each of the 12 rotations of `profile`."""
    rotations = np.stack([np.roll(profile, t) for t in range(12)])
    v = vec - vec.mean()
    r = rotations - rotations.mean(axis=1, keepdims=True)
    denom = np.linalg.norm(r, axis=1) * np.linalg.norm(v)
    return (r @ v) / np.where(denom > 0, denom, 1.0)


def estimate_key(chroma: np.ndarray) -> tuple[str, str, float] | None:
    """(tonic, scale, correlation) for a 12-bin chroma vector, or None if it is flat."""
    vec = np.asarray(chroma, dtype=np.float64)
    if vec.shape != (12,) or not np.all(np.isfinite(vec)) or float(np.ptp(vec)) <= 1e-12:
        return None
    major = _correlate(vec, MAJOR_PROFILE)
    minor = _correlate(vec, MINOR_PROFILE)
    if major.max() >= minor.max():
        t = int(np.argmax(major))
        return NOTE_NAMES[t], "major", float(major[t])
    t = int(np.argmax(minor))
    return NOTE_NAMES[t], "minor", float(minor[t])


def detect_key(mono: np.ndarray, sr: int = 44100) -> dict | None:
    """Returns {"label", "tonic", "scale", "confidence"} or None for silent input."""
    y = np.asarray(mono, dtype=np.float32)
    if y.size == 0 or float(np.max(np.abs(y))) < 1e-6:
        return None
    est = estimate_key(key_chroma(y, sr))
    if est is None:
        return None
    tonic, scale, corr = est
    return {
        "label": f"{tonic} {scale}",
        "tonic": tonic,
        "scale": scale,
        "confidence": round(min(1.0, max(0.0, corr)), 3),
    }
