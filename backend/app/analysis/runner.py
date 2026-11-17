"""Full analysis (spec §7.4): beats/BPM, key, chords -> analysis.json payload."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import numpy as np

from ..audio import read_audio
from ..stems import harmonic_stems, non_drum_stems
from .beats import BeatDetector, compute_bpm
from .chords import match_chords
from .key import detect_key

ANALYSIS_VERSION = 1


def _sum_stems_mono(stems_dir: Path, names: list[str]) -> tuple[np.ndarray, int]:
    total: np.ndarray | None = None
    sr = 44100
    for name in names:
        data, sr = read_audio(stems_dir / f"{name}.flac")
        mono = data.mean(axis=1)
        if total is None:
            total = mono.astype(np.float32)
        else:
            n = max(len(total), len(mono))
            if len(total) < n:
                total = np.pad(total, (0, n - len(total)))
            if len(mono) < n:
                mono = np.pad(mono, (0, n - len(mono)))
            total = total + mono
    if total is None:
        raise ValueError("no stems to analyze")
    return total, sr


def key_stems(stem_mode: int) -> list[str]:
    return non_drum_stems(stem_mode)


def chord_stems(stem_mode: int) -> list[str]:
    return harmonic_stems(stem_mode)


def run_analysis(
    source_wav: Path,
    stems_dir: Path,
    stem_mode: int,
    detector: BeatDetector,
    on_progress: Callable[[int], None] = lambda _p: None,
) -> dict:
    beats, downbeats = detector.detect(source_wav)
    bpm = compute_bpm(beats)
    if bpm is None:
        beats, downbeats = [], []
    on_progress(33)

    key_mix, sr = _sum_stems_mono(stems_dir, key_stems(stem_mode))
    key = detect_key(key_mix, sr)
    del key_mix
    on_progress(66)

    chord_mix, sr = _sum_stems_mono(stems_dir, chord_stems(stem_mode))
    chords = match_chords(chord_mix, sr, beats or None)
    on_progress(100)

    return {
        "version": ANALYSIS_VERSION,
        "bpm": bpm,
        "beats": [round(float(b), 3) for b in beats],
        "downbeats": [round(float(d), 3) for d in downbeats],
        "key": key,
        "chords": chords,
    }
