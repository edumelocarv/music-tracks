"""Exports (spec §10): single stem, ZIP of stems, custom mix. WAV/FLAC 24-bit, MP3 320k CBR."""
from __future__ import annotations

import math
import shutil
import subprocess
import unicodedata
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

import numpy as np
import soundfile as sf

from .audio import find_executable
from .config import SAMPLE_RATE, get_paths
from .db import new_id
from .errors import AppError
from .stems import STEM_MODES

FORMATS = ("wav", "flac", "mp3")
MEDIA_TYPES = {"wav": "audio/wav", "flac": "audio/flac", "mp3": "audio/mpeg", "zip": "application/zip"}
_BAD_CHARS = set('/\\:*?"<>|')
MIN_MIX_S = 0.5


# ---------------------------------------------------------------- names


def sanitize(name: str) -> str:
    out = "".join("_" if (c in _BAD_CHARS or ord(c) < 32 or ord(c) == 127) else c for c in name)
    return out.strip()


def export_filename(artist: str | None, title: str, suffix: str, ext: str) -> str:
    base = f"{artist} - {title}" if artist else title
    name = sanitize(f"{base} [{suffix}]")
    if name.startswith("."):
        name = "_" + name[1:]
    return f"{name}.{ext}"


def content_disposition(filename: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode("ascii")
    ascii_name = "".join(c if 32 <= ord(c) < 127 and c not in '"\\' else "_" for c in ascii_name).strip()
    if not ascii_name or ascii_name.startswith("."):
        ascii_name = "export" + (Path(filename).suffix or "")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename, safe='')}"


def check_format(fmt: str | None) -> str:
    fmt = (fmt or "wav").lower()
    if fmt not in FORMATS:
        raise AppError("VALIDATION_ERROR", f"format must be one of {', '.join(FORMATS)}", field="format")
    return fmt


# ---------------------------------------------------------------- audio io


def tmp_dir() -> Path:
    d = get_paths().tmp / "api"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ffmpeg_bin() -> str:
    exe = find_executable("ffmpeg")
    if exe:
        return exe
    raise AppError("INTERNAL_ERROR", "ffmpeg not found")


def _stereo(data: np.ndarray) -> np.ndarray:
    if data.ndim == 1:
        data = data[:, None]
    if data.shape[1] == 1:
        data = np.repeat(data, 2, axis=1)
    elif data.shape[1] > 2:
        data = data[:, :2]
    return np.ascontiguousarray(data, dtype=np.float32)


def read_stem(path: Path, start_frame: int = 0, stop_frame: int | None = None) -> np.ndarray:
    if not path.is_file():
        raise AppError("NOT_FOUND", f"stem file {path.name} missing")
    data, sr = sf.read(str(path), start=start_frame, stop=stop_frame, dtype="float32", always_2d=True)
    if sr != SAMPLE_RATE:
        raise AppError("INTERNAL_ERROR", f"unexpected sample rate {sr} in {path.name}")
    return _stereo(data)


def encode(data: np.ndarray, dest: Path, fmt: str) -> Path:
    """Write stereo float data (frames, 2) at 44.1 kHz in the requested format."""
    data = np.clip(_stereo(data), -1.0, 1.0)
    if fmt == "wav":
        sf.write(str(dest), data, SAMPLE_RATE, subtype="PCM_24", format="WAV")
    elif fmt == "flac":
        sf.write(str(dest), data, SAMPLE_RATE, subtype="PCM_24", format="FLAC")
    elif fmt == "mp3":
        src = dest.with_name(dest.name + ".src.wav")
        try:
            sf.write(str(src), data, SAMPLE_RATE, subtype="FLOAT", format="WAV")
            proc = subprocess.run(
                [ffmpeg_bin(), "-nostdin", "-hide_banner", "-v", "error", "-y", "-i", str(src),
                 "-ar", str(SAMPLE_RATE), "-ac", "2", "-c:a", "libmp3lame", "-b:a", "320k", str(dest)],
                capture_output=True, text=True, timeout=600,
            )
            if proc.returncode != 0:
                raise AppError("INTERNAL_ERROR", f"ffmpeg failed: {proc.stderr.strip()[:300]}")
        finally:
            src.unlink(missing_ok=True)
    else:  # pragma: no cover - validated earlier
        raise AppError("VALIDATION_ERROR", "invalid format")
    return dest


def _stems_dir(song_id: str) -> Path:
    return get_paths().song_dir(song_id) / "stems"


def _new_tmp(ext: str) -> Path:
    return tmp_dir() / f"export-{new_id()}.{ext}"


# ---------------------------------------------------------------- exports


def export_stem(song: Any, stem: str, fmt: str) -> Path:
    data = read_stem(_stems_dir(song.id) / f"{stem}.flac")
    dest = _new_tmp(fmt)
    try:
        return encode(data, dest, fmt)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise


def export_zip(song: Any, fmt: str) -> Path:
    stems = STEM_MODES[song.stem_mode]
    work = tmp_dir() / f"zip-{new_id()}"
    work.mkdir()
    dest = _new_tmp("zip")
    try:
        with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
            for stem in stems:
                part = encode(read_stem(_stems_dir(song.id) / f"{stem}.flac"), work / f"{stem}.{fmt}", fmt)
                zf.write(part, arcname=f"{stem}.{fmt}")
                part.unlink(missing_ok=True)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return dest


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise AppError("VALIDATION_ERROR", f"{name} must be a number", field=name)
    return float(value)


def validate_mix(song: Any, body: dict) -> dict:
    stems = STEM_MODES[song.stem_mode]
    gains_in = body.get("gains")
    if not isinstance(gains_in, dict):
        raise AppError("VALIDATION_ERROR", "gains must be an object", field="gains")
    gains = {s: 0.0 for s in stems}
    for stem, g in gains_in.items():
        if stem not in stems:
            raise AppError("VALIDATION_ERROR", f"stem {stem!r} not in current mode", field="gains")
        g = _number(g, "gains")
        if not 0.0 <= g <= 1.0:
            raise AppError("VALIDATION_ERROR", "gains must be within 0-1", field="gains")
        gains[stem] = g
    if all(g == 0 for g in gains.values()):
        raise AppError("VALIDATION_ERROR", "all gains are zero", field="gains")

    speed = 1.0 if body.get("speed") is None else _number(body.get("speed"), "speed")
    if not 0.5 <= speed <= 1.5:
        raise AppError("VALIDATION_ERROR", "speed must be within 0.5-1.5", field="speed")
    semitones = 0.0 if body.get("semitones") is None else _number(body.get("semitones"), "semitones")
    if not -12 <= semitones <= 12:
        raise AppError("VALIDATION_ERROR", "semitones must be within -12..12", field="semitones")

    duration = float(song.duration_s or 0.0)
    start = 0.0 if body.get("start_s") is None else _number(body.get("start_s"), "start_s")
    end = duration if body.get("end_s") is None else _number(body.get("end_s"), "end_s")
    if not (0 <= start < end <= duration) or end - start < MIN_MIX_S:
        raise AppError("VALIDATION_ERROR", "invalid start_s/end_s", field="start_s")
    return {
        "gains": gains,
        "speed": speed,
        "semitones": semitones,
        "start_s": start,
        "end_s": end,
        "format": check_format(body.get("format")),
    }


def time_stretch(data: np.ndarray, speed: float, semitones: float) -> np.ndarray:
    """Signalsmith Stretch via python-stretch. `setTimeFactor(speed)` makes the output
    len(input)/speed long; input/output latency is compensated inside `process`."""
    from python_stretch.Signalsmith import Stretch

    st = Stretch()
    st.preset(2, float(SAMPLE_RATE))
    st.setTimeFactor(float(speed))
    if semitones:
        st.setTransposeSemitones(float(semitones))
    out = st.process(np.ascontiguousarray(data.T, dtype=np.float32))
    return np.ascontiguousarray(out.T)


def render_mix(song: Any, params: dict) -> np.ndarray:
    start_f = int(round(params["start_s"] * SAMPLE_RATE))
    stop_f = int(round(params["end_s"] * SAMPLE_RATE))
    mix: np.ndarray | None = None
    for stem, gain in params["gains"].items():
        if gain == 0:
            continue
        data = read_stem(_stems_dir(song.id) / f"{stem}.flac", start_f, stop_f)
        data *= np.float32(gain)
        if mix is None:
            mix = data
        else:
            n = max(len(mix), len(data))
            if len(mix) < n:
                mix = np.pad(mix, ((0, n - len(mix)), (0, 0)))
            if len(data) < n:
                data = np.pad(data, ((0, n - len(data)), (0, 0)))
            mix += data
    assert mix is not None
    if params["speed"] != 1.0 or params["semitones"] != 0:
        mix = time_stretch(mix, params["speed"], params["semitones"])
    peak = float(np.max(np.abs(mix))) if mix.size else 0.0
    if peak > 1.0:
        mix *= np.float32(0.98 / peak)
    return mix


def export_mix(song: Any, params: dict) -> Path:
    mix = render_mix(song, params)
    dest = _new_tmp(params["format"])
    try:
        return encode(mix, dest, params["format"])
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
