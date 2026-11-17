"""§13 item 15: markers and settings validation."""
from __future__ import annotations

import json

import pytest
from api_helpers import make_song

from app import config


def test_marker_crud(client):
    sid = make_song(duration=10.0)
    r = client.post(f"/api/songs/{sid}/markers", json={"kind": "marker", "name": "Verse", "start_s": 4})
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["kind"] == "marker" and m["end_s"] is None and m["song_id"] == sid
    r = client.post(f"/api/songs/{sid}/markers", json={"kind": "loop", "name": "Solo", "start_s": 1, "end_s": 3})
    loop = r.json()
    assert [x["name"] for x in client.get(f"/api/songs/{sid}/markers").json()["markers"]] == ["Solo", "Verse"]
    r = client.patch(f"/api/songs/{sid}/markers/{loop['id']}", json={"name": "Solo 2", "end_s": 5})
    assert r.status_code == 200 and r.json()["end_s"] == 5 and r.json()["name"] == "Solo 2"
    assert client.patch(f"/api/songs/{sid}/markers/{loop['id']}", json={"start_s": 6}).status_code == 422
    assert client.delete(f"/api/songs/{sid}/markers/{m['id']}").status_code == 204
    assert len(client.get(f"/api/songs/{sid}/markers").json()["markers"]) == 1
    assert client.delete(f"/api/songs/{sid}/markers/{m['id']}").status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "loop", "name": "x", "start_s": 3, "end_s": 3},
        {"kind": "loop", "name": "x", "start_s": 3, "end_s": 2},
        {"kind": "loop", "name": "x", "start_s": 3},
        {"kind": "loop", "name": "x", "start_s": 3, "end_s": 10.5},
        {"kind": "marker", "name": "x", "start_s": -1},
        {"kind": "marker", "name": "x", "start_s": 11},
        {"kind": "marker", "name": "", "start_s": 1},
        {"kind": "marker", "name": "x" * 61, "start_s": 1},
        {"kind": "other", "name": "x", "start_s": 1},
    ],
)
def test_marker_validation(client, body):
    sid = make_song(duration=10.0)
    r = client.post(f"/api/songs/{sid}/markers", json=body)
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_marker_limit(client):
    sid = make_song(duration=10.0)
    for i in range(200):
        r = client.post(f"/api/songs/{sid}/markers", json={"kind": "marker", "name": f"M{i}", "start_s": i / 20})
        assert r.status_code == 201
    r = client.post(f"/api/songs/{sid}/markers", json={"kind": "marker", "name": "M200", "start_s": 1})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_markers_require_ready(client):
    sid = make_song(status="pending", job_status="queued", with_files=False)
    r = client.post(f"/api/songs/{sid}/markers", json={"kind": "marker", "name": "x", "start_s": 1})
    assert r.status_code == 409 and r.json()["error"]["code"] == "SONG_NOT_READY"


# ---------------------------------------------------------------- settings


def test_settings_defaults_and_partial_update(client):
    s = client.get("/api/settings").json()
    assert s["language"] is None and s["default_stem_mode"] == 4 and s["metronome_volume"] == 70
    assert s["data_dir_locked"] is False
    r = client.put("/api/settings", json={"language": "pt-BR", "restart_required": False, "data_dir_locked": True})
    assert r.status_code == 200
    s = r.json()
    assert s["language"] == "pt-BR" and s["default_stem_mode"] == 4 and s["data_dir_locked"] is False
    for body in ({"language": "fr"}, {"default_stem_mode": 3}, {"metronome_volume": 101}, {"metronome_volume": "x"}):
        assert client.put("/api/settings", json=body).status_code == 422, body


def test_settings_data_dir(client, tmp_path):
    r = client.put("/api/settings", json={"data_dir": "relative/path"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert client.put("/api/settings", json={"data_dir": str(tmp_path / "missing" / "deep")}).status_code == 422
    target = tmp_path / "new-library"
    r = client.put("/api/settings", json={"data_dir": str(target)})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["data_dir"] == str(target) and s["restart_required"] is True
    assert target.is_dir()
    assert json.loads(config.CONFIG_FILE.read_text())["data_dir"] == str(target)


def test_settings_data_dir_locked(client, tmp_path, monkeypatch, paths):
    monkeypatch.setenv("MUSIC_TRACKS_HOME", str(paths.root))
    s = client.get("/api/settings").json()
    assert s["data_dir_locked"] is True and s["restart_required"] is False
    r = client.put("/api/settings", json={"data_dir": str(tmp_path / "elsewhere")})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert not config.CONFIG_FILE.exists()
