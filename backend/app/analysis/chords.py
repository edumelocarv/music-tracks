"""Chord matcher (spec §7.4): chroma templates + Viterbi smoothing."""
from __future__ import annotations

import numpy as np

SR = 22050
HOP = 2048
BINS_PER_OCTAVE = 36
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
QUALITIES: list[tuple[str, tuple[int, ...]]] = [
    ("", (0, 4, 7)),
    ("m", (0, 3, 7)),
    ("7", (0, 4, 7, 10)),
    ("m7", (0, 3, 7, 10)),
    ("maj7", (0, 4, 7, 11)),
]
N_SCORE = 0.25
TETRAD_PENALTY = 0.03
SOFTMAX_BETA = 20.0
SELF_TRANSITION = 0.9
MIN_SEGMENT_S = 0.25
LOW_ENERGY_RATIO = 0.01
FIXED_WINDOW_S = 0.5


def build_templates() -> tuple[list[str], np.ndarray, np.ndarray]:
    """Returns (labels, templates[n_chords, 12] L2-normalized, bias[n_chords]). `N` is excluded."""
    labels: list[str] = []
    rows: list[np.ndarray] = []
    bias: list[float] = []
    for root in range(12):
        for suffix, intervals in QUALITIES:
            t = np.zeros(12)
            for iv in intervals:
                t[(root + iv) % 12] = 1.0
            rows.append(t / np.linalg.norm(t))
            labels.append(NOTE_NAMES[root] + suffix)
            bias.append(-TETRAD_PENALTY if len(intervals) == 4 else 0.0)
    return labels, np.array(rows), np.array(bias)


def _segment_boundaries(n_frames: int, beats: list[float] | None, duration: float) -> np.ndarray:
    import librosa

    if beats is not None and len(beats) > 0:
        frames = librosa.time_to_frames(np.asarray(beats, dtype=float), sr=SR, hop_length=HOP)
    else:
        times = np.arange(FIXED_WINDOW_S, duration, FIXED_WINDOW_S)
        frames = librosa.time_to_frames(times, sr=SR, hop_length=HOP)
    return librosa.util.fix_frames(frames, x_min=0, x_max=n_frames, pad=True)


def _viterbi(probs: np.ndarray) -> np.ndarray:
    import librosa

    n_states = probs.shape[0]
    trans = librosa.sequence.transition_loop(n_states, SELF_TRANSITION)
    return librosa.sequence.viterbi(probs, trans)


def match_chords(y: np.ndarray, sr: int, beats: list[float] | None) -> list[dict]:
    """y: mono float signal. Returns [{start, end, label}] in seconds (source time)."""
    import librosa

    y = np.asarray(y, dtype=np.float32)
    if sr != SR:
        import soxr

        y = soxr.resample(y, sr, SR).astype(np.float32)
    duration = len(y) / SR
    if duration <= 0:
        return []
    # Raw (non-normalized) chroma so the low-energy rule can compare column energies.
    chroma = librosa.feature.chroma_cqt(
        y=y, sr=SR, hop_length=HOP, bins_per_octave=BINS_PER_OCTAVE, norm=None
    )
    n_frames = chroma.shape[1]
    bounds = _segment_boundaries(n_frames, beats, duration)
    synced = librosa.util.sync(chroma, bounds, aggregate=np.median, pad=False)
    n_cols = synced.shape[1]
    if n_cols == 0:
        return []

    labels, templates, bias = build_templates()
    energy = synced.sum(axis=0)
    norms = np.linalg.norm(synced, axis=0)
    normed = synced / np.maximum(norms, 1e-12)
    scores = templates @ normed + bias[:, None]  # (60, n_cols)
    scores = np.vstack([scores, np.full((1, n_cols), N_SCORE)])
    all_labels = labels + ["N"]

    median_energy = float(np.median(energy))
    low = energy < LOW_ENERGY_RATIO * median_energy if median_energy > 0 else np.ones(n_cols, bool)

    z = SOFTMAX_BETA * scores
    z = z - z.max(axis=0, keepdims=True)
    probs = np.exp(z)
    probs /= probs.sum(axis=0, keepdims=True)
    if low.any():
        probs[:, low] = 1e-12
        probs[-1, low] = 1.0
        probs[:, low] /= probs[:, low].sum(axis=0, keepdims=True)

    path = _viterbi(probs)

    times = librosa.frames_to_time(bounds, sr=SR, hop_length=HOP)
    times[0] = 0.0
    times[-1] = duration
    segs: list[dict] = []
    for i, state in enumerate(path):
        start, end = float(times[i]), float(times[i + 1])
        if end <= start:
            continue
        label = all_labels[int(state)]
        if segs and segs[-1]["label"] == label:
            segs[-1]["end"] = end
        else:
            segs.append({"start": start, "end": end, "label": label})
    segs = _absorb_short(segs)
    return [
        {"start": round(s["start"], 3), "end": round(s["end"], 3), "label": s["label"]} for s in segs
    ]


def _absorb_short(segs: list[dict]) -> list[dict]:
    """Segments shorter than MIN_SEGMENT_S are absorbed by the previous one (the first by the next)."""
    out: list[dict] = []
    pending_start: float | None = None
    for s in segs:
        s = dict(s)
        if pending_start is not None:
            s["start"] = pending_start
            pending_start = None
        if s["end"] - s["start"] < MIN_SEGMENT_S:
            if out:
                out[-1]["end"] = s["end"]
                continue
            pending_start = s["start"]
            continue
        if out and out[-1]["label"] == s["label"]:
            out[-1]["end"] = s["end"]
        else:
            out.append(s)
    if pending_start is not None:  # everything was short
        if out:
            out[-1]["end"] = segs[-1]["end"]
        elif segs:
            out.append({"start": segs[0]["start"], "end": segs[-1]["end"], "label": segs[0]["label"]})
    return out
