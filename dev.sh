#!/usr/bin/env bash
# Development mode: worker + API (--reload) + Vite dev server on :5173 (spec §4).
set -uo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PORT="${MUSIC_TRACKS_PORT:-8765}"
export MUSIC_TRACKS_PORT="$PORT"
export MUSIC_TRACKS_DEV=1
export PATH="/opt/homebrew/bin:$PATH"

(cd "$ROOT/backend" && uv sync --quiet) || exit 1
[[ -d "$ROOT/frontend/node_modules" ]] || (cd "$ROOT/frontend" && npm ci --no-audit --no-fund) || exit 1

pids=()
cleanup() { trap - INT TERM; kill "${pids[@]}" 2>/dev/null; wait 2>/dev/null; }
trap 'cleanup; exit 0' INT TERM

(cd "$ROOT/backend" && exec uv run python -m app.worker) & pids+=($!)
(cd "$ROOT/backend" && exec uv run uvicorn app.api.main:app --host 127.0.0.1 --port "$PORT" --reload --reload-dir app) & pids+=($!)
(cd "$ROOT/frontend" && exec npm run dev -- --host 127.0.0.1 --port 5173) & pids+=($!)

echo "Dev: http://localhost:5173 (API em http://127.0.0.1:$PORT)"
wait -n
cleanup
