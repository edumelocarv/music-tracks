"""Portable file helpers (Windows semantics: replace over existing files, locked files)."""
from __future__ import annotations

import os

import pytest

from app import fsutil


def test_replace_overwrites_existing_file(tmp_path):
    src, dst = tmp_path / "a.tmp", tmp_path / "a"
    src.write_text("new")
    dst.write_text("old")
    fsutil.replace(src, dst)
    assert dst.read_text() == "new" and not src.exists()


def test_replace_directory_to_free_name(tmp_path):
    (tmp_path / "stems").mkdir()
    (tmp_path / "stems" / "x.flac").write_bytes(b"1")
    fsutil.replace(tmp_path / "stems", tmp_path / "stems.old")
    assert (tmp_path / "stems.old" / "x.flac").read_bytes() == b"1"


def test_remove_path(tmp_path):
    d = tmp_path / "d"
    (d / "sub").mkdir(parents=True)
    (d / "sub" / "f").write_text("x")
    f = tmp_path / "f"
    f.write_text("x")
    assert fsutil.remove_path(d) and not d.exists()
    assert fsutil.remove_path(f) and not f.exists()
    assert fsutil.remove_path(tmp_path / "missing")


@pytest.mark.skipif(os.name != "nt", reason="only Windows locks open files")
def test_remove_open_file_on_windows(tmp_path):
    f = tmp_path / "locked"
    f.write_text("x")
    with open(f) as fh:
        assert fsutil.remove_path(f, timeout=0.2) is False
        fh.read()
    assert fsutil.remove_path(f)
