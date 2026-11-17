"""Analysis units (spec §7.4, §7.5, §13 item 8)."""
from __future__ import annotations

import numpy as np
import pytest

from app.analysis.beats import compute_bpm
from app.analysis.chords import _absorb_short, build_templates, match_chords
from app.analysis.key import detect_key, normalize_tonic
from app.analysis.peaks import compute_peaks

from .conftest import SR, synth_song


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
    assert normalize_tonic("Bb") == "A#" and normalize_tonic("Eb") == "D#" and normalize_tonic("C#") == "C#"
    assert detect_key(np.zeros(SR * 5, dtype=np.float32)) is None


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
