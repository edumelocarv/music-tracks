"""Runtime configuration: data directory resolution and constants (spec §6.1)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

CONFIG_FILE = Path(os.path.expanduser("~/.config/music-tracks/config.json"))
DEFAULT_DATA_DIR = Path(os.path.expanduser("~/MusicTracks"))

PORT = int(os.environ.get("MUSIC_TRACKS_PORT", "8765"))
DEV_ORIGIN = "http://localhost:5173"

SAMPLE_RATE = 44100
MAX_FILE_BYTES = 500 * 1024 * 1024
MAX_DURATION_S = 15 * 60
MIN_DURATION_S = 5.0
MAX_COVER_BYTES = 10 * 1024 * 1024
MIN_FREE_BYTES = 2 * 1024**3
MAX_MARKERS = 200
ACCEPTED_EXTS = {
    "mp3", "wav", "flac", "m4a", "aac", "ogg", "opus", "aiff", "aif",
    "wma", "webm", "mp4", "mkv",
}


def read_config_file() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text())
    except (OSError, ValueError):
        return {}


def write_config_file(data: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2))


def data_dir_locked() -> bool:
    return bool(os.environ.get("MUSIC_TRACKS_HOME"))


def resolve_data_dir() -> Path:
    env = os.environ.get("MUSIC_TRACKS_HOME")
    if env:
        return Path(os.path.expanduser(env)).resolve()
    cfg = read_config_file().get("data_dir")
    if cfg:
        return Path(os.path.expanduser(cfg)).resolve()
    return DEFAULT_DATA_DIR


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def db(self) -> Path:
        return self.root / "library.db"

    @property
    def inbox(self) -> Path:
        return self.root / "inbox"

    @property
    def ignored(self) -> Path:
        return self.inbox / "_ignorados"

    @property
    def songs(self) -> Path:
        return self.root / "songs"

    @property
    def models(self) -> Path:
        return self.root / "models"

    @property
    def tmp(self) -> Path:
        return self.root / "tmp"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    def song_dir(self, song_id: str) -> Path:
        return self.songs / song_id

    def ensure(self) -> None:
        for p in (self.root, self.inbox, self.ignored, self.songs, self.models, self.tmp, self.logs):
            p.mkdir(parents=True, exist_ok=True)


_paths: Paths | None = None


def get_paths() -> Paths:
    global _paths
    if _paths is None:
        _paths = Paths(resolve_data_dir())
        _paths.ensure()
    return _paths


def set_paths(paths: Paths) -> None:
    """Used by tests to point at a temporary DATA_DIR."""
    global _paths
    paths.ensure()
    _paths = paths


def configure_model_env(paths: Paths) -> None:
    """Point HF/torch caches into DATA_DIR/models (spec §7.3). Call before importing torch."""
    os.environ.setdefault("HF_HOME", str(paths.models / "hf"))
    os.environ.setdefault("TORCH_HOME", str(paths.models / "torch"))
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    if "/opt/homebrew/bin" not in os.environ.get("PATH", ""):
        os.environ["PATH"] = "/opt/homebrew/bin:" + os.environ.get("PATH", "")
