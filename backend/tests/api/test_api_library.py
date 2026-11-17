"""§13 items 10 and 22 (API part): search, tags, sorting, PATCH."""
from __future__ import annotations

from api_helpers import make_song
from sqlalchemy import select

from app import db


def _ids(resp):
    return [s["id"] for s in resp.json()["songs"]]


def test_search_ignores_case_and_accents(client):
    a = make_song(title="Canção do Mar", artist="Dulce")
    b = make_song(title="Other", artist="ÉDITH Piaf")
    make_song(title="Nothing", notes="random")
    assert _ids(client.get("/api/songs", params={"q": "cancao"})) == [a]
    assert _ids(client.get("/api/songs", params={"q": "CANÇÃO"})) == [a]
    assert _ids(client.get("/api/songs", params={"q": "edith"})) == [b]
    client.patch(f"/api/songs/{b}", json={"tags": ["Práticá"]})
    assert _ids(client.get("/api/songs", params={"q": "pratica"})) == [b]


def test_tags_replace_and_cleanup(client):
    s1 = make_song(title="One")
    s2 = make_song(title="Two")
    r = client.patch(f"/api/songs/{s1}", json={"tags": [" rock ", "Estudar", "ROCK"]})
    assert r.status_code == 200, r.text
    assert r.json()["tags"] == ["Estudar", "rock"]
    client.patch(f"/api/songs/{s2}", json={"tags": ["estudar"]})
    assert client.get("/api/tags").json() == {"tags": [{"name": "Estudar", "count": 2}, {"name": "rock", "count": 1}]}
    assert _ids(client.get("/api/songs", params={"tag": "ESTUDAR"})) and len(_ids(client.get("/api/songs", params={"tag": "estudar"}))) == 2

    client.patch(f"/api/songs/{s1}", json={"tags": []})
    assert client.get("/api/tags").json() == {"tags": [{"name": "Estudar", "count": 1}]}
    with db.get_engine().connect() as conn:
        assert [r.name for r in conn.execute(select(db.tags.c.name))] == ["Estudar"]
    # deleting the last song with the tag removes it too
    assert client.delete(f"/api/songs/{s2}").status_code == 204
    assert client.get("/api/tags").json() == {"tags": []}

    bad = client.patch(f"/api/songs/{s1}", json={"tags": ["x" * 41]})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "VALIDATION_ERROR"


def test_sort_nulls_last(client):
    a = make_song(title="b", artist="Zed", bpm=90.0)
    b = make_song(title="A", artist=None, bpm=None)
    c = make_song(title="c", artist="alpha", bpm=150.0)
    assert _ids(client.get("/api/songs", params={"sort": "bpm", "order": "asc"})) == [a, c, b]
    assert _ids(client.get("/api/songs", params={"sort": "bpm", "order": "desc"})) == [c, a, b]
    assert _ids(client.get("/api/songs", params={"sort": "artist", "order": "asc"})) == [c, a, b]
    assert _ids(client.get("/api/songs", params={"sort": "artist", "order": "desc"})) == [a, c, b]
    assert _ids(client.get("/api/songs", params={"sort": "title", "order": "asc"})) == [b, a, c]
    assert client.get("/api/songs", params={"sort": "nope"}).status_code == 422


def test_filters(client):
    a = make_song(title="A", favorite=1)
    b = make_song(title="B", status="failed", job_status="failed", with_files=False)
    assert _ids(client.get("/api/songs", params={"favorite": "true"})) == [a]
    assert _ids(client.get("/api/songs", params={"status": "failed"})) == [b]


def test_patch_title_persists_and_sets_metadata_edited(client):
    sid = make_song(title="Old", artist="Someone")
    r = client.patch(f"/api/songs/{sid}", json={"favorite": True, "notes": "practice bridge"})
    assert r.status_code == 200
    with db.get_engine().connect() as conn:
        assert conn.execute(select(db.songs.c.metadata_edited).where(db.songs.c.id == sid)).scalar() == 0

    r = client.patch(f"/api/songs/{sid}", json={"title": "  New title ", "album": ""})
    assert r.status_code == 200
    song = client.get(f"/api/songs/{sid}").json()
    assert song["title"] == "New title" and song["album"] is None and song["artist"] == "Someone"
    assert song["favorite"] is True and song["notes"] == "practice bridge"
    with db.get_engine().connect() as conn:
        assert conn.execute(select(db.songs.c.metadata_edited).where(db.songs.c.id == sid)).scalar() == 1


def test_patch_player_state_and_validation(client):
    sid = make_song()
    state = {"volumes": {"vocals": 50}, "speed": 0.8, "loop": None}
    assert client.patch(f"/api/songs/{sid}", json={"player_state": state}).json()["player_state"] == state
    assert client.get(f"/api/songs/{sid}").json()["player_state"] == state
    for body in ({"title": ""}, {"title": "x" * 201}, {"artist": "x" * 201}, {"favorite": "yes"},
                 {"notes": "x" * 20001}, {"player_state": [1]}, {"tags": "rock"}):
        r = client.patch(f"/api/songs/{sid}", json=body)
        assert r.status_code == 422, body
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_song_shape(client):
    sid = make_song(stem_mode=6, artist="X", bpm=120.0, key_label="A minor", analysis_status="ok")
    song = client.get(f"/api/songs/{sid}").json()
    assert song["stems"] == ["vocals", "drums", "bass", "guitar", "piano", "other"]
    assert song["last_job"]["status"] == "done" and song["active_job"] is None
    assert song["cover_url"] is None and song["has_cover"] is False
    assert song["bpm"] == 120.0 and song["key_label"] == "A minor"
    assert client.get("/api/songs/not-a-uuid").status_code == 404
    assert client.get("/api/songs/00000000-0000-4000-8000-000000000000").json()["error"]["code"] == "NOT_FOUND"
