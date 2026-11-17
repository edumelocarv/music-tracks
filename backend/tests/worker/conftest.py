"""Worker test fixtures: temp DATA_DIR, fake separator and fake beat detector (spec §13)."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

import numpy as np
import pytest
import soundfile as sf

BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app import config, db  # noqa: E402
from app.audio import ffmpeg_bin  # noqa: E402
from app.services import create_song_with_job  # noqa: E402
from app.worker.pipeline import Deps  # noqa: E402

SR = 44100
MODEL_SOURCES = {
    "htdemucs_ft": ["drums", "bass", "other", "vocals"],
    "htdemucs_6s": ["drums", "bass", "other", "vocals", "guitar", "piano"],
}
# Frequency bands (Hz) used by the fake separator to split the mix.
BANDS = {
    4: {"bass": (0, 250), "vocals": (250, 1000), "other": (1000, 4000), "drums": (4000, 1e9)},
    6: {
        "bass": (0, 250), "vocals": (250, 600), "guitar": (600, 1200), "piano": (1200, 2500),
        "other": (2500, 6000), "drums": (6000, 1e9),
    },
}


class FakeSeparator:
    """Splits the mix into frequency bands; emits demucs-like chunk callbacks."""

    def __init__(self) -> None:
        self.device = "mps"
        self.cached = True
        self.loaded: str | None = None
        self.load_calls: list[str] = []
        self.calls: list[str] = []  # devices used
        self.failures: dict[str, BaseException] = {}  # device -> exception to raise
        self.on_chunk: Callable[[int], None] | None = None  # test hook, receives chunk index
        self.chunks = 4

    def default_device(self) -> str:
        return self.device

    def is_model_cached(self, model: str) -> bool:
        return self.cached

    def load(self, model: str) -> None:
        self.load_calls.append(model)
        self.loaded = model
        self.cached = True

    def separate(self, model, wav, device, callback):  # noqa: ANN001
        self.calls.append(device)
        n = wav.shape[1]
        for i in range(self.chunks):
            off = i * n // self.chunks
            base = {"model_idx_in_bag": 0, "segment_offset": off, "audio_length": n, "models": 1}
            callback({**base, "state": "start"})
            if self.on_chunk:
                self.on_chunk(i)
            callback({**base, "state": "end"})
        if device in self.failures:
            raise self.failures[device]
        bands = BANDS[6 if model == "htdemucs_6s" else 4]
        spec = np.fft.rfft(wav, axis=1)
        freqs = np.fft.rfftfreq(n, 1 / SR)
        out = {}
        for name in MODEL_SOURCES[model]:
            lo, hi = bands[name]
            mask = (freqs >= lo) & (freqs < hi)
            out[name] = np.fft.irfft(spec * mask, n=n, axis=1).astype(np.float32)
        return out


class FakeBeats:
    """Beats every 0.5 s from 0; downbeats every 2 s."""

    def __init__(self) -> None:
        self.error: BaseException | None = None

    def detect(self, wav_path: Path):  # noqa: ANN201
        if self.error:
            raise self.error
        dur = sf.info(str(wav_path)).duration
        beats = [round(x, 3) for x in np.arange(0, dur, 0.5)]
        return beats, beats[::4]


@pytest.fixture
def data_dir(tmp_path):  # noqa: ANN001, ANN201
    paths = config.Paths(tmp_path / "data")
    config.set_paths(paths)
    engine = db.make_engine(paths.db)
    db.set_engine(engine)
    yield paths
    db.set_engine(None)
    engine.dispose()
    config._paths = None  # noqa: SLF001


@pytest.fixture
def engine(data_dir):  # noqa: ANN001, ANN201
    return db.get_engine()


@pytest.fixture
def fake_sep() -> FakeSeparator:
    return FakeSeparator()


@pytest.fixture
def fake_beats() -> FakeBeats:
    return FakeBeats()


@pytest.fixture
def deps(fake_sep, fake_beats) -> Deps:  # noqa: ANN001
    return Deps(separator=fake_sep, beat_detector=fake_beats)


@pytest.fixture
def worker(engine, deps):  # noqa: ANN001, ANN201
    from app.worker.main import Worker

    return Worker(engine, deps, poll_interval=0.01, watch_interval=0.01)


# ---------------------------------------------------------------------------
# audio generation


def midi_hz(m: float) -> float:
    return 440.0 * 2 ** ((m - 69) / 12)


PROGRESSION = [("Am", [57, 60, 64]), ("F", [53, 57, 60]), ("C", [48, 52, 55]), ("G", [55, 59, 62])]


def synth_song(seconds: float = 10.0, sr: int = SR, clicks: bool = True, chord_len: float = 2.0) -> np.ndarray:
    """Am-F-C-G (2 s each, repeated) with bass notes and optional clicks at 120 BPM. (frames, 2)."""
    n = int(seconds * sr)
    t = np.arange(n) / sr
    y = np.zeros(n)
    seg = int(chord_len * sr)
    for i in range(0, n, seg):
        _, notes = PROGRESSION[(i // seg) % 4]
        tt = t[i:i + seg] - t[i]
        env = np.minimum(1, tt * 50) * np.minimum(1, (chord_len - tt) * 50)
        part = np.zeros(len(tt))
        for m in notes:
            f = midi_hz(m)
            part += sum((0.6 ** k) * np.sin(2 * np.pi * f * (k + 1) * tt) for k in range(3))
        part += 0.8 * np.sin(2 * np.pi * midi_hz(notes[0] - 12) * tt)
        y[i:i + len(tt)] = part * env
    y *= 0.08
    if clicks:
        click_len = int(0.03 * sr)
        ct = np.arange(click_len) / sr
        click = np.sin(2 * np.pi * 1500 * ct) * np.exp(-ct * 150) * 0.5
        rng = np.random.default_rng(0)
        noise = rng.standard_normal(click_len) * np.exp(-ct * 200) * 0.3
        for b in np.arange(0, seconds, 0.5):
            s = int(b * sr)
            e = min(n, s + click_len)
            y[s:e] += (click + noise)[: e - s]
    return np.stack([y, y], axis=1).astype(np.float32)


def write_song_wav(path: Path, seconds: float = 10.0, **kw) -> Path:  # noqa: ANN003
    sf.write(str(path), synth_song(seconds, **kw), SR, subtype="PCM_16")
    return path


def write_silence(path: Path, seconds: float, sr: int = 8000) -> Path:
    sf.write(str(path), np.zeros(int(seconds * sr), dtype=np.float32), sr, subtype="PCM_16")
    return path


def to_mp3(src: Path, dst: Path) -> Path:
    subprocess.run(
        [ffmpeg_bin(), "-nostdin", "-loglevel", "error", "-y", "-i", str(src), "-c:a", "libmp3lame", "-b:a", "128k", str(dst)],
        check=True,
    )
    return dst


def add_song(engine, src: Path, stem_mode: int = 4, source_type: str = "file", title: str | None = None):  # noqa: ANN001, ANN201
    """Mimics the API: copies src into songs/<id>/original.<ext> and inserts song + job."""
    song_id = db.new_id()
    paths = config.get_paths()
    d = paths.song_dir(song_id)
    d.mkdir(parents=True)
    ext = src.suffix.lower().lstrip(".")
    shutil.copy(src, d / f"original.{ext}")
    _song, job = create_song_with_job(
        engine, song_id=song_id, title=title or src.stem, source_type=source_type,
        original_ext=ext, stem_mode=stem_mode, source_key=f"sha256:{song_id}",
        original_filename=src.name,
    )
    return song_id, job["id"]


def add_url_song(engine, url: str = "https://example.com/watch?v=abc", stem_mode: int = 4):  # noqa: ANN001, ANN201
    song_id = db.new_id()
    config.get_paths().song_dir(song_id).mkdir(parents=True)
    _song, job = create_song_with_job(
        engine, song_id=song_id, title="Provisional", source_type="url", original_ext="url",
        stem_mode=stem_mode, source_key=f"url:test:{song_id}", source_url=url,
    )
    return song_id, job["id"]


def get_song(engine, song_id):  # noqa: ANN001, ANN201
    from sqlalchemy import select

    with engine.connect() as conn:
        return conn.execute(select(db.songs).where(db.songs.c.id == song_id)).first()


def get_job(engine, job_id):  # noqa: ANN001, ANN201
    from sqlalchemy import select

    with engine.connect() as conn:
        return conn.execute(select(db.jobs).where(db.jobs.c.id == job_id)).first()


def update_song(engine, song_id, **values):  # noqa: ANN001, ANN003, ANN201
    from sqlalchemy import update

    with engine.begin() as conn:
        conn.execute(update(db.songs).where(db.songs.c.id == song_id).values(**values))


def update_job(engine, job_id, **values):  # noqa: ANN001, ANN003, ANN201
    from sqlalchemy import update

    with engine.begin() as conn:
        conn.execute(update(db.jobs).where(db.jobs.c.id == job_id).values(**values))
