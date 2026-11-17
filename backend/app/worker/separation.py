"""Stem separation with demucs (spec §7.3).

`SeparatorBackend` is the low-level engine (real: demucs; tests: a fake). Device choice,
the MPS->CPU retry, error classification, stem combination, rescaling and saving live in
`separate_stems`, so they are exercised with the fake too.
"""
from __future__ import annotations

import gc
import logging
import time
from pathlib import Path
from typing import Callable, Protocol

import numpy as np

from ..errors import AppError, JobCanceled
from ..stems import MODEL_FOR_MODE, stems_for

log = logging.getLogger("worker.separation")

ChunkCallback = Callable[[dict], None]

PEAK_LIMIT = 0.99
PEAK_TARGET = 0.98


class SeparatorBackend(Protocol):
    def default_device(self) -> str:
        """'mps' or 'cpu'."""
        ...

    def is_model_cached(self, model: str) -> bool:
        ...

    def load(self, model: str) -> None:
        """Loads (downloading if needed) the model; at most one model stays loaded."""
        ...

    def separate(self, model: str, wav: np.ndarray, device: str, callback: ChunkCallback) -> dict[str, np.ndarray]:
        """wav: float32 (channels, frames) at 44.1 kHz. Returns {source: (channels, frames)}.

        `callback` receives demucs-style dicts (state, model_idx_in_bag, segment_offset,
        audio_length, models) and may raise to abort.
        """
        ...


def _hf_repo_id(model: str) -> str:
    from demucs.hf import DEFAULT_NAMESPACE, hf_repo_name

    return f"{DEFAULT_NAMESPACE}/{hf_repo_name(model)}"


class DemucsBackend:
    """Real separator: demucs.api.Separator cached per model (one at a time)."""

    def __init__(self) -> None:
        self._model_name: str | None = None
        self._separator = None

    def default_device(self) -> str:
        import torch

        return "mps" if torch.backends.mps.is_available() else "cpu"

    def is_model_cached(self, model: str) -> bool:
        try:
            import yaml
            from huggingface_hub import try_to_load_from_cache

            repo = _hf_repo_id(model)
            bag_path = try_to_load_from_cache(repo, f"{model}.yaml")
            if not isinstance(bag_path, str):
                return False
            with open(bag_path) as fh:
                bag = yaml.safe_load(fh)
            for sig in bag.get("models", []):
                if not isinstance(try_to_load_from_cache(repo, f"{sig}.safetensors"), str):
                    return False
            return True
        except Exception:  # noqa: BLE001
            return False

    def load(self, model: str) -> None:
        if self._model_name == model and self._separator is not None:
            return
        self.unload()
        from demucs.api import Separator

        t0 = time.monotonic()
        try:
            self._separator = Separator(
                model=model, device=self.default_device(), shifts=1, overlap=0.25,
                split=True, progress=False,
            )
        except Exception as exc:  # noqa: BLE001
            raise AppError(
                "SEPARATION_FAILED",
                f"could not load model {model} (first use needs internet to download it): "
                f"{type(exc).__name__}: {exc}",
            ) from exc
        self._model_name = model
        log.info("loaded model %s in %.1fs", model, time.monotonic() - t0)

    def unload(self) -> None:
        if self._separator is None:
            return
        log.info("unloading model %s", self._model_name)
        self._separator = None
        self._model_name = None
        gc.collect()
        _empty_mps_cache()

    def separate(self, model: str, wav: np.ndarray, device: str, callback: ChunkCallback) -> dict[str, np.ndarray]:
        import torch

        self.load(model)
        sep = self._separator
        sep.update_parameter(device=device, callback=callback)
        tensor = torch.from_numpy(np.ascontiguousarray(wav, dtype=np.float32))
        try:
            with torch.inference_mode():
                _, out = sep.separate_tensor(tensor, 44100)
            return {name: t.detach().cpu().numpy() for name, t in out.items()}
        finally:
            del tensor
            if device == "mps":
                _empty_mps_cache()


def _empty_mps_cache() -> None:
    try:
        import torch

        if torch.backends.mps.is_available():
            torch.mps.empty_cache()
    except Exception:  # noqa: BLE001
        pass


def is_memory_error(exc: BaseException) -> bool:
    if isinstance(exc, MemoryError):
        return True
    try:
        import torch

        oom = getattr(torch, "OutOfMemoryError", None)
        if oom is not None and isinstance(exc, oom):
            return True
    except Exception:  # noqa: BLE001
        pass
    msg = str(exc).lower()
    return "out of memory" in msg or "failed to allocate" in msg or "mps backend out of memory" in msg


def _is_mps_retryable(exc: BaseException) -> bool:
    return is_memory_error(exc) or isinstance(exc, RuntimeError)


def _passthrough(exc: BaseException) -> bool:
    """Exceptions that must not be translated into separation errors."""
    from .context import StopRequested

    if isinstance(exc, (JobCanceled, StopRequested, AppError, KeyboardInterrupt)):
        return True
    return isinstance(exc, OSError) and getattr(exc, "errno", None) is not None


def run_separator(
    backend: SeparatorBackend,
    model: str,
    wav: np.ndarray,
    callback: ChunkCallback,
    on_retry: Callable[[], None] = lambda: None,
) -> dict[str, np.ndarray]:
    """Runs on the default device; on MPS memory/runtime errors retries once on CPU."""
    device = backend.default_device()
    try:
        return backend.separate(model, wav, device, callback)
    except BaseException as exc:  # noqa: BLE001
        if _passthrough(exc):
            raise
        if device == "mps" and _is_mps_retryable(exc):
            log.warning("separation on mps failed (%s: %s); retrying on cpu", type(exc).__name__, exc)
            gc.collect()
            _empty_mps_cache()
            on_retry()
            try:
                return backend.separate(model, wav, "cpu", callback)
            except BaseException as exc2:  # noqa: BLE001
                if _passthrough(exc2):
                    raise
                raise _classify(exc2) from exc2
        raise _classify(exc) from exc


def _classify(exc: BaseException) -> AppError:
    code = "OUT_OF_MEMORY" if is_memory_error(exc) else "SEPARATION_FAILED"
    log.error("separation failed", exc_info=exc)
    return AppError(code, f"{type(exc).__name__}: {exc}"[:1000])


def combine_stems(sources: dict[str, np.ndarray], stem_mode: int) -> dict[str, np.ndarray]:
    """Maps model sources to the stems of the mode (2-stem: instrumental = sum of non-vocals)."""
    if stem_mode == 2:
        rest = [v for k, v in sources.items() if k != "vocals"]
        instrumental = np.sum(rest, axis=0) if rest else np.zeros_like(sources["vocals"])
        return {"vocals": sources["vocals"], "instrumental": instrumental}
    missing = [s for s in stems_for(stem_mode) if s not in sources]
    if missing:
        raise AppError("SEPARATION_FAILED", f"model did not produce stems {missing}")
    return {s: sources[s] for s in stems_for(stem_mode)}


def rescale_common(stems: dict[str, np.ndarray]) -> float:
    """In place: if the common peak exceeds 0.99, scale every stem by 0.98/peak. Returns the factor."""
    peak = max((float(np.max(np.abs(v))) if v.size else 0.0) for v in stems.values())
    if peak > PEAK_LIMIT:
        factor = PEAK_TARGET / peak
        for k in stems:
            stems[k] = stems[k] * factor
        return factor
    return 1.0


def save_stem(wav: np.ndarray, path: Path) -> None:
    """wav: (channels, frames). FLAC 24-bit, 44.1 kHz, no clipping strategy (already rescaled)."""
    import torch
    from demucs.audio import save_audio

    save_audio(
        torch.from_numpy(np.ascontiguousarray(wav, dtype=np.float32)), str(path), 44100,
        bits_per_sample=24, clip="none",
    )
    if not path.exists():
        raise OSError(f"failed to write {path}")


def model_for(stem_mode: int) -> str:
    return MODEL_FOR_MODE[stem_mode]
