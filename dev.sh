#!/usr/bin/env bash
# Development mode: worker + API (--reload) + Vite dev server on :5173 (spec §4).
# Same as ./start.sh --dev (MUSIC_TRACKS_DEV=1 is set by the launcher).
set -eu
exec "$(cd "$(dirname "$0")" && pwd)/start.sh" --dev "$@"
