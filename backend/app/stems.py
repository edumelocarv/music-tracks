"""Stem modes (spec §2, §7.3)."""
from __future__ import annotations

STEM_MODES: dict[int, list[str]] = {
    2: ["vocals", "instrumental"],
    4: ["vocals", "drums", "bass", "other"],
    6: ["vocals", "drums", "bass", "guitar", "piano", "other"],
}

MODEL_FOR_MODE: dict[int, str] = {2: "htdemucs_ft", 4: "htdemucs_ft", 6: "htdemucs_6s"}

ALL_STEMS = {s for stems in STEM_MODES.values() for s in stems}


def stems_for(mode: int) -> list[str]:
    return list(STEM_MODES[mode])


def harmonic_stems(mode: int) -> list[str]:
    """Stems used for chord detection (§7.4)."""
    if mode == 2:
        return ["instrumental"]
    return [s for s in STEM_MODES[mode] if s not in ("vocals", "drums")]


def non_drum_stems(mode: int) -> list[str]:
    """Stems used for key detection (§7.4)."""
    return [s for s in STEM_MODES[mode] if s != "drums"]
