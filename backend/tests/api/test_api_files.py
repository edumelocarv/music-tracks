"""§13 items 11 and 24: stem/peaks/analysis files and covers."""
from __future__ import annotations

import io

from api_helpers import make_song
from PIL import Image


def test_stem_file_and_etag(client):
    sid = make_song()
    r = client.get(f"/api/songs/{sid}/stems/vocals.flac")
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/flac"
    assert r.headers["cache-control"] == "no-cache"
    etag = r.headers["etag"]
    r2 = client.get(f"/api/songs/{sid}/stems/vocals.flac", headers={"If-None-Match": etag})
    assert r2.status_code == 304


def test_stem_outside_mode_is_404(client, paths):
    sid = make_song(stem_mode=4)
    # even if a stray file exists, stems outside the current mode are not served
    (paths.song_dir(sid) / "stems" / "piano.flac").write_bytes(b"x")
    for stem in ("piano", "instrumental", "nope", "..%2Fpeaks"):
        r = client.get(f"/api/songs/{sid}/stems/{stem}.flac")
        assert r.status_code == 404, stem
    assert client.get("/api/songs/not-a-uuid/stems/vocals.flac").json()["error"]["code"] == "NOT_FOUND"


def test_peaks_and_analysis(client, paths):
    sid = make_song()
    assert client.get(f"/api/songs/{sid}/peaks").json()["samples_per_peak"] == 512
    assert client.get(f"/api/songs/{sid}/analysis").json()["bpm"] == 120.0
    (paths.song_dir(sid) / "analysis.json").unlink()
    assert client.get(f"/api/songs/{sid}/analysis").status_code == 404


def _image(fmt: str, size=(2000, 1000), mode="RGB") -> bytes:
    buf = io.BytesIO()
    Image.new(mode, size, (200, 30, 30)).save(buf, fmt)
    return buf.getvalue()


def test_cover_png_resized_to_jpeg(client):
    sid = make_song()
    assert client.get(f"/api/songs/{sid}/cover").status_code == 404
    r = client.put(f"/api/songs/{sid}/cover", files={"file": ("c.png", _image("PNG"), "image/png")})
    assert r.status_code == 200, r.text
    song = r.json()
    assert song["has_cover"] is True and song["cover_url"].startswith(f"/api/songs/{sid}/cover?v=")
    r = client.get(f"/api/songs/{sid}/cover")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    img = Image.open(io.BytesIO(r.content))
    assert img.format == "JPEG" and img.size == (600, 300)

    r = client.delete(f"/api/songs/{sid}/cover")
    assert r.status_code == 200 and r.json()["has_cover"] is False and r.json()["cover_url"] is None
    assert client.get(f"/api/songs/{sid}/cover").status_code == 404


def test_cover_rgba_png(client):
    sid = make_song()
    r = client.put(f"/api/songs/{sid}/cover", files={"file": ("c.png", _image("PNG", (100, 50), "RGBA"), "image/png")})
    assert r.status_code == 200
    assert Image.open(io.BytesIO(client.get(f"/api/songs/{sid}/cover").content)).size == (100, 50)


def test_cover_rejections(client):
    sid = make_song()
    r = client.put(f"/api/songs/{sid}/cover", files={"file": ("c.gif", _image("GIF", (10, 10)), "image/gif")})
    assert r.status_code == 422 and r.json()["error"]["code"] == "UNSUPPORTED_FORMAT"
    r = client.put(f"/api/songs/{sid}/cover", files={"file": ("c.jpg", b"\xff\xd8" + b"0" * (11 * 1024 * 1024), "image/jpeg")})
    assert r.status_code == 413 and r.json()["error"]["code"] == "FILE_TOO_LARGE"
    r = client.put(f"/api/songs/{sid}/cover", files={"file": ("c.jpg", b"not an image", "image/jpeg")})
    assert r.status_code == 422
    assert client.get(f"/api/songs/{sid}").json()["has_cover"] is False
