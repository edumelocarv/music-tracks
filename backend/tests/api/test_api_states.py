"""§13 item 14: job/song state rules through the API."""
from __future__ import annotations

import threading
import time

from api_helpers import HOST, job_rows, make_song
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app import db
from app.api import routes_songs


def _job(song_id):
    return job_rows(song_id)[0]


def test_retry_done_job_invalid_state(client):
    sid = make_song()
    r = client.post(f"/api/jobs/{_job(sid)['id']}/retry")
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_STATE"


def test_cancel_failed_job_invalid_state(client):
    sid = make_song(status="failed", job_status="failed", with_files=False)
    r = client.post(f"/api/jobs/{_job(sid)['id']}/cancel")
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_STATE"


def test_retry_failed_job_creates_new_job(client):
    sid = make_song(status="failed", job_status="failed", with_files=False, stem_mode=6)
    r = client.post(f"/api/jobs/{_job(sid)['id']}/retry")
    assert r.status_code == 201, r.text
    job = r.json()["job"]
    assert job["status"] == "queued" and job["stem_mode"] == 6 and job["song_title"] == "Song"
    assert client.get(f"/api/songs/{sid}").json()["status"] == "pending"
    # a second retry while the new job is active
    r = client.post(f"/api/jobs/{_job(sid)['id']}/retry")
    assert r.status_code == 409 and r.json()["error"]["code"] == "JOB_ALREADY_ACTIVE"


def test_reprocess_with_active_job(client):
    sid = make_song()
    first = client.post(f"/api/songs/{sid}/reprocess", json={"stem_mode": 6})
    assert first.status_code == 201
    # song keeps its stems -> stays ready with the old mode
    song = client.get(f"/api/songs/{sid}").json()
    assert song["status"] == "ready" and song["stem_mode"] == 4 and song["active_job"]["stem_mode"] == 6
    r = client.post(f"/api/songs/{sid}/reprocess", json={"stem_mode": 4})
    assert r.status_code == 409 and r.json()["error"]["code"] == "JOB_ALREADY_ACTIVE"
    assert client.post(f"/api/songs/{sid}/reprocess", json={"stem_mode": 5}).status_code == 422


def test_export_of_failed_song(client):
    sid = make_song(status="failed", job_status="failed")
    r = client.get(f"/api/songs/{sid}/export/zip", params={"format": "wav"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "SONG_NOT_READY"
    r = client.post(f"/api/songs/{sid}/export/mix", json={"gains": {"vocals": 1}, "format": "wav"})
    assert r.status_code == 409


def test_cancel_queued_and_running(client):
    sid = make_song(status="pending", job_status="queued", with_files=False)
    jid = _job(sid)["id"]
    r = client.post(f"/api/jobs/{jid}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "canceled"
    assert client.get(f"/api/songs/{sid}").json()["status"] == "failed"

    sid2 = make_song(status="processing", job_status="running", with_files=False)
    jid2 = _job(sid2)["id"]
    r = client.post(f"/api/jobs/{jid2}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "running"
    assert _job(sid2)["cancel_requested"] == 1


def test_delete_with_running_job(client, paths, monkeypatch):
    monkeypatch.setattr(routes_songs, "DELETE_POLL_S", 0.02)
    sid = make_song(job_status="running")
    jid = _job(sid)["id"]

    def fake_worker():
        # Acknowledge cancellation like the worker would.
        for _ in range(200):
            with db.get_engine().begin() as conn:
                flag = conn.execute(select(db.jobs.c.cancel_requested).where(db.jobs.c.id == jid)).scalar()
                if flag:
                    conn.execute(update(db.jobs).where(db.jobs.c.id == jid).values(status="canceled"))
                    return
            time.sleep(0.01)

    t = threading.Thread(target=fake_worker)
    t.start()
    r = client.delete(f"/api/songs/{sid}")
    t.join()
    assert r.status_code == 204
    assert not paths.song_dir(sid).exists()
    assert client.get(f"/api/songs/{sid}").status_code == 404
    assert job_rows(sid) == []


def test_delete_gives_up_waiting(client, paths, monkeypatch):
    monkeypatch.setattr(routes_songs, "DELETE_WAIT_S", 0.1)
    monkeypatch.setattr(routes_songs, "DELETE_POLL_S", 0.02)
    sid = make_song(job_status="running")
    assert client.delete(f"/api/songs/{sid}").status_code == 204
    assert not paths.song_dir(sid).exists()
    assert job_rows(sid) == []


def test_concurrent_job_creation(client):
    from app.api.main import app

    sid = make_song()
    results = []
    barrier = threading.Barrier(2)

    def go(mode):
        c = TestClient(app, base_url=f"http://{HOST}", raise_server_exceptions=False)
        barrier.wait()
        results.append(c.post(f"/api/songs/{sid}/reprocess", json={"stem_mode": mode}).status_code)

    threads = [threading.Thread(target=go, args=(m,)) for m in (4, 6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [201, 409]
    assert len([j for j in job_rows(sid) if j["status"] == "queued"]) == 1


def test_jobs_list_order(client):
    a = make_song(title="A", job_status="queued", status="pending", with_files=False)
    b = make_song(title="B", job_status="done")
    jobs = client.get("/api/jobs").json()["jobs"]
    assert [j["song_id"] for j in jobs] == [a, b]
    assert jobs[0]["song_title"] == "A"
    assert client.get("/api/jobs", params={"limit": 0}).json()["jobs"][0]["song_id"] == a
    assert len(client.get("/api/jobs", params={"limit": 0}).json()["jobs"]) == 1
