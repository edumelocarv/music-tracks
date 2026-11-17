"""Watch folder (spec §13: 7, 20)."""
from __future__ import annotations

import shutil

from app import config, db
from app.worker.main import WatchScanner

from .conftest import add_song, get_song, write_song_wav


def ignored_names():
    return sorted(p.name for p in config.get_paths().ignored.iterdir())


def test_growing_file_not_imported_until_stable(engine, tmp_path):
    scanner = WatchScanner(engine)
    inbox = config.get_paths().inbox
    target = inbox / "song.wav"
    write_song_wav(tmp_path / "src.wav", 6)
    data = (tmp_path / "src.wav").read_bytes()
    target.write_bytes(data[: len(data) // 2])
    assert scanner.scan_once() == []
    with open(target, "ab") as fh:  # still being copied
        fh.write(data[len(data) // 2 :])
    assert scanner.scan_once() == []
    assert target.exists()
    created = scanner.scan_once()  # unchanged across two scans -> import
    assert len(created) == 1
    song = get_song(engine, created[0])
    assert song.source_type == "watch" and song.title == "song" and song.status == "pending"
    assert song.original_filename == "song.wav" and song.source_key.startswith("sha256:")
    assert song.stem_mode == 4
    assert (config.get_paths().song_dir(created[0]) / "original.wav").exists()
    assert not target.exists()


def test_watch_uses_default_stem_mode(engine, tmp_path):
    with engine.begin() as conn:
        db.set_setting(conn, "default_stem_mode", 6)
    write_song_wav(config.get_paths().inbox / "x.wav", 6)
    scanner = WatchScanner(engine)
    scanner.scan_once()
    (created,) = scanner.scan_once()
    assert get_song(engine, created).stem_mode == 6


def test_unsupported_goes_to_ignorados_with_suffixes(engine):
    scanner = WatchScanner(engine)
    inbox = config.get_paths().inbox
    (inbox / ".hidden.txt").write_text("x")
    (inbox / "notes.txt").write_text("hello")
    scanner.scan_once()
    assert scanner.scan_once() == []
    (inbox / "notes.txt").write_text("again")
    scanner.scan_once()
    scanner.scan_once()
    assert ignored_names() == ["notes (2).txt", "notes (2).txt.erro.txt", "notes.txt", "notes.txt.erro.txt"]
    assert "UNSUPPORTED_FORMAT" in (config.get_paths().ignored / "notes.txt.erro.txt").read_text()
    assert (inbox / ".hidden.txt").exists()


def test_duplicate_hash_goes_to_ignorados(engine, tmp_path):
    src = write_song_wav(tmp_path / "a.wav", 6)
    scanner = WatchScanner(engine)
    inbox = config.get_paths().inbox
    shutil.copy(src, inbox / "a.wav")
    scanner.scan_once()
    (existing,) = scanner.scan_once()
    shutil.copy(src, inbox / "copy.wav")
    scanner.scan_once()
    assert scanner.scan_once() == []
    assert ignored_names() == ["copy.wav", "copy.wav.erro.txt"]
    text = (config.get_paths().ignored / "copy.wav.erro.txt").read_text()
    assert "DUPLICATE" in text and existing in text
    assert len(list(config.get_paths().songs.iterdir())) == 1


def test_too_large_goes_to_ignorados(engine, monkeypatch):
    from app.worker import main

    monkeypatch.setattr(main, "MAX_FILE_BYTES", 10)
    (config.get_paths().inbox / "big.mp3").write_bytes(b"x" * 100)
    scanner = WatchScanner(engine)
    scanner.scan_once()
    scanner.scan_once()
    assert "FILE_TOO_LARGE" in (config.get_paths().ignored / "big.mp3.erro.txt").read_text()


def test_watch_import_runs_through_pipeline(engine, worker, tmp_path):
    write_song_wav(config.get_paths().inbox / "Track.WAV", 6)
    worker.scanner.scan_once()
    (song_id,) = worker.scanner.scan_once()
    assert worker.run_once() == "done"
    song = get_song(engine, song_id)
    assert song.status == "ready" and song.original_ext == "wav"
