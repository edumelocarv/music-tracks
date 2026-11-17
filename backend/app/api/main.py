"""FastAPI application: `uvicorn app.api.main:app --host 127.0.0.1 --port $MUSIC_TRACKS_PORT`.

Normally started by `python -m app.launcher` (binds MUSIC_TRACKS_HOST, default 127.0.0.1).
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import time
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .. import config
from ..config import get_paths
from ..db import get_engine
from ..errors import AppError
from . import routes_export, routes_ingest, routes_jobs, routes_markers, routes_songs, routes_system
from .common import log

DIST_DIR = Path(__file__).resolve().parents[3] / "frontend" / "dist"
MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
DEV_ORIGINS = {"http://localhost:5173", "http://127.0.0.1:5173"}


# ---------------------------------------------------------------- logging / startup


def setup_logging(logs_dir: Path) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    for h in list(log.handlers):
        if getattr(h, "_music_tracks", False):
            log.removeHandler(h)
            h.close()
    handler = RotatingFileHandler(logs_dir / "api.log", maxBytes=5 * 1024 * 1024, backupCount=4, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler._music_tracks = True  # type: ignore[attr-defined]
    log.addHandler(handler)
    log.setLevel(logging.INFO)


def startup() -> None:
    paths = get_paths()
    paths.ensure()
    config.configure_model_env(paths)
    setup_logging(paths.logs)
    api_tmp = paths.tmp / "api"
    shutil.rmtree(api_tmp, ignore_errors=True)
    api_tmp.mkdir(parents=True, exist_ok=True)
    get_engine()
    log.info("api started, data_dir=%s", paths.root)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    startup()
    yield
    log.info("api stopped")


# ---------------------------------------------------------------- security middleware (§12)


def _error_body(code: str, detail: str) -> bytes:
    return json.dumps({"error": {"code": code, "detail": detail}}).encode()


class SecurityMiddleware:
    """Rejects foreign Host headers (DNS rebinding) and cross-origin mutating requests."""

    def __init__(self, app) -> None:  # noqa: ANN001
        self.app = app

    async def __call__(self, scope, receive, send) -> None:  # noqa: ANN001
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        host = headers.get("host", "").strip().lower()
        ports = {os.environ.get("MUSIC_TRACKS_PORT", str(config.PORT))}
        server = scope.get("server")
        if server and server[1]:
            ports.add(str(server[1]))
        allowed_hosts = {f"{h}:{p}" for h in ("127.0.0.1", "localhost") for p in ports}
        allowed_hosts |= config.extra_allowed_hosts()
        reason = None
        if host not in allowed_hosts:
            reason = "host not allowed"
        elif scope["method"] in MUTATING_METHODS and "origin" in headers:
            origin = headers["origin"].strip().lower().rstrip("/")
            allowed = {f"http://{host}"}
            if os.environ.get("MUSIC_TRACKS_DEV") == "1":
                allowed |= DEV_ORIGINS
            if origin not in allowed:
                reason = "origin not allowed"
        if reason:
            log.warning("403 %s %s: %s (host=%r origin=%r)", scope["method"], scope.get("path"), reason,
                        headers.get("host"), headers.get("origin"))
            body = _error_body("FORBIDDEN", reason)
            await send({"type": "http.response.start", "status": 403,
                        "headers": [(b"content-type", b"application/json"),
                                    (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)


# ---------------------------------------------------------------- app


app = FastAPI(title="Music Tracks", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SecurityMiddleware)


@app.middleware("http")
async def access_log(request: Request, call_next):
    t0 = time.monotonic()
    response = await call_next(request)
    if request.method in MUTATING_METHODS or response.status_code >= 400:
        log.info("%s %s -> %d (%.0f ms)", request.method, request.url.path, response.status_code,
                 (time.monotonic() - t0) * 1000)
    return response


@app.exception_handler(AppError)
async def app_error_handler(_request: Request, exc: AppError):
    if exc.status >= 500:
        log.error("app error %s: %s", exc.code, exc.detail)
    return JSONResponse(exc.payload(), status_code=exc.status)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_request: Request, exc: RequestValidationError):
    parts = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err.get("loc", ()) if x != "body")
        parts.append(f"{loc}: {err.get('msg')}" if loc else str(err.get("msg")))
    return JSONResponse(
        {"error": {"code": "VALIDATION_ERROR", "detail": "; ".join(parts)[:1000]}}, status_code=422
    )


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(_request: Request, exc: StarletteHTTPException):
    code = "NOT_FOUND" if exc.status_code == 404 else ("INTERNAL_ERROR" if exc.status_code >= 500 else "VALIDATION_ERROR")
    return JSONResponse({"error": {"code": code, "detail": str(exc.detail)}}, status_code=exc.status_code)


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception):
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        {"error": {"code": "INTERNAL_ERROR", "detail": f"{type(exc).__name__}: {exc}"[:500]}}, status_code=500
    )


for module in (routes_system, routes_ingest, routes_songs, routes_markers, routes_jobs, routes_export):
    app.include_router(module.router, prefix="/api")


@app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
async def api_not_found(rest: str):
    raise AppError("NOT_FOUND", f"no route /api/{rest}")


@app.get("/{full_path:path}", include_in_schema=False)
async def spa(full_path: str):
    index = DIST_DIR / "index.html"
    if not index.is_file():
        return PlainTextResponse("Music Tracks API is running. Frontend not built (run ./start.sh).")
    if full_path:
        candidate = (DIST_DIR / full_path).resolve()
        if candidate.is_file() and candidate.is_relative_to(DIST_DIR.resolve()):
            return FileResponse(candidate)
    return FileResponse(index, headers={"Cache-Control": "no-cache"})
