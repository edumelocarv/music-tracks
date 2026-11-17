"""§13 item 12: Host and Origin checks."""
from __future__ import annotations


def test_foreign_host_forbidden(client):
    r = client.get("/api/health", headers={"Host": "evil.example:8765"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN"
    assert client.get("/api/tags", headers={"Host": "127.0.0.1:9999"}).status_code == 403


def test_localhost_host_allowed(client):
    assert client.get("/api/tags", headers={"Host": "localhost:8765"}).status_code == 200
    assert client.get("/api/tags").status_code == 200


def test_post_with_foreign_origin_forbidden(client):
    r = client.put("/api/settings", json={"metronome_volume": 10}, headers={"Origin": "http://evil.example"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN"
    r = client.put("/api/settings", json={"metronome_volume": 10}, headers={"Origin": "http://localhost:5173"})
    assert r.status_code == 403
    assert client.get("/api/settings").json()["metronome_volume"] == 70


def test_post_with_own_origin_or_without_origin_accepted(client):
    assert client.put("/api/settings", json={"metronome_volume": 10}).status_code == 200
    r = client.put("/api/settings", json={"metronome_volume": 11}, headers={"Origin": "http://127.0.0.1:8765"})
    assert r.status_code == 200


def test_get_with_foreign_origin_allowed(client):
    assert client.get("/api/tags", headers={"Origin": "http://evil.example"}).status_code == 200


def test_dev_origins(client, monkeypatch):
    monkeypatch.setenv("MUSIC_TRACKS_DEV", "1")
    for origin in ("http://localhost:5173", "http://127.0.0.1:5173"):
        r = client.put("/api/settings", json={"metronome_volume": 12}, headers={"Origin": origin})
        assert r.status_code == 200
    assert client.put("/api/settings", json={}, headers={"Origin": "http://evil.example"}).status_code == 403


def test_unknown_api_route_is_json_404_and_spa_fallback(client):
    r = client.get("/api/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"
    assert client.get("/songs/123").status_code == 200
