"""Torch device selection shared by the worker (separation) and the API (health)."""
from __future__ import annotations


def best_torch_device() -> str:
    """'cuda' (NVIDIA GPU) -> 'mps' (Apple Silicon) -> 'cpu'. Imports torch (slow)."""
    import torch

    if torch.cuda.is_available():
        return "cuda"
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        return "mps"
    return "cpu"


def empty_device_cache(device: str) -> None:
    """Releases cached allocator memory on the accelerator (best effort)."""
    try:
        import torch

        if device == "cuda" and torch.cuda.is_available():
            torch.cuda.empty_cache()
        elif device == "mps" and torch.backends.mps.is_available():
            torch.mps.empty_cache()
    except Exception:  # noqa: BLE001
        pass
