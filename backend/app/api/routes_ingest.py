"""Adding songs: multipart upload and URL (spec §8.3)."""
from __future__ import annotations

import asyncio
import hashlib
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from python_multipart.multipart import MultipartParser, parse_options_header

from .. import services
from ..config import ACCEPTED_EXTS, MAX_DURATION_S, MAX_FILE_BYTES, get_paths
from ..db import get_setting, new_id
from ..errors import AppError
from ..stems import STEM_MODES
from .common import engine, log, song_dict

router = APIRouter()

# Overridable by tests.
URL_TIMEOUT_S = 30.0
MAX_FIELD_BYTES = 4096
URL_PLACEHOLDER_EXT = "pending"  # the worker sets the real extension after downloading


def api_tmp_dir() -> Path:
    d = get_paths().tmp / "api"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _default_stem_mode() -> int:
    with engine().connect() as conn:
        mode = get_setting(conn, "default_stem_mode")
    return mode if mode in STEM_MODES else 4


def _parse_stem_mode(value: Any) -> int:
    if value is None or value == "":
        return _default_stem_mode()
    try:
        mode = int(value)
    except (TypeError, ValueError):
        raise AppError("VALIDATION_ERROR", "stem_mode must be 2, 4 or 6", field="stem_mode") from None
    if isinstance(value, bool) or mode not in STEM_MODES or str(value).strip() not in {"2", "4", "6"}:
        raise AppError("VALIDATION_ERROR", "stem_mode must be 2, 4 or 6", field="stem_mode")
    return mode


def _response(song_id: str, job: dict) -> dict:
    with engine().connect() as conn:
        song = song_dict(conn, song_id)
    return {"song": song, "job": song["active_job"] or song["last_job"]}


# ---------------------------------------------------------------- upload


class _UploadSink:
    """Streaming multipart receiver: the file goes straight to tmp/api with a running sha256."""

    def __init__(self, tmp_dir: Path, max_bytes: int) -> None:
        self.tmp_dir = tmp_dir
        self.max_bytes = max_bytes
        self.fields: dict[str, str] = {}
        self.filename: str | None = None
        self.ext: str | None = None
        self.path: Path | None = None
        self.size = 0
        self.sha = hashlib.sha256()
        self._fh = None
        self._reset_part()

    def _reset_part(self) -> None:
        self._headers: dict[str, bytes] = {}
        self._hfield = b""
        self._hvalue = b""
        self._part_name: str | None = None
        self._part_is_file = False
        self._field_buf = bytearray()

    # callbacks
    def on_part_begin(self) -> None:
        self._reset_part()

    def on_header_field(self, data: bytes, start: int, end: int) -> None:
        self._hfield += data[start:end]

    def on_header_value(self, data: bytes, start: int, end: int) -> None:
        self._hvalue += data[start:end]

    def on_header_end(self) -> None:
        self._headers[self._hfield.decode("latin-1").lower()] = self._hvalue
        self._hfield = b""
        self._hvalue = b""

    def on_headers_finished(self) -> None:
        _, params = parse_options_header(self._headers.get("content-disposition", b""))
        name = params.get(b"name", b"").decode("utf-8", "replace")
        self._part_name = name
        if name != "file":
            return
        if self._fh is not None or self.path is not None:
            raise AppError("VALIDATION_ERROR", "only one file per request", field="file")
        raw = params.get(b"filename")
        filename = raw.decode("utf-8", "replace") if raw is not None else ""
        filename = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in ACCEPTED_EXTS:
            raise AppError("UNSUPPORTED_FORMAT", f"extension {ext!r} not accepted")
        self.filename = filename
        self.ext = ext
        self._part_is_file = True
        self.path = self.tmp_dir / f"upload-{new_id()}.{ext}"
        self._fh = open(self.path, "wb")  # noqa: SIM115

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        chunk = data[start:end]
        if self._part_is_file:
            self.size += len(chunk)
            if self.size > self.max_bytes:
                raise AppError("FILE_TOO_LARGE", f"file larger than {self.max_bytes} bytes")
            self.sha.update(chunk)
            self._fh.write(chunk)
        else:
            self._field_buf += chunk
            if len(self._field_buf) > MAX_FIELD_BYTES:
                raise AppError("VALIDATION_ERROR", "form field too large")

    def on_part_end(self) -> None:
        if self._part_is_file:
            self._fh.close()
            self._fh = None
        elif self._part_name:
            self.fields[self._part_name] = self._field_buf.decode("utf-8", "replace")

    def callbacks(self) -> dict:
        return {
            name: getattr(self, name)
            for name in (
                "on_part_begin", "on_header_field", "on_header_value", "on_header_end",
                "on_headers_finished", "on_part_data", "on_part_end",
            )
        }

    def discard(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
        if self.path is not None:
            self.path.unlink(missing_ok=True)


def _finish_upload(sink: _UploadSink, stem_mode_raw: str | None) -> tuple[str, dict]:
    stem_mode = _parse_stem_mode(stem_mode_raw)
    source_key = f"sha256:{sink.sha.hexdigest()}"
    existing = services.find_by_source_key(engine(), source_key)
    if existing:
        raise AppError("DUPLICATE", "song already exists", existing_song_id=existing)

    song_id = new_id()
    dest_dir = get_paths().song_dir(song_id)
    try:
        dest_dir.mkdir(parents=True)
        shutil.move(str(sink.path), dest_dir / f"original.{sink.ext}")
        title = Path(sink.filename or "").stem.strip() or "Untitled"
        _, job = services.create_song_with_job(
            engine(),
            song_id=song_id,
            title=title,
            source_type="file",
            original_ext=sink.ext,
            stem_mode=stem_mode,
            source_key=source_key,
            original_filename=sink.filename,
        )
    except BaseException:
        services.cleanup_song_dir(song_id)
        raise
    log.info("upload %r (%d bytes) -> song %s job %s", sink.filename, sink.size, song_id, job["id"])
    return song_id, job


@router.post("/songs/upload", status_code=201)
async def upload_song(request: Request):
    ctype, params = parse_options_header(request.headers.get("content-type", ""))
    boundary = params.get(b"boundary")
    if ctype != b"multipart/form-data" or not boundary:
        raise AppError("VALIDATION_ERROR", "expected multipart/form-data")
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_FILE_BYTES + 1024 * 1024:
        raise AppError("FILE_TOO_LARGE", f"file larger than {MAX_FILE_BYTES} bytes")

    sink = _UploadSink(api_tmp_dir(), MAX_FILE_BYTES)
    parser = MultipartParser(boundary, sink.callbacks())
    try:
        async for chunk in request.stream():
            if chunk:
                parser.write(chunk)
        parser.finalize()
        if sink.path is None or sink._fh is not None:
            raise AppError("VALIDATION_ERROR", "missing file", field="file")
        song_id, job = await run_in_threadpool(_finish_upload, sink, sink.fields.get("stem_mode"))
    except BaseException:
        sink.discard()
        raise
    return await run_in_threadpool(_response, song_id, job)


# ---------------------------------------------------------------- URL


def _extract_info(url: str) -> dict | None:
    import yt_dlp

    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 15,
        "js_runtimes": {"node": {}},
        "extract_flat": "in_playlist",  # don't resolve every playlist entry
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


async def _extract(url: str) -> dict:
    try:
        info = await asyncio.wait_for(asyncio.to_thread(_extract_info, url), URL_TIMEOUT_S)
    except asyncio.TimeoutError:
        raise AppError("INVALID_URL", "timed out extracting info") from None
    except AppError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AppError("INVALID_URL", f"{type(exc).__name__}: {exc}"[:500]) from None
    if not isinstance(info, dict):
        raise AppError("INVALID_URL", "no media found")
    return info


def _is_http_url(url: str) -> bool:
    try:
        p = urlparse(url)
    except ValueError:
        return False
    return p.scheme in ("http", "https") and bool(p.netloc)


class UrlBody(BaseModel):
    url: Any = None
    stem_mode: Any = None


@router.post("/songs/url", status_code=201)
async def add_url(body: UrlBody):
    url = body.url.strip() if isinstance(body.url, str) else ""
    if not _is_http_url(url):
        raise AppError("INVALID_URL", "only http(s) URLs are accepted")
    stem_mode = await run_in_threadpool(_parse_stem_mode, body.stem_mode)

    info = await _extract(url)
    if info.get("_type") in ("playlist", "multi_video"):
        entries = [e for e in (info.get("entries") or []) if e]
        entry_url = None
        if len(entries) == 1:
            entry_url = entries[0].get("url") or entries[0].get("webpage_url")
        if not entry_url or not _is_http_url(entry_url):
            raise AppError("PLAYLIST_NOT_SUPPORTED", "playlists are not supported")
        info = await _extract(entry_url)
        if info.get("_type") in ("playlist", "multi_video"):
            raise AppError("PLAYLIST_NOT_SUPPORTED", "playlists are not supported")
    if info.get("is_live"):
        raise AppError("INVALID_URL", "live streams are not supported")
    duration = info.get("duration")
    if isinstance(duration, (int, float)) and duration > MAX_DURATION_S:
        raise AppError("TOO_LONG", f"duration {duration}s exceeds {MAX_DURATION_S}s")
    extractor = info.get("extractor_key") or info.get("ie_key") or info.get("extractor")
    media_id = info.get("id")
    if not extractor or not media_id:
        raise AppError("INVALID_URL", "could not identify media")
    source_key = f"url:{str(extractor).lower()}:{media_id}"
    title = str(info.get("title") or media_id).strip() or "Untitled"
    source_url = info.get("webpage_url") if _is_http_url(str(info.get("webpage_url") or "")) else url

    def create() -> tuple[str, dict]:
        existing = services.find_by_source_key(engine(), source_key)
        if existing:
            raise AppError("DUPLICATE", "song already exists", existing_song_id=existing)
        song_id = new_id()
        try:
            get_paths().song_dir(song_id).mkdir(parents=True)
            _, job = services.create_song_with_job(
                engine(),
                song_id=song_id,
                title=title,
                source_type="url",
                original_ext=URL_PLACEHOLDER_EXT,
                stem_mode=stem_mode,
                source_key=source_key,
                source_url=source_url,
            )
        except BaseException:
            services.cleanup_song_dir(song_id)
            raise
        log.info("url %s (%s) -> song %s job %s", source_url, source_key, song_id, job["id"])
        return song_id, job

    song_id, job = await run_in_threadpool(create)
    return await run_in_threadpool(_response, song_id, job)

