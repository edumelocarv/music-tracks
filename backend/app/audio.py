"""ffprobe/ffmpeg helpers and audio file I/O (spec §7.2, §8.1).

Self-contained: only depends on the standard library, numpy and soundfile.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import soundfile as sf

SAMPLE_RATE = 44100
_HOMEBREW_BIN = "/opt/homebrew/bin"


class AudioError(Exception):
    """ffprobe/ffmpeg could not read or convert the file."""

    def __init__(self, message: str, *, no_space: bool = False) -> None:
        super().__init__(message)
        self.no_space = no_space


def _which(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    candidate = os.path.join(_HOMEBREW_BIN, name)
    if os.path.exists(candidate):
        return candidate
    return name


def ffmpeg_bin() -> str:
    return _which("ffmpeg")


def ffprobe_bin() -> str:
    return _which("ffprobe")


def ffmpeg_version() -> str | None:
    """Returns e.g. '8.1.2' or None if ffmpeg is unavailable."""
    try:
        out = subprocess.run(
            [ffmpeg_bin(), "-version"], capture_output=True, text=True, timeout=10
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    first = out.splitlines()[0] if out else ""
    parts = first.split()
    if len(parts) >= 3 and parts[0] == "ffmpeg" and parts[1] == "version":
        return parts[2]
    return None


@dataclass(frozen=True)
class ProbeResult:
    duration_s: float | None
    codec: str | None
    channels: int | None
    sample_rate: int | None


def probe(path: Path | str, timeout: float = 60) -> ProbeResult:
    """Inspects the first audio stream. Raises AudioError if there is none or the file is unreadable."""
    cmd = [
        ffprobe_bin(), "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise AudioError("ffprobe timed out") from exc
    if proc.returncode != 0:
        raise AudioError(f"ffprobe failed: {proc.stderr.strip()[:500]}")
    try:
        data = json.loads(proc.stdout or "{}")
    except ValueError as exc:
        raise AudioError("ffprobe returned invalid JSON") from exc
    streams = [s for s in data.get("streams", []) if s.get("codec_type") == "audio"]
    if not streams:
        raise AudioError("no audio stream")
    st = streams[0]
    duration = _float(st.get("duration")) or _float(data.get("format", {}).get("duration"))
    return ProbeResult(
        duration_s=duration,
        codec=st.get("codec_name"),
        channels=_int(st.get("channels")),
        sample_rate=_int(st.get("sample_rate")),
    )


def _float(v) -> float | None:  # noqa: ANN001
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _int(v) -> int | None:  # noqa: ANN001
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def convert_to_wav(
    src: Path | str,
    dst: Path | str,
    *,
    duration_hint: float | None = None,
    on_progress: Callable[[float], None] | None = None,
) -> None:
    """Converts the first audio stream to 44.1 kHz stereo float32 WAV (mono is duplicated).

    `on_progress(fraction)` is called periodically; it may raise to abort (the ffmpeg
    process is killed and the exception propagates). Raises AudioError on ffmpeg failure.
    """
    cmd = [
        ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(src), "-map", "0:a:0", "-vn", "-ac", "2", "-ar", str(SAMPLE_RATE),
        "-c:a", "pcm_f32le", "-f", "wav", str(dst),
        "-progress", "pipe:1", "-nostats",
    ]
    # stderr goes to a temp file: a pipe could fill up (>64 KB of decode errors on a
    # damaged file) and block ffmpeg while we only read stdout.
    err_file = tempfile.TemporaryFile(mode="w+b")
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=err_file, text=True, bufsize=1
    )
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if on_progress is None:
                continue
            if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                try:
                    us = int(line.split("=", 1)[1])
                except ValueError:
                    continue
                if duration_hint:
                    on_progress(min(1.0, us / 1e6 / duration_hint))
            elif line == "progress=continue":
                on_progress(-1.0)  # heartbeat: lets the caller check cancellation
        proc.wait()
    except BaseException:
        proc.kill()
        proc.wait()
        raise
    finally:
        err_file.seek(0, 2)
        size = err_file.tell()
        err_file.seek(max(0, size - 4000))
        stderr = err_file.read().decode("utf-8", "replace")
        err_file.close()
    if proc.returncode != 0:
        msg = stderr.strip()[:500] or f"ffmpeg exited with {proc.returncode}"
        raise AudioError(f"ffmpeg conversion failed: {msg}", no_space="No space left" in stderr)


def read_audio(path: Path | str) -> tuple[np.ndarray, int]:
    """Reads an audio file as float32, shape (frames, channels)."""
    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    return data, sr


def read_mono(path: Path | str) -> tuple[np.ndarray, int]:
    data, sr = read_audio(path)
    return data.mean(axis=1).astype(np.float32), sr


def audio_duration(path: Path | str) -> float:
    info = sf.info(str(path))
    return info.frames / float(info.samplerate)


def write_wav(path: Path | str, data: np.ndarray, sr: int = SAMPLE_RATE, subtype: str = "FLOAT") -> None:
    """data: (frames, channels) or (frames,)."""
    sf.write(str(path), data, sr, subtype=subtype, format="WAV")


def write_flac24(path: Path | str, data: np.ndarray, sr: int = SAMPLE_RATE) -> None:
    """data: (frames, channels) or (frames,)."""
    sf.write(str(path), data, sr, subtype="PCM_24", format="FLAC")


class Throttle:
    """Helper: returns True at most once every `interval` seconds."""

    def __init__(self, interval: float) -> None:
        self.interval = interval
        self._last = 0.0

    def ready(self) -> bool:
        now = time.monotonic()
        if now - self._last >= self.interval:
            self._last = now
            return True
        return False
