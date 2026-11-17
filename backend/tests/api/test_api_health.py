"""Health endpoint, model-cache detection and generic error handling."""
from __future__ import annotations

import pytest

from app.api import routes_songs, routes_system


@pytest.fixture(autouse=True)
def no_torch(monkeypatch):
    monkeypatch.setattr(routes_system, "detect_device", lambda: "cpu")


def _fake_models(models_dir):
    for repo, name, sigs in (("HTDemucs-ft", "htdemucs_ft", ["f7e0c4bc", "d12395a8"]), ("HTDemucs-6s", "htdemucs_6s", ["5c90dfd2"])):
        snap = models_dir / "hf" / "hub" / f"models--adefossez--{repo}" / "snapshots" / "abc"
        snap.mkdir(parents=True)
        (snap / f"{name}.yaml").write_text(f"models: {sigs!r}\nweights: [[1., 0.], [0., 1.]]\n")
        for sig in sigs:
            (snap / f"{sig}.safetensors").write_bytes(b"x")
    ckpt = models_dir / "torch" / "hub" / "checkpoints"
    ckpt.mkdir(parents=True)
    (ckpt / "beat_this-final0.ckpt").write_bytes(b"x")


def test_health(client, paths):
    body = client.get("/api/health").json()
    assert body["ok"] is True and body["device"] == "cpu"
    assert body["data_dir"] == str(paths.root)
    assert body["models_cached"] is False
    assert body["yt_dlp"]
    _fake_models(paths.models)
    assert client.get("/api/health").json()["models_cached"] is True
    (paths.models / "hf" / "hub" / "models--adefossez--HTDemucs-ft" / "snapshots" / "abc" / "d12395a8.safetensors").unlink()
    assert client.get("/api/health").json()["models_cached"] is False


def test_unexpected_error_is_500_internal_error(client, monkeypatch):
    def boom(**_kw):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(routes_songs, "load_songs", lambda *a, **k: boom())
    r = client.get("/api/songs")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "INTERNAL_ERROR"


def test_request_validation_error_shape(client):
    r = client.post("/api/songs/00000000-0000-4000-8000-000000000000/reprocess", json={})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"
