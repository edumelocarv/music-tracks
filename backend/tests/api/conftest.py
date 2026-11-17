"""Fixtures for API tests: temporary DATA_DIR and a TestClient."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
for p in (str(BACKEND), str(Path(__file__).resolve().parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi.testclient import TestClient  # noqa: E402

from api_helpers import HOST  # noqa: E402
from app import config, db  # noqa: E402
from app.config import Paths  # noqa: E402


@pytest.fixture
def paths(tmp_path, monkeypatch):
    for var in ("MUSIC_TRACKS_HOME", "MUSIC_TRACKS_DEV", "MUSIC_TRACKS_PORT", "MUSIC_TRACKS_HOST", "MUSIC_TRACKS_ALLOWED_HOSTS"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config" / "config.json")
    monkeypatch.setattr(config, "DEFAULT_DATA_DIR", tmp_path / "default-data")
    p = Paths(tmp_path / "data")
    config.set_paths(p)
    engine = db.make_engine(p.db)
    db.set_engine(engine)
    yield p
    engine.dispose()
    db.set_engine(None)
    config._paths = None


@pytest.fixture
def client(paths):
    from app.api.main import app

    with TestClient(app, base_url=f"http://{HOST}", raise_server_exceptions=False) as c:
        yield c
