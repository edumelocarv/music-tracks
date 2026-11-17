#!/usr/bin/env bash
# Music Tracks: starts worker + API and opens the browser (spec §4).
# Thin wrapper around the cross-platform launcher (backend/app/launcher.py).
# Usage: ./start.sh [--port N] [--no-browser] [--dev]
# Env: MUSIC_TRACKS_PORT, MUSIC_TRACKS_HOME, MUSIC_TRACKS_HOST, MUSIC_TRACKS_NO_BROWSER
set -eu

ROOT="$(cd "$(dirname "$0")" && pwd)"

if ! command -v uv >/dev/null 2>&1; then
  # Not on PATH (e.g. non-login shell): look in the usual install locations.
  for d in "$HOME/.local/bin" "$HOME/.cargo/bin" /opt/homebrew/bin /usr/local/bin; do
    if [ -x "$d/uv" ]; then
      PATH="$d:$PATH"
      export PATH
      break
    fi
  done
fi
if ! command -v uv >/dev/null 2>&1; then
  echo "uv não encontrado / uv not found. Instale / install:" >&2
  if [ "$(uname -s)" = "Darwin" ]; then
    echo "  brew install uv" >&2
  fi
  echo "  curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  echo "(depois abra um novo terminal / then open a new terminal)" >&2
  exit 1
fi

exec uv run --project "$ROOT/backend" python -m app.launcher "$@"
