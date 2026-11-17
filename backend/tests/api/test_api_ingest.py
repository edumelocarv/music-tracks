"""§13 items 1, 2 and 16: upload, duplicates, URL validation."""
from __future__ import annotations

import time

import pytest
from api_helpers import count_songs, job_rows, wav_bytes

from app.api import routes_ingest


def _upload(client, name="My Song.wav", data=None, stem_mode=None):
    files = {"file": (name, data if data is not None else wav_bytes(), "application/octet-stream")}
    form = {"stem_mode": str(stem_mode)} if stem_mode is not None else {}
    return client.post("/api/songs/upload", files=files, data=form)


def _assert_nothing_created(paths):
    assert count_songs() == 0
    assert list(paths.songs.iterdir()) == []
    assert list((paths.tmp / "api").iterdir()) == []


def test_upload_creates_pending_song_and_queued_job(client, paths):
    r = _upload(client, stem_mode=6)
    assert r.status_code == 201, r.text
    body = r.json()
    song, job = body["song"], body["job"]
    assert song["status"] == "pending"
    assert song["title"] == "My Song"
    assert song["original_filename"] == "My Song.wav"
    assert song["stem_mode"] == 6
    assert song["source_type"] == "file"
    assert song["stems"] == [] and song["tags"] == [] and song["favorite"] is False
    assert song["active_job"]["id"] == job["id"]
    assert job["status"] == "queued" and job["stem_mode"] == 6 and job["song_title"] == "My Song"
    assert (paths.song_dir(song["id"]) / "original.wav").read_bytes() == wav_bytes()
    assert list((paths.tmp / "api").iterdir()) == []


def test_upload_uses_default_stem_mode_setting_and_case_insensitive_ext(client):
    assert client.put("/api/settings", json={"default_stem_mode": 2}).status_code == 200
    r = _upload(client, name="LOUD.WAV")
    assert r.status_code == 201, r.text
    assert r.json()["song"]["stem_mode"] == 2


def test_upload_unsupported_format_creates_nothing(client, paths):
    r = _upload(client, name="notes.txt", data=b"hello")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "UNSUPPORTED_FORMAT"
    _assert_nothing_created(paths)


def test_upload_too_large_creates_nothing(client, paths, monkeypatch):
    monkeypatch.setattr(routes_ingest, "MAX_FILE_BYTES", 1000)
    r = _upload(client, data=b"x" * 5000)
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "FILE_TOO_LARGE"
    _assert_nothing_created(paths)


def test_upload_invalid_stem_mode(client, paths):
    r = _upload(client, stem_mode=3)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    _assert_nothing_created(paths)


def test_upload_missing_file(client, paths):
    r = client.post("/api/songs/upload", data={"stem_mode": "4"}, files={"other": ("a", b"b")})
    assert r.status_code == 422
    _assert_nothing_created(paths)


def test_upload_duplicate_by_hash(client, paths):
    first = _upload(client).json()["song"]["id"]
    r = _upload(client, name="Other name.wav")
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "DUPLICATE" and err["existing_song_id"] == first
    assert count_songs() == 1
    assert [p.name for p in paths.songs.iterdir()] == [first]


# ---------------------------------------------------------------- URL


def fake_info(**over):
    info = {"id": "dQw4w9WgXcQ", "extractor_key": "Youtube", "title": "Never Gonna", "duration": 213,
            "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}
    info.update(over)
    return info


@pytest.fixture
def mock_ytdlp(monkeypatch):
    state = {"info": fake_info(), "calls": []}

    def extract(url):
        state["calls"].append(url)
        value = state["info"]
        if isinstance(value, Exception):
            raise value
        if callable(value):
            return value(url)
        return value

    monkeypatch.setattr(routes_ingest, "_extract_info", extract)
    return state


def test_url_creates_song(client, paths, mock_ytdlp):
    r = client.post("/api/songs/url", json={"url": "https://youtu.be/dQw4w9WgXcQ", "stem_mode": 4})
    assert r.status_code == 201, r.text
    song = r.json()["song"]
    assert song["source_type"] == "url" and song["title"] == "Never Gonna" and song["status"] == "pending"
    assert song["source_url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert r.json()["job"]["status"] == "queued"
    assert paths.song_dir(song["id"]).is_dir()


def test_url_duplicate(client, mock_ytdlp):
    first = client.post("/api/songs/url", json={"url": "https://youtu.be/dQw4w9WgXcQ"}).json()["song"]["id"]
    r = client.post("/api/songs/url", json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"})
    assert r.status_code == 409
    assert r.json()["error"] == {"code": "DUPLICATE", "detail": "song already exists", "existing_song_id": first}


@pytest.mark.parametrize(
    "info, code",
    [
        (fake_info(_type="playlist", entries=[{"url": "https://a/1"}, {"url": "https://a/2"}]), "PLAYLIST_NOT_SUPPORTED"),
        (fake_info(is_live=True), "INVALID_URL"),
        (RuntimeError("Unsupported URL"), "INVALID_URL"),
        (fake_info(duration=901), "TOO_LONG"),
    ],
)
def test_url_rejections(client, paths, mock_ytdlp, info, code):
    mock_ytdlp["info"] = info
    r = client.post("/api/songs/url", json={"url": "https://example.com/v"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == code
    assert count_songs() == 0 and list(paths.songs.iterdir()) == []


def test_url_timeout(client, mock_ytdlp, monkeypatch):
    monkeypatch.setattr(routes_ingest, "URL_TIMEOUT_S", 0.1)

    def slow(url):
        time.sleep(0.5)
        return fake_info()

    mock_ytdlp["info"] = slow
    r = client.post("/api/songs/url", json={"url": "https://example.com/v"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_URL"
    assert count_songs() == 0


@pytest.mark.parametrize("url", ["ftp://example.com/a.mp3", "file:///etc/passwd", "javascript:alert(1)", "", "example.com"])
def test_url_scheme_rejected_without_calling_ytdlp(client, mock_ytdlp, url):
    r = client.post("/api/songs/url", json={"url": url})
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_URL"
    assert mock_ytdlp["calls"] == []
    assert count_songs() == 0


def test_url_single_entry_playlist_is_resolved(client, mock_ytdlp):
    def info(url):
        if url == "https://example.com/list":
            return {"_type": "playlist", "entries": [{"_type": "url", "url": "https://example.com/v1"}]}
        return fake_info(id="v1", extractor_key="Generic")

    mock_ytdlp["info"] = info
    r = client.post("/api/songs/url", json={"url": "https://example.com/list"})
    assert r.status_code == 201, r.text
    assert job_rows(r.json()["song"]["id"])[0]["status"] == "queued"
