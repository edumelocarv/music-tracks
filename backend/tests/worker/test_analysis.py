"""Analysis units (spec §7.4, §7.5, §13 item 8)."""
from __future__ import annotations

import numpy as np
import pytest

from app.analysis.beats import compute_bpm
from app.analysis.chords import _absorb_short, build_templates, match_chords
from app.analysis.key import MAJOR_PROFILE, MINOR_PROFILE, detect_key, estimate_key, normalize_tonic
from app.analysis.peaks import compute_peaks

from .conftest import SR, midi_hz, synth_song


def test_chord_matcher_am_f_c_g():
    y = synth_song(8.0, clicks=False).mean(axis=1)
    beats = list(np.arange(0, 8.0, 0.5))
    chords = match_chords(y, SR, beats)
    assert [c["label"] for c in chords] == ["Am", "F", "C", "G"]
    for c, expected_start in zip(chords, [0, 2, 4, 6]):
        assert abs(c["start"] - expected_start) <= 0.5
    assert abs(chords[-1]["end"] - 8.0) <= 0.01


def test_chord_matcher_without_beats_and_silence():
    y = synth_song(8.0, clicks=False).mean(axis=1)
    y[int(4 * SR):] = 0
    chords = match_chords(y, SR, None)
    assert [c["label"] for c in chords] == ["Am", "F", "N"]
    assert abs(chords[-1]["start"] - 4.0) <= 0.5


def test_templates():
    labels, templates, bias = build_templates()
    assert len(labels) == 60 and labels[:5] == ["C", "Cm", "C7", "Cm7", "Cmaj7"]
    assert np.allclose(np.linalg.norm(templates, axis=1), 1.0)
    assert bias[labels.index("Am7")] == pytest.approx(-0.03) and bias[labels.index("Am")] == 0


def test_absorb_short_segments():
    segs = [
        {"start": 0.0, "end": 0.1, "label": "C"},
        {"start": 0.1, "end": 2.0, "label": "G"},
        {"start": 2.0, "end": 2.2, "label": "D"},
        {"start": 2.2, "end": 4.0, "label": "G"},
    ]
    assert _absorb_short(segs) == [{"start": 0.0, "end": 4.0, "label": "G"}]


def test_key_detection_and_flats():
    y = synth_song(8.0, clicks=False).mean(axis=1)
    key = detect_key(y, SR)
    assert key["label"] in ("A minor", "C major") and 0 <= key["confidence"] <= 1
    assert set(key) == {"label", "tonic", "scale", "confidence"}
    assert normalize_tonic("Bb") == "A#" and normalize_tonic("Eb") == "D#" and normalize_tonic("C#") == "C#"
    assert detect_key(np.zeros(SR * 5, dtype=np.float32)) is None
    assert detect_key(np.zeros(0, dtype=np.float32)) is None


def test_estimate_key_profiles():
    assert estimate_key(np.roll(MAJOR_PROFILE, 2)) == ("D", "major", pytest.approx(1.0))
    assert estimate_key(np.roll(MINOR_PROFILE, 10))[:2] == ("A#", "minor")
    assert estimate_key(np.ones(12)) is None
    assert estimate_key(np.full(12, np.nan)) is None


def _cadence(tonic_midi: int, scale: str, sr: int = SR) -> np.ndarray:
    """I-IV-V-I (major) or i-iv-V-i (harmonic minor) with bass, 1.5 s per chord."""
    third = 3 if scale == "minor" else 4
    chords = [(0, third, 7), (5, 5 + third, 12), (7, 11, 14), (0, third, 7)]
    t = np.arange(int(1.5 * sr)) / sr
    env = np.exp(-t * 1.5) * np.minimum(1, t * 100)
    out = []
    for chord in chords:
        seg = np.zeros_like(t)
        for iv in chord:
            f = midi_hz(tonic_midi + iv)
            seg += sum((0.5 ** k) * np.sin(2 * np.pi * f * (k + 1) * t) for k in range(4))
        seg += 0.8 * np.sin(2 * np.pi * midi_hz(tonic_midi - 12 + chord[0]) * t)
        out.append(seg * env)
    y = np.concatenate(out * 2)
    return (0.2 * y / np.max(np.abs(y))).astype(np.float32)


@pytest.mark.parametrize(
    ("tonic_midi", "scale", "label"),
    [(62, "major", "D major"), (58, "major", "A# major"), (64, "minor", "E minor"), (54, "minor", "F# minor")],
)
def test_key_detection_on_cadences(tonic_midi, scale, label):
    key = detect_key(_cadence(tonic_midi, scale), SR)
    assert key["label"] == label and key["confidence"] > 0.5
    assert detect_key(_cadence(tonic_midi, scale)[::2], SR // 2)["label"] == label  # other sample rate


def test_bpm():
    assert compute_bpm(list(np.arange(0, 10, 0.5))) == 120.0
    assert compute_bpm([0, 0.5, 1.0]) is None


def test_peaks():
    y = np.zeros(1100, dtype=np.float32)
    y[10] = 1.0
    y[600] = -0.5
    y[1099] = 0.25
    p = compute_peaks(y)
    assert p == [0, 127, -64, 0, 0, 32]


@pytest.mark.slow
def test_real_bpm_with_beat_this(tmp_path):
    import soundfile as sf

    from app.analysis.beats import BeatThisDetector

    path = tmp_path / "clicks.wav"
    sf.write(str(path), synth_song(16.0, clicks=True), SR)
    beats, downbeats = BeatThisDetector().detect(path)
    bpm = compute_bpm(beats)
    assert bpm is not None and 119 <= bpm <= 121
