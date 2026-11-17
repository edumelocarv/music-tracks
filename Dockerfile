# syntax=docker/dockerfile:1
# Music Tracks in a container: API + worker on port 8765, data in /data.
#   docker compose up -d --build        (see docker-compose.yml)
# CPU by default; NVIDIA GPUs work on Linux x86_64 hosts with the NVIDIA Container Toolkit
# (PyPI's Linux torch wheel is a CUDA build).

ARG PYTHON_IMAGE=python:3.12-slim
ARG NODE_IMAGE=node:22-slim
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.11.26

FROM ${UV_IMAGE} AS uv

# ---------------------------------------------------------------- frontend (frontend/dist)
FROM ${NODE_IMAGE} AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------- backend (.venv)
FROM ${PYTHON_IMAGE} AS backend
COPY --from=uv /uv /uvx /bin/
# linux/arm64: python-stretch and sphn (a demucs dependency) publish no Linux aarch64
# wheels, so they are compiled from source (C++ / Rust; sphn links the system libopus,
# which the runtime image gets through ffmpeg). Not needed on amd64.
RUN if [ "$(uname -m)" = "aarch64" ]; then \
      apt-get update \
      && apt-get install -y --no-install-recommends \
           build-essential cmake pkg-config libopus-dev curl ca-certificates \
      && rm -rf /var/lib/apt/lists/* \
      && curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal; \
    fi
ENV PATH="/root/.cargo/bin:${PATH}" \
    CMAKE_POLICY_VERSION_MINIMUM=3.5 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
COPY backend/app ./app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ---------------------------------------------------------------- runtime
FROM ${PYTHON_IMAGE}
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 app \
    && mkdir /data && chown app:app /data
# node: yt-dlp solves YouTube's JS challenges with it (spec §3.1).
COPY --from=frontend /usr/local/bin/node /usr/local/bin/node
COPY --from=uv /uv /bin/uv
COPY --from=backend /app/backend /app/backend
COPY --from=frontend /src/frontend/dist /app/frontend/dist

ENV PATH="/app/backend/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    MUSIC_TRACKS_HOME=/data \
    MUSIC_TRACKS_HOST=0.0.0.0 \
    MUSIC_TRACKS_PORT=8765
USER app
WORKDIR /app/backend
VOLUME ["/data"]
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python", "-c", "import urllib.request as u; u.urlopen(u.Request('http://127.0.0.1:8765/api/health', headers={'Host': '127.0.0.1:8765'}), timeout=4)"]
CMD ["python", "-m", "app.launcher", "--no-browser"]
