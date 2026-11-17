"""yt-dlp download step with a mocked YoutubeDL (spec §13: 23)."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from PIL import Image

from app import config
from app.services import create_job
from app.worker import download

from .conftest import add_url_song, get_job, get_song, write_song_wav


class FakeYDL:
    info: dict = {}
    audio_src: Path | None = None
    error: BaseException | None = None
    skip_download = False
    last_opts: dict = {}

    def __init__(self, opts):
        FakeYDL.last_opts = opts
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=True):
        if FakeYDL.error:
            raise FakeYDL.error
        tmpl = self.opts["outtmpl"]
        info = dict(FakeYDL.info)
        if not FakeYDL.skip_download:
            dest = Path(tmpl.replace("%(ext)s", "m4a"))
            shutil.copy(FakeYDL.audio_src, dest)
            for hook in self.opts["progress_hooks"]:
                hook({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100})
                hook({"status": "finished", "downloaded_bytes": 100, "total_bytes": 100})
            info["requested_downloads"] = [{"filepath": str(dest)}]
            Image.new("RGB", (1280, 720), (10, 200, 10)).save(tmpl.replace("%(ext)s", "webp"), "WEBP")
        return info


@pytest.fixture
def fake_ydl(monkeypatch, tmp_path):
    FakeYDL.audio_src = write_song_wav(tmp_path / "dl.wav", 6)
    FakeYDL.info = {"id": "abc", "extractor": "youtube", "title": "Video Title", "creator": "The Creator",
                    "uploader": "Uploader", "album": "An Album", "filesize": 1000}
    FakeYDL.error = None
    FakeYDL.skip_download = False
    monkeypatch.setattr(download, "YDL_FACTORY", FakeYDL)
    return FakeYDL


def test_download_full_pipeline(engine, worker, fake_ydl):
    song_id, job_id = add_url_song(engine)
    assert worker.run_once() == "done"
    opts = fake_ydl.last_opts
    assert opts["format"] == "bestaudio/best" and opts["noplaylist"] is True
    assert opts["max_filesize"] == 500 * 1024 * 1024 and opts["js_runtimes"] == {"node": {}}
    job = get_job(engine, job_id)
    assert job.step_count == 5 and job.step_index == 5 and job.status == "done"
    song = get_song(engine, song_id)
    assert (song.title, song.artist, song.album) == ("Video Title", "The Creator", "An Album")
    assert song.original_ext == "m4a" and song.status == "ready" and song.has_cover == 1
    d = config.get_paths().song_dir(song_id)
    assert (d / "original.m4a").exists()
    with Image.open(d / "cover.jpg") as im:
        assert im.format == "JPEG" and max(im.size) <= 600 and im.size == (600, 338)


@pytest.mark.parametrize(
    ("fields", "expected"),
    [({"artist": "A", "creator": "C", "uploader": "U"}, "A"), ({"uploader": "U"}, "U")],
)
def test_artist_fallback_chain(engine, worker, fake_ydl, fields, expected):
    fake_ydl.info = {"title": "T", **fields}
    song_id, _ = add_url_song(engine)
    assert worker.run_once() == "done"
    assert get_song(engine, song_id).artist == expected


def test_download_exception_is_download_failed(engine, worker, fake_ydl):
    fake_ydl.error = RuntimeError("HTTP Error 403")
    song_id, job_id = add_url_song(engine)
    assert worker.run_once() == "failed"
    job = get_job(engine, job_id)
    assert job.error_code == "DOWNLOAD_FAILED" and "403" in job.error_detail
    assert get_song(engine, song_id).status == "failed"


def test_skipped_download_is_file_too_large(engine, worker, fake_ydl):
    fake_ydl.skip_download = True
    fake_ydl.info = {"title": "T", "filesize_approx": 600 * 1024 * 1024}
    _, job_id = add_url_song(engine)
    assert worker.run_once() == "failed"
    assert get_job(engine, job_id).error_code == "FILE_TOO_LARGE"


def test_retry_with_existing_original_skips_download(engine, worker, fake_ydl, fake_sep):
    song_id, job_id = add_url_song(engine)
    fake_sep.failures = {"mps": ValueError("x")}
    assert worker.run_once() == "failed"
    assert get_job(engine, job_id).step_count == 5
    fake_sep.failures = {}
    fake_ydl.error = RuntimeError("must not be called")
    job2 = create_job(engine, song_id, 4)
    assert worker.run_once() == "done"
    job = get_job(engine, job2["id"])
    assert job.step_count == 4 and job.step_index == 4
