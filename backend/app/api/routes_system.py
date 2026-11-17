"""Health, tags and settings endpoints."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select

from .. import config
from ..config import get_paths
from ..db import get_setting, set_setting, song_tags, tags
from ..errors import AppError
from ..stems import MODEL_FOR_MODE, STEM_MODES
from .common import engine, log

router = APIRouter()

# ---------------------------------------------------------------- health

_cache: dict[str, Any] = {}
_cache_lock = threading.Lock()


def detect_device() -> str:
    """mps/cpu, computed once (importing torch is slow)."""
    with _cache_lock:
        if "device" not in _cache:
            try:
                import torch

                _cache["device"] = "mps" if torch.backends.mps.is_available() else "cpu"
            except Exception:  # noqa: BLE001
                log.exception("torch device detection failed")
                _cache["device"] = "cpu"
        return _cache["device"]


def ffmpeg_version() -> str | None:
    with _cache_lock:
        if "ffmpeg" not in _cache:
            version = None
            exe = shutil.which("ffmpeg") or ("/opt/homebrew/bin/ffmpeg" if Path("/opt/homebrew/bin/ffmpeg").exists() else None)
            if exe:
                try:
                    out = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=10).stdout
                    m = re.match(r"ffmpeg version (\S+)", out)
                    version = m.group(1) if m else None
                except (OSError, subprocess.SubprocessError):
                    version = None
            _cache["ffmpeg"] = version
        return _cache["ffmpeg"]


def ytdlp_version() -> str | None:
    try:
        from yt_dlp.version import __version__

        return __version__
    except Exception:  # noqa: BLE001
        return None


def _hf_repo_dir(models_dir: Path, model: str) -> Path:
    from_name = "HTDemucs" if model == "htdemucs" else "HTDemucs-" + model[len("htdemucs_"):]
    return models_dir / "hf" / "hub" / f"models--adefossez--{from_name}"


def _bag_signatures(yaml_path: Path) -> list[str]:
    try:
        import yaml

        bag = yaml.safe_load(yaml_path.read_text())
        models = bag.get("models") if isinstance(bag, dict) else None
        return [str(m) for m in models] if isinstance(models, list) else []
    except Exception:  # noqa: BLE001
        return re.findall(r"[0-9a-f]{8}", yaml_path.read_text().split("weights")[0])


def demucs_model_cached(models_dir: Path, model: str) -> bool:
    """demucs 4.1.0 loads `adefossez/HTDemucs-<x>` from the HF hub: `<model>.yaml` lists the
    safetensors signatures of the bag; all of them must be in some snapshot."""
    snapshots = _hf_repo_dir(models_dir, model) / "snapshots"
    if not snapshots.is_dir():
        return False
    for snap in snapshots.iterdir():
        yaml_path = snap / f"{model}.yaml"
        if not yaml_path.is_file():
            continue
        sigs = _bag_signatures(yaml_path)
        if sigs and all((snap / f"{sig}.safetensors").is_file() for sig in sigs):
            return True
    return False


def beat_this_cached(models_dir: Path) -> bool:
    return (models_dir / "torch" / "hub" / "checkpoints" / "beat_this-final0.ckpt").is_file()


def models_cached() -> bool:
    models_dir = get_paths().models
    needed = sorted(set(MODEL_FOR_MODE.values()))
    return all(demucs_model_cached(models_dir, m) for m in needed) and beat_this_cached(models_dir)


@router.get("/health")
def health():
    return {
        "ok": True,
        "device": detect_device(),
        "ffmpeg": ffmpeg_version(),
        "yt_dlp": ytdlp_version(),
        "data_dir": str(get_paths().root),
        "models_cached": models_cached(),
    }


# ---------------------------------------------------------------- tags


@router.get("/tags")
def list_tags():
    with engine().connect() as conn:
        rows = conn.execute(
            select(tags.c.name, func.count(song_tags.c.song_id))
            .select_from(tags.outerjoin(song_tags, song_tags.c.tag_id == tags.c.id))
            .group_by(tags.c.id)
        ).all()
    items = [{"name": name, "count": count} for name, count in rows if count > 0]
    items.sort(key=lambda t: t["name"].casefold())
    return {"tags": items}


# ---------------------------------------------------------------- settings


def configured_data_dir() -> Path:
    if config.data_dir_locked():
        return config.resolve_data_dir()
    raw = config.read_config_file().get("data_dir")
    if raw:
        return Path(os.path.expanduser(raw)).resolve()
    return config.DEFAULT_DATA_DIR


def settings_dict() -> dict:
    with engine().connect() as conn:
        values = {k: get_setting(conn, k) for k in ("language", "default_stem_mode", "metronome_volume")}
    configured = configured_data_dir()
    running = get_paths().root
    return {
        **values,
        "data_dir": str(configured),
        "data_dir_locked": config.data_dir_locked(),
        "restart_required": Path(os.path.realpath(configured)) != Path(os.path.realpath(running)),
    }


class SettingsBody(BaseModel):
    language: Any = None
    default_stem_mode: Any = None
    metronome_volume: Any = None
    data_dir: Any = None


def validate_data_dir(value: Any) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise AppError("VALIDATION_ERROR", "data_dir must be a non-empty string", field="data_dir")
    raw = value.strip()
    if not (raw.startswith("/") or raw.startswith("~")):
        raise AppError("VALIDATION_ERROR", "data_dir must be absolute", field="data_dir")
    path = Path(os.path.expanduser(raw))
    if not path.is_absolute():
        raise AppError("VALIDATION_ERROR", "data_dir must be absolute", field="data_dir")
    path = Path(os.path.normpath(path))
    if path.exists():
        if not path.is_dir() or not os.access(path, os.W_OK | os.X_OK):
            raise AppError("VALIDATION_ERROR", "data_dir is not a writable directory", field="data_dir")
    else:
        parent = path.parent
        if not parent.is_dir() or not os.access(parent, os.W_OK | os.X_OK):
            raise AppError("VALIDATION_ERROR", "parent of data_dir is not writable", field="data_dir")
    return path


@router.get("/settings")
def get_settings():
    return settings_dict()


@router.put("/settings")
def put_settings(body: SettingsBody):
    fields = body.model_fields_set
    updates: dict[str, Any] = {}
    if "language" in fields:
        if body.language not in (None, "en", "pt-BR"):
            raise AppError("VALIDATION_ERROR", "language must be en, pt-BR or null", field="language")
        updates["language"] = body.language
    if "default_stem_mode" in fields:
        v = body.default_stem_mode
        if isinstance(v, bool) or v not in STEM_MODES:
            raise AppError("VALIDATION_ERROR", "default_stem_mode must be 2, 4 or 6", field="default_stem_mode")
        updates["default_stem_mode"] = int(v)
    if "metronome_volume" in fields:
        v = body.metronome_volume
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 100 or int(v) != v:
            raise AppError("VALIDATION_ERROR", "metronome_volume must be an integer 0-100", field="metronome_volume")
        updates["metronome_volume"] = int(v)

    new_dir: Path | None = None
    if "data_dir" in fields:
        current = configured_data_dir()
        if config.data_dir_locked():
            same = isinstance(body.data_dir, str) and Path(os.path.expanduser(body.data_dir.strip())) == current
            if not same:
                raise AppError("VALIDATION_ERROR", "data_dir is locked by MUSIC_TRACKS_HOME", field="data_dir")
        else:
            candidate = validate_data_dir(body.data_dir)
            if candidate != current:
                new_dir = candidate

    if new_dir is not None:
        try:
            new_dir.mkdir(exist_ok=True)
        except OSError as exc:
            raise AppError("VALIDATION_ERROR", f"cannot create data_dir: {exc}", field="data_dir") from None
        cfg = config.read_config_file()
        cfg["data_dir"] = str(new_dir)
        config.write_config_file(cfg)
        log.info("data_dir set to %s (restart required)", new_dir)

    if updates:
        with engine().begin() as conn:
            for k, v in updates.items():
                set_setting(conn, k, v)
    return settings_dict()
