"""Helpers for API tests (separate module name to avoid clashing with other conftests)."""
from __future__ import annotations

import io
import json
import uuid

import numpy as np
import soundfile as sf
from sqlalchemy import insert

from app import config, db
from app.stems import STEM_MODES

HOST = "127.0.0.1:8765"
SR = 44100
STEM_FREQS = {"vocals": 440, "instrumental": 220, "drums": 110, "bass": 55, "guitar": 330, "piano": 660, "other": 550}


def wav_bytes(seconds: float = 1.0, freq: float = 440.0, sr: int = SR, seed: int = 0) -> bytes:
    t = np.arange(int(seconds * sr)) / sr
    rng = np.random.default_rng(seed)
    x = (0.3 * np.sin(2 * np.pi * freq * t) + 0.01 * rng.standard_normal(len(t))).astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, np.stack([x, x], axis=1), sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def make_song(
    *,
    status: str = "ready",
    stem_mode: int = 4,
    duration: float = 3.0,
    title: str = "Song",
    artist: str | None = None,
    album: str | None = None,
    amplitude: float = 0.25,
    with_files: bool = True,
    job_status: str | None = "done",
    **extra,
) -> str:
    """Insert a song (and optionally its job) directly, writing small synthetic stems."""
    song_id = str(uuid.uuid4())
    ts = db.now_iso()
    paths = config.get_paths()
    with db.get_engine().begin() as conn:
        conn.execute(
            insert(db.songs).values(
                id=song_id, title=title, artist=artist, album=album, duration_s=duration,
                source_type="file", source_key=f"sha256:{song_id}", original_filename=f"{title}.wav",
                original_ext="wav", stem_mode=stem_mode, status=status, created_at=ts, updated_at=ts,
                **extra,
            )
        )
        if job_status:
            conn.execute(
                insert(db.jobs).values(
                    id=str(uuid.uuid4()), song_id=song_id, stem_mode=stem_mode, status=job_status,
                    step_index=4, step_count=4, step_progress=100, attempts=1, created_at=ts,
                    started_at=ts if job_status != "queued" else None,
                    finished_at=ts if job_status in ("done", "failed", "canceled") else None,
                    error_code="SEPARATION_FAILED" if job_status == "failed" else None,
                )
            )
    d = paths.song_dir(song_id)
    d.mkdir(parents=True, exist_ok=True)
    if with_files:
        stems_dir = d / "stems"
        stems_dir.mkdir()
        t = np.arange(int(duration * SR)) / SR
        peaks = {}
        for stem in STEM_MODES[stem_mode]:
            x = (amplitude * np.sin(2 * np.pi * STEM_FREQS[stem] * t)).astype(np.float32)
            sf.write(stems_dir / f"{stem}.flac", np.stack([x, x], axis=1), SR, format="FLAC", subtype="PCM_24")
            peaks[stem] = [-30, 30] * 4
        (d / "peaks.json").write_text(json.dumps({"samples_per_peak": 512, "sample_rate": SR, "stems": peaks}))
        (d / "analysis.json").write_text(
            json.dumps({"version": 1, "bpm": 120.0, "beats": [0.0, 0.5], "downbeats": [0.0], "key": None, "chords": []})
        )
    return song_id


def job_rows(song_id: str) -> list[dict]:
    from sqlalchemy import select

    with db.get_engine().connect() as conn:
        return [dict(r) for r in conn.execute(select(db.jobs).where(db.jobs.c.song_id == song_id)).mappings()]


def count_songs() -> int:
    from sqlalchemy import func, select

    with db.get_engine().connect() as conn:
        return conn.execute(select(func.count()).select_from(db.songs)).scalar()
