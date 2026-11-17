"""Cancellation and recovery (spec §13: 6, 13)."""
from __future__ import annotations

from app import config
from app.worker.main import claim_next, recover

from .conftest import add_song, get_job, get_song, update_job, write_song_wav


def test_cancel_queued_job_is_skipped(engine, worker, tmp_path):
    song_id, job_id = add_song(engine, write_song_wav(tmp_path / "a.wav", 6))
    update_job(engine, job_id, status="canceled")  # what the API does for queued jobs
    assert worker.run_once() is None
    assert get_job(engine, job_id).attempts == 0


def test_cancel_running_job(engine, worker, tmp_path, fake_sep):
    song_id, job_id = add_song(engine, write_song_wav(tmp_path / "a.wav", 6))
    fake_sep.on_chunk = lambda i: update_job(engine, job_id, cancel_requested=1) if i == 1 else None
    assert worker.run_once() == "canceled"
    job = get_job(engine, job_id)
    assert job.status == "canceled" and job.error_code is None and job.finished_at
    assert job.step == "separate"
    assert get_song(engine, song_id).status == "failed"
    assert not (config.get_paths().tmp / "jobs" / job_id).exists()
    assert not (config.get_paths().song_dir(song_id) / "stems").exists()


def test_cancel_running_reprocess_keeps_ready(engine, worker, tmp_path, fake_sep):
    from app.services import create_job

    song_id, _ = add_song(engine, write_song_wav(tmp_path / "a.wav", 6))
    assert worker.run_once() == "done"
    job2 = create_job(engine, song_id, 6)
    fake_sep.on_chunk = lambda i: update_job(engine, job2["id"], cancel_requested=1)
    assert worker.run_once() == "canceled"
    song = get_song(engine, song_id)
    assert song.status == "ready" and song.stem_mode == 4


def test_running_job_recovered_after_restart(engine, worker, tmp_path):
    song_id, job_id = add_song(engine, write_song_wav(tmp_path / "a.wav", 6))
    assert claim_next(engine) == job_id  # worker "crashes" right after claiming
    assert get_song(engine, song_id).status == "processing"
    (config.get_paths().tmp / "jobs" / job_id).mkdir(parents=True)
    recover(engine)
    job = get_job(engine, job_id)
    assert job.status == "queued" and job.attempts == 1
    assert get_song(engine, song_id).status == "pending"
    assert not (config.get_paths().tmp / "jobs" / job_id).exists()
    assert worker.run_once() == "done"
    assert get_job(engine, job_id).attempts == 2


def test_running_job_with_two_attempts_fails(engine, tmp_path):
    song_id, job_id = add_song(engine, write_song_wav(tmp_path / "a.wav", 6))
    claim_next(engine)
    update_job(engine, job_id, attempts=2)
    recover(engine)
    job = get_job(engine, job_id)
    assert job.status == "failed" and job.error_code == "INTERNAL_ERROR"
    assert job.error_detail == "worker crashed twice"
    assert get_song(engine, song_id).status == "failed"


def _setup_swap_crash(engine, worker, tmp_path, fake_sep):
    """A finished song, then a reprocess that crashed in the middle of the swap."""
    from app.services import create_job

    song_id, _ = add_song(engine, write_song_wav(tmp_path / "a.wav", 6))
    assert worker.run_once() == "done"
    d = config.get_paths().song_dir(song_id)
    job2 = create_job(engine, song_id, 6)
    claim_next(engine)
    # Simulated half-done swap: old renamed to .old, new ones moved in.
    for name in ("stems", "peaks.json", "analysis.json"):
        (d / name).rename(d / f"{name}.old")
    (d / "stems").mkdir()
    (d / "stems" / "guitar.flac").write_bytes(b"new")
    (d / "peaks.json").write_text("new")
    return song_id, job2["id"], d


def test_recovery_restores_old_when_job_running(engine, worker, tmp_path, fake_sep):
    song_id, job_id, d = _setup_swap_crash(engine, worker, tmp_path, fake_sep)
    recover(engine)
    assert sorted(p.name for p in (d / "stems").iterdir()) == ["bass.flac", "drums.flac", "other.flac", "vocals.flac"]
    assert (d / "peaks.json").read_text() != "new"
    assert (d / "analysis.json").exists()
    assert not any(p.name.endswith(".old") for p in d.iterdir())
    assert get_job(engine, job_id).status == "queued"
    assert get_song(engine, song_id).status == "ready"


def test_recovery_deletes_old_when_job_done(engine, worker, tmp_path, fake_sep):
    song_id, job_id, d = _setup_swap_crash(engine, worker, tmp_path, fake_sep)
    update_job(engine, job_id, status="done")
    recover(engine)
    assert not any(p.name.endswith(".old") for p in d.iterdir())
    assert (d / "stems" / "guitar.flac").read_bytes() == b"new"
    assert (d / "peaks.json").read_text() == "new"
