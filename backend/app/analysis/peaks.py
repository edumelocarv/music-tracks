"""Waveform peaks (spec §7.5)."""
from __future__ import annotations

import numpy as np

SAMPLES_PER_PEAK = 512


def compute_peaks(mono: np.ndarray, samples_per_peak: int = SAMPLES_PER_PEAK) -> list[int]:
    """Interleaved [min0, max0, min1, max1, ...] quantized to -127..127."""
    y = np.asarray(mono, dtype=np.float32)
    n = len(y)
    if n == 0:
        return []
    blocks = -(-n // samples_per_peak)
    pad = blocks * samples_per_peak - n
    if pad:
        y = np.concatenate([y, np.zeros(pad, dtype=np.float32)])
        # Padding must not affect the last block's min/max: repeat its last real sample.
        y[n:] = y[n - 1]
    y = y.reshape(blocks, samples_per_peak)
    mins = np.clip(np.round(y.min(axis=1) * 127), -127, 127).astype(np.int16)
    maxs = np.clip(np.round(y.max(axis=1) * 127), -127, 127).astype(np.int16)
    out = np.empty(blocks * 2, dtype=np.int16)
    out[0::2] = mins
    out[1::2] = maxs
    return out.tolist()
