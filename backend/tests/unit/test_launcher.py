"""Launcher helpers (portable: no real servers, no browser)."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time

import pytest

from app import launcher


def test_install_hints_per_os():
    assert launcher.install_hint(["ffmpeg", "ffprobe", "npm"], "darwin")[0] == "brew install ffmpeg node"
    assert launcher.install_hint(["node"], "win32")[0] == "winget install OpenJS.NodeJS.LTS"
    assert launcher.install_hint(["ffprobe", "node"], "win32")[0] == "winget install Gyan.FFmpeg OpenJS.NodeJS.LTS"
    assert launcher.install_hint(["ffmpeg", "npm"], "linux", {"ubuntu", "debian"}) == ["sudo apt install ffmpeg nodejs npm"]
    assert launcher.install_hint(["ffmpeg"], "linux", {"fedora"})[0] == "sudo dnf install ffmpeg"
    assert launcher.install_hint(["node"], "linux", {"arch"}) == ["sudo pacman -S nodejs npm"]
    assert "ffmpeg" in launcher.install_hint(["ffmpeg"], "linux", set())[0]


def test_linux_distro_ids(tmp_path):
    f = tmp_path / "os-release"
    f.write_text('NAME="Linux Mint"\nID=linuxmint\nID_LIKE="ubuntu debian"\n')
    assert launcher.linux_distro_ids(f) == {"linuxmint", "ubuntu", "debian"}
    assert launcher.linux_distro_ids(tmp_path / "missing") == set()


def test_port_in_use():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        port = s.getsockname()[1]
        assert launcher.port_in_use(port)
    assert not launcher.port_in_use(port)


def test_frontend_needs_build(tmp_path):
    (tmp_path / "src").mkdir()
    src = tmp_path / "src" / "main.tsx"
    src.write_text("x")
    assert launcher.frontend_needs_build(tmp_path)  # no dist
    (tmp_path / "dist").mkdir()
    index = tmp_path / "dist" / "index.html"
    index.write_text("<html>")
    # Explicit timestamps: on Windows two files written back to back can share an mtime.
    old = time.time() - 100
    os.utime(src, (old, old))
    os.utime(index, (old + 50, old + 50))
    assert not launcher.frontend_needs_build(tmp_path)
    (tmp_path / "package.json").write_text("{}")  # newer than dist
    assert launcher.frontend_needs_build(tmp_path)
    os.utime(tmp_path / "package.json", (old, old))
    assert not launcher.frontend_needs_build(tmp_path)
    src.write_text("y")
    assert launcher.frontend_needs_build(tmp_path)
    for p in (tmp_path / "src").iterdir():
        p.unlink()
    (tmp_path / "src").rmdir()
    assert not launcher.frontend_needs_build(tmp_path)  # prebuilt dist only (Docker)


def test_node_modules_outdated(tmp_path):
    lock = tmp_path / "package-lock.json"
    lock.write_text("{}")
    assert launcher.node_modules_outdated(tmp_path)
    (tmp_path / "node_modules").mkdir()
    marker = tmp_path / "node_modules" / ".package-lock.json"
    marker.write_text("{}")
    old = time.time() - 100
    os.utime(lock, (old, old))
    assert not launcher.node_modules_outdated(tmp_path)
    os.utime(marker, (old - 100, old - 100))
    assert launcher.node_modules_outdated(tmp_path)


def test_parse_args(monkeypatch):
    monkeypatch.delenv("MUSIC_TRACKS_PORT", raising=False)
    monkeypatch.delenv("MUSIC_TRACKS_NO_BROWSER", raising=False)
    a = launcher.parse_args([])
    assert a.port == 8765 and not a.no_browser and not a.dev
    monkeypatch.setenv("MUSIC_TRACKS_PORT", "9001")
    monkeypatch.setenv("MUSIC_TRACKS_NO_BROWSER", "1")
    a = launcher.parse_args(["--dev"])
    assert a.port == 9001 and a.no_browser and a.dev
    assert launcher.parse_args(["--port", "9100"]).port == 9100
    with pytest.raises(SystemExit):
        launcher.parse_args(["--port", "70000"])


def test_health_url():
    assert launcher.health_url("127.0.0.1", 8765) == ("http://127.0.0.1:8765/api/health", "127.0.0.1:8765")
    assert launcher.health_url("0.0.0.0", 9000) == ("http://127.0.0.1:9000/api/health", "127.0.0.1:9000")


def test_child_env(monkeypatch):
    monkeypatch.delenv("MUSIC_TRACKS_DEV", raising=False)
    env = launcher.child_env(9002, dev=False)
    assert env["MUSIC_TRACKS_PORT"] == "9002" and "MUSIC_TRACKS_DEV" not in env
    assert launcher.child_env(9002, dev=True)["MUSIC_TRACKS_DEV"] == "1"


def test_child_stop_and_kill(tmp_path):
    """A child in its own process group is stopped (gracefully or, failing that, killed)."""
    code = "import time\nwhile True:\n    time.sleep(0.1)\n"
    child = launcher.Child("sleeper", [sys.executable, "-c", code], tmp_path, dict(os.environ))
    child.start()
    assert child.alive()
    t0 = time.monotonic()
    launcher.stop_all([child, None], timeout=5)
    assert not child.alive()
    assert time.monotonic() - t0 < 15


def test_child_restart_after_crash(tmp_path):
    child = launcher.Child("crasher", [sys.executable, "-c", "raise SystemExit(3)"], tmp_path, dict(os.environ))
    child.start()
    child.proc.wait(timeout=30)
    assert not child.alive() and child.returncode == 3
    child.start()  # the launcher restarts the same Child object
    child.proc.wait(timeout=30)
    assert child.returncode == 3


def test_launcher_module_runs_help():
    out = subprocess.run([sys.executable, "-m", "app.launcher", "--help"], capture_output=True, text=True,
                         cwd=launcher.BACKEND_DIR, timeout=60)
    assert out.returncode == 0 and "--no-browser" in out.stdout
