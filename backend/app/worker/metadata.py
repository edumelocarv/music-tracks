"""Metadata extraction: embedded tags (mutagen), yt-dlp info, cover conversion (spec §7.2)."""
from __future__ import annotations

import base64
import io
import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("worker.metadata")

COVER_MAX = 600


@dataclass
class ExtractedMetadata:
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    cover: bytes | None = None  # raw image bytes (any Pillow-readable format)


def _clean(v) -> str | None:  # noqa: ANN001
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        v = v[0] if v else None
        if v is None:
            return None
    s = str(v).strip()
    return s[:200] or None


def read_tags(path: Path) -> ExtractedMetadata:
    """Title/artist/album and embedded cover. Never raises (returns empty metadata on errors)."""
    meta = ExtractedMetadata()
    try:
        import mutagen

        easy = mutagen.File(str(path), easy=True)
        if easy is not None and easy.tags is not None:
            meta.title = _clean(easy.tags.get("title"))
            meta.artist = _clean(easy.tags.get("artist"))
            meta.album = _clean(easy.tags.get("album"))
        meta.cover = _embedded_cover(path)
    except Exception as exc:  # noqa: BLE001
        log.warning("could not read tags of %s: %s", path, exc)
    return meta


def _embedded_cover(path: Path) -> bytes | None:
    import mutagen

    f = mutagen.File(str(path))
    if f is None:
        return None
    pictures = getattr(f, "pictures", None)  # FLAC
    if pictures:
        return pictures[0].data
    tags = f.tags
    if tags is None:
        return None
    if hasattr(tags, "getall"):  # ID3
        apic = tags.getall("APIC")
        if apic:
            front = [a for a in apic if getattr(a, "type", None) == 3]
            return (front or apic)[0].data
    try:
        covr = tags.get("covr")  # MP4
        if covr:
            return bytes(covr[0])
    except Exception:  # noqa: BLE001
        pass
    try:
        blocks = tags.get("metadata_block_picture")  # Ogg/Opus
        if blocks:
            from mutagen.flac import Picture

            return Picture(base64.b64decode(blocks[0])).data
    except Exception:  # noqa: BLE001
        pass
    return None


def info_metadata(info: dict) -> ExtractedMetadata:
    """yt-dlp info -> metadata (artist -> creator -> uploader)."""

    def first(*keys: str) -> str | None:
        for k in keys:
            v = _clean(info.get(k))
            if v:
                return v
        return None

    return ExtractedMetadata(
        title=first("title"),
        artist=first("artist", "artists", "creator", "creators", "uploader"),
        album=first("album"),
    )


def save_cover(data: bytes | Path, dest: Path) -> None:
    """Converts any Pillow-readable image to RGB JPEG of at most 600x600 at `dest`."""
    from PIL import Image

    src = io.BytesIO(data) if isinstance(data, (bytes, bytearray)) else str(data)
    with Image.open(src) as im:
        im = im.convert("RGB")
        im.thumbnail((COVER_MAX, COVER_MAX), Image.LANCZOS)
        im.save(str(dest), "JPEG", quality=90)
