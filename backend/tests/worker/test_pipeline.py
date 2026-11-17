"""Pipeline tests with the fake separator (spec §13: 3, 4, 5, 18, 19, 21, 22)."""
from __future__ import annotations

import errno
import json
import shutil
from collections import namedtuple

import soundfile as sf
from mutagen.id3 import APIC, ID3, TALB, TIT2, TPE1
from PIL import Image

from app import config
from app.services import create_job
from app.stems import stems_for

from .conftest import (
    add_song, get_job, get_song, to_mp3, update_job, update_song, write_silence, write_song_wav,
)


def stem_files(song_id):
    d = config.get_paths().song_dir(song_id) / "stems"
    return sorted(p.name for p in d.glob("*")) if d.is_dir() else []


def test_full_pipeline_4_stems(engine, worker, tmp_path):
    song_id, job_id = add_song(engine, write_song_wav(tmp_path / "My Song.wav", 10))
    assert get_song(engine, song_id).status == "pending"
    assert worker.run_once() == "done"
    assert worker.run_once() is None

    song = get_song(engine, song_id)
    job = get_job(engine, job_id)
    assert song.status == "ready"
    assert job.status == "done" and job.attempts == 1 and job.finished_at
    assert job.step == "peaks" and job.step_index == 4 and job.step_count == 4 and job.step_progress == 100
    assert abs(song.duration_s - 10.0) < 0.01
    assert song.analysis_status == "ok"
    assert song.bpm == 120.0
    assert song.key_label is not None
    d = config.get_paths().song_dir(song_id)
    assert stem_files(song_id) == sorted(f"{s}.flac" for s in stems_for(4))
    info = sf.info(str(d / "stems" / "vocals.flac"))
    assert info.samplerate == 44100 and info.channels == 2 and info.subtype == "PCM_24"
    peaks = json.loads((d / "peaks.json").read_text())
    assert peaks["samples_per_peak"] == 512 and peaks["sample_rate"] == 44100
    assert set(peaks["stems"]) == set(stems_for(4))
    assert len(peaks["stems"]["bass"]) == 2 * -(-441000 // 512)
    analysis = json.loads((d / "analysis.json").read_text())
    assert analysis["version"] == 1 and analysis["bpm"] == 120.0
    assert analysis["beats"][:2] == [0.0, 0.5] and analysis["downbeats"][:2] == [0.0, 2.0]
    assert analysis["key"]["label"] == song.key_label
    chords = analysis["chords"]
    assert chords and chords[0]["start"] == 0.0 and abs(chords[-1]["end"] - 10.0) < 0.01
    assert all(set(c) == {"start", "end", "label"} for c in chords)
    # work dir removed, no leftovers
    assert not (config.get_paths().tmp / "jobs" / job_id).exists()
    assert not any(p.name.endswith(".old") for p in d.iterdir())


def test_two_stem_mode_and_rescale(engine, worker, tmp_path, fake_sep):
    src = tmp_path / "loud.wav"
    write_song_wav(src, 6)
    data, sr = sf.read(str(src))
    sf.write(str(src), data * 12, sr, subtype="FLOAT")  # peaks well above 1.0
    song_id, _ = add_song(engine, src, stem_mode=2)
    assert worker.run_once() == "done"
    assert stem_files(song_id) == ["instrumental.flac", "vocals.flac"]
    d = config.get_paths().song_dir(song_id) / "stems"
    peak = max(abs(sf.read(str(d / f"{s}.flac"))[0]).max() for s in ("vocals", "instrumental"))
    assert 0.97 < peak <= 0.981


def test_analysis_failure_keeps_job_ok(engine, worker, tmp_path, fake_beats):
    fake_beats.error = RuntimeError("boom")
    song_id, job_id = add_song(engine, write_song_wav(tmp_path / "a.wav", 6))
    assert worker.run_once() == "done"
    song = get_song(engine, song_id)
    assert song.status == "ready" and song.analysis_status == "failed"
    assert song.bpm is None and song.key_label is None
    d = config.get_paths().song_dir(song_id)
    assert not (d / "analysis.json").exists()
    assert (d / "peaks.json").exists()
    assert get_job(engine, job_id).status == "done"


def test_failed_reprocess_keeps_old_stems(engine, worker, tmp_path, fake_sep):
    song_id, _ = add_song(engine, write_song_wav(tmp_path / "a.wav", 6))
    assert worker.run_once() == "done"
    d = config.get_paths().song_dir(song_id)
    before = {p.name: p.read_bytes() for p in (d / "stems").iterdir()}
    peaks_before = (d / "peaks.json").read_bytes()

    job2 = create_job(engine, song_id, 6)
    assert get_song(engine, song_id).status == "ready"
    fake_sep.failures = {"mps": ValueError("bad"), "cpu": ValueError("bad")}
    assert worker.run_once() == "failed"
    job = get_job(engine, job2["id"])
    assert job.error_code == "SEPARATION_FAILED"
    song = get_song(engine, song_id)
    assert song.status == "ready" and song.stem_mode == 4
    assert {p.name: p.read_bytes() for p in (d / "stems").iterdir()} == before
    assert (d / "peaks.json").read_bytes() == peaks_before


def test_reprocess_4_to_6(engine, worker, tmp_path):
    song_id, _ = add_song(engine, write_song_wav(tmp_path / "a.wav", 6))
    assert worker.run_once() == "done"
    create_job(engine, song_id, 6)
    assert worker.run_once() == "done"
    song = get_song(engine, song_id)
    assert song.stem_mode == 6 and song.status == "ready"
    assert stem_files(song_id) == sorted(f"{s}.flac" for s in stems_for(6))
    peaks = json.loads((config.get_paths().song_dir(song_id) / "peaks.json").read_text())
    assert list(peaks["stems"]) == stems_for(6)


# -- separation errors / disk (18) ---------------------------------------------


def test_mps_memory_error_retries_on_cpu(engine, worker, tmp_path, fake_sep):
    fake_sep.failures = {"mps": RuntimeError("MPS backend out of memory (MPS allocated: 9 GB)")}
    song_id, _ = add_song(engine, write_song_wav(tmp_path / "a.wav", 6))
    assert worker.run_once() == "done"
    assert fake_sep.calls == ["mps", "cpu"]
    assert get_song(engine, song_id).status == "ready"


def test_mps_and_cpu_memory_error_is_out_of_memory(engine, worker, tmp_path, fake_sep):
    fake_sep.failures = {"mps": RuntimeError("MPS backend out of memory"), "cpu": MemoryError("no mem")}
    song_id, job_id = add_song(engine, write_song_wav(tmp_path / "a.wav", 6))
    assert worker.run_once() == "failed"
    assert fake_sep.calls == ["mps", "cpu"]
    assert get_job(engine, job_id).error_code == "OUT_OF_MEMORY"
    assert get_song(engine, song_id).status == "failed"


class OutOfMemoryError(RuntimeError):
    """Stands in for torch.cuda.OutOfMemoryError (a RuntimeError subclass of that name)."""


def test_cuda_out_of_memory_retries_on_cpu(engine, worker, tmp_path, fake_sep, monkeypatch):
    from app.worker import separation

    emptied = []
    monkeypatch.setattr(separation, "empty_device_cache", emptied.append)
    fake_sep.device = "cuda"
    fake_sep.failures = {"cuda": OutOfMemoryError("CUDA out of memory. Tried to allocate 2.00 GiB")}
    song_id, job_id = add_song(engine, write_song_wav(tmp_path / "a.wav", 6))
    assert worker.run_once() == "done"
    assert fake_sep.calls == ["cuda", "cpu"]
    assert emptied == ["cuda"]
    assert get_song(engine, song_id).status == "ready"


def test_cuda_and_cpu_memory_error_is_out_of_memory(engine, worker, tmp_path, fake_sep):
    fake_sep.device = "cuda"
    fake_sep.failures = {"cuda": OutOfMemoryError("CUDA out of memory"), "cpu": MemoryError("no mem")}
    _, job_id = add_song(engine, write_song_wav(tmp_path / "a.wav", 6))
    assert worker.run_once() == "failed"
    assert fake_sep.calls == ["cuda", "cpu"]
    assert get_job(engine, job_id).error_code == "OUT_OF_MEMORY"


def test_cuda_non_memory_runtime_error_is_not_retried(engine, worker, tmp_path, fake_sep):
    fake_sep.device = "cuda"
    fake_sep.failures = {"cuda": RuntimeError("CUDA error: device-side assert triggered")}
    _, job_id = add_song(engine, write_song_wav(tmp_path / "a.wav", 6))
    assert worker.run_once() == "failed"
    assert fake_sep.calls == ["cuda"]
    assert get_job(engine, job_id).error_code == "SEPARATION_FAILED"


def test_best_torch_device_order(monkeypatch):
    import sys
    from types import SimpleNamespace

    from app.devices import best_torch_device

    def fake_torch(cuda: bool, mps: bool):
        return SimpleNamespace(
            cuda=SimpleNamespace(is_available=lambda: cuda),
            backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: mps)),
        )

    for cuda, mps, expected in ((True, True, "cuda"), (False, True, "mps"), (False, False, "cpu")):
        monkeypatch.setitem(sys.modules, "torch", fake_torch(cuda, mps))
        assert best_torch_device() == expected


def test_cpu_runtime_error_is_separation_failed_without_retry(engine, worker, tmp_path, fake_sep):
    fake_sep.device = "cpu"
    fake_sep.failures = {"cpu": RuntimeError("weird")}
    _, job_id = add_song(engine, write_song_wav(tmp_path / "a.wav", 6))
    assert worker.run_once() == "failed"
    assert fake_sep.calls == ["cpu"]
    job = get_job(engine, job_id)
    assert job.error_code == "SEPARATION_FAILED" and "weird" in job.error_detail


def test_low_disk_space_is_disk_full(engine, worker, tmp_path, monkeypatch):
    song_id, job_id = add_song(engine, write_song_wav(tmp_path / "a.wav", 6))
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda _p: Usage(10**12, 10**12 - 10**9, 10**9))
    assert worker.run_once() == "failed"
    assert get_job(engine, job_id).error_code == "DISK_FULL"
    assert get_song(engine, song_id).status == "failed"


def test_enospc_in_peaks_is_disk_full(engine, worker, tmp_path, monkeypatch):
    from app.worker import pipeline

    def boom(_mono):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(pipeline, "compute_peaks", boom)
    song_id, job_id = add_song(engine, write_song_wav(tmp_path / "a.wav", 6))
    assert worker.run_once() == "failed"
    job = get_job(engine, job_id)
    assert job.error_code == "DISK_FULL" and job.step == "peaks"
    assert get_song(engine, song_id).status == "failed"
    assert not (config.get_paths().song_dir(song_id) / "stems").exists()


def test_unexpected_error_is_internal_error(engine, worker, tmp_path, monkeypatch):
    from app.worker import pipeline

    monkeypatch.setattr(pipeline, "compute_peaks", lambda _m: 1 / 0)
    _, job_id = add_song(engine, write_song_wav(tmp_path / "a.wav", 6))
    assert worker.run_once() == "failed"
    job = get_job(engine, job_id)
    assert job.error_code == "INTERNAL_ERROR"
    assert job.error_detail.startswith("ZeroDivisionError: ")


def test_model_download_sets_step_detail(engine, worker, tmp_path, fake_sep):
    seen = []
    fake_sep.cached = False
    orig_load = fake_sep.load

    def load(model):
        seen.append(get_job(engine, job_id).step_detail)
        orig_load(model)

    fake_sep.load = load
    _, job_id = add_song(engine, write_song_wav(tmp_path / "a.wav", 6))
    assert worker.run_once() == "done"
    assert seen == ["downloading_model"]
    assert get_job(engine, job_id).step_detail is None


# -- prepare validation (19) ---------------------------------------------------


def test_prepare_too_short(engine, worker, tmp_path):
    song_id, job_id = add_song(engine, write_silence(tmp_path / "short.wav", 3))
    assert worker.run_once() == "failed"
    assert get_job(engine, job_id).error_code == "TOO_SHORT"
    assert get_song(engine, song_id).status == "failed"


def test_prepare_too_long(engine, worker, tmp_path):
    song_id, job_id = add_song(engine, write_silence(tmp_path / "long.wav", 15 * 60 + 1))
    assert worker.run_once() == "failed"
    job = get_job(engine, job_id)
    assert job.error_code == "TOO_LONG" and job.step == "prepare"
    assert get_song(engine, song_id).status == "failed"


def test_prepare_corrupt_mp3(engine, worker, tmp_path):
    bad = tmp_path / "bad.mp3"
    bad.write_bytes(b"ID3\x03\x00\x00\x00\x00\x00\x00" + bytes(range(256)) * 50)
    song_id, job_id = add_song(engine, bad)
    assert worker.run_once() == "failed"
    assert get_job(engine, job_id).error_code == "INVALID_AUDIO"
    assert get_song(engine, song_id).status == "failed"


# -- metadata (22) -------------------------------------------------------------


def make_tagged_mp3(tmp_path):
    mp3 = to_mp3(write_song_wav(tmp_path / "raw.wav", 6), tmp_path / "file name.mp3")
    cover = tmp_path / "c.png"
    Image.new("RGB", (1200, 800), (200, 30, 30)).save(cover)
    tags = ID3()
    tags.add(TIT2(encoding=3, text="Tag Title"))
    tags.add(TPE1(encoding=3, text="Tag Artist"))
    tags.add(TALB(encoding=3, text="Tag Album"))
    tags.add(APIC(encoding=3, mime="image/png", type=3, desc="cover", data=cover.read_bytes()))
    tags.save(str(mp3))
    return mp3


def test_metadata_from_tags_and_reprocess_rules(engine, worker, tmp_path):
    song_id, _ = add_song(engine, make_tagged_mp3(tmp_path))
    assert get_song(engine, song_id).title == "file name"
    assert worker.run_once() == "done"
    song = get_song(engine, song_id)
    assert (song.title, song.artist, song.album, song.has_cover) == ("Tag Title", "Tag Artist", "Tag Album", 1)
    cover = config.get_paths().song_dir(song_id) / "cover.jpg"
    with Image.open(cover) as im:
        assert im.format == "JPEG" and im.size == (600, 400)

    # PATCH title (+ artist changed by the user) then reprocess -> preserved
    update_song(engine, song_id, title="My Title", artist="Someone", metadata_edited=1)
    create_job(engine, song_id, 4)
    assert worker.run_once() == "done"
    song = get_song(engine, song_id)
    assert (song.title, song.artist, song.album) == ("My Title", "Someone", "Tag Album")

    # DELETE cover then reprocess -> still no cover
    cover.unlink()
    update_song(engine, song_id, has_cover=0)
    create_job(engine, song_id, 6)
    assert worker.run_once() == "done"
    assert get_song(engine, song_id).has_cover == 0 and not cover.exists()


def test_reprocess_never_touches_artist_album(engine, worker, tmp_path):
    song_id, _ = add_song(engine, make_tagged_mp3(tmp_path))
    assert worker.run_once() == "done"
    update_song(engine, song_id, artist=None, album="Other")  # metadata_edited stays 0
    create_job(engine, song_id, 4)
    assert worker.run_once() == "done"
    song = get_song(engine, song_id)
    assert song.artist is None and song.album == "Other"


def test_failed_after_prepare_then_delete_cover_and_retry(engine, worker, tmp_path, fake_sep):
    song_id, job_id = add_song(engine, make_tagged_mp3(tmp_path))
    fake_sep.failures = {"mps": ValueError("x")}
    assert worker.run_once() == "failed"
    song = get_song(engine, song_id)
    assert song.status == "failed" and song.has_cover == 1 and song.duration_s
    cover = config.get_paths().song_dir(song_id) / "cover.jpg"
    cover.unlink()
    update_song(engine, song_id, has_cover=0)
    fake_sep.failures = {}
    create_job(engine, song_id, get_job(engine, job_id).stem_mode)  # retry
    assert worker.run_once() == "done"
    assert get_song(engine, song_id).has_cover == 0 and not cover.exists()


# -- deletion during a job / shutdown ------------------------------------------


def test_song_deleted_during_separation(engine, worker, tmp_path, fake_sep):
    from sqlalchemy import delete

    from app import db

    song_id, job_id = add_song(engine, write_song_wav(tmp_path / "a.wav", 6))
    d = config.get_paths().song_dir(song_id)

    def on_chunk(i):
        if i == 1:
            with engine.begin() as conn:
                conn.execute(delete(db.songs).where(db.songs.c.id == song_id))
            shutil.rmtree(d)

    fake_sep.on_chunk = on_chunk
    assert worker.run_once() == "gone"
    assert get_job(engine, job_id) is None
    assert not d.exists()
    assert not (config.get_paths().tmp / "jobs" / job_id).exists()


def test_graceful_stop_requeues_job(engine, worker, tmp_path, fake_sep, deps):
    song_id, job_id = add_song(engine, write_song_wav(tmp_path / "a.wav", 6))
    fake_sep.on_chunk = lambda i: deps.stop_event.set() if i == 1 else None
    assert worker.run_once() == "queued"
    job = get_job(engine, job_id)
    assert job.status == "queued" and job.attempts == 0 and job.step is None
    assert get_song(engine, song_id).status == "pending"
    deps.stop_event.clear()
    fake_sep.on_chunk = None
    assert worker.run_once() == "done"
