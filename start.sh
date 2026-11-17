#!/usr/bin/env bash
# Music Tracks — starts worker + API and opens the browser (spec §4).
set -uo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PORT="${MUSIC_TRACKS_PORT:-8765}"
export MUSIC_TRACKS_PORT="$PORT"
export PATH="/opt/homebrew/bin:$PATH"

missing=()
for cmd in uv node npm ffmpeg ffprobe; do
  command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
done
if ((${#missing[@]})); then
  echo "Dependências ausentes / missing dependencies: ${missing[*]}"
  pkgs=()
  for m in "${missing[@]}"; do
    case "$m" in
      npm) pkgs+=(node) ;;
      ffprobe) pkgs+=(ffmpeg) ;;
      *) pkgs+=("$m") ;;
    esac
  done
  echo "  brew install $(printf '%s\n' "${pkgs[@]}" | sort -u | tr '\n' ' ')"
  exit 1
fi

if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "A porta $PORT já está em uso / port $PORT is already in use."
  echo "Use MUSIC_TRACKS_PORT=<outra porta> ./start.sh"
  exit 1
fi

echo "==> Backend: uv sync"
(cd "$ROOT/backend" && uv sync --quiet) || exit 1

FRONT="$ROOT/frontend"
needs_build=0
if [[ ! -f "$FRONT/dist/index.html" ]]; then
  needs_build=1
elif [[ -n "$(find "$FRONT/src" "$FRONT/index.html" "$FRONT/package.json" -newer "$FRONT/dist/index.html" -print -quit 2>/dev/null)" ]]; then
  needs_build=1
fi
if ((needs_build)); then
  echo "==> Frontend: build"
  if [[ ! -d "$FRONT/node_modules" || "$FRONT/package-lock.json" -nt "$FRONT/node_modules" ]]; then
    (cd "$FRONT" && npm ci --no-audit --no-fund) || exit 1
  fi
  (cd "$FRONT" && npm run build) || exit 1
fi

WORKER_PID=""
API_PID=""

start_worker() {
  (cd "$ROOT/backend" && exec uv run --quiet python -m app.worker) &
  WORKER_PID=$!
}

cleanup() {
  trap - INT TERM EXIT
  echo
  echo "==> Encerrando / stopping..."
  [[ -n "$API_PID" ]] && kill "$API_PID" 2>/dev/null
  [[ -n "$WORKER_PID" ]] && kill "$WORKER_PID" 2>/dev/null
  wait 2>/dev/null
}
trap 'cleanup; exit 0' INT TERM

echo "==> Iniciando worker e API em http://127.0.0.1:$PORT"
start_worker
(cd "$ROOT/backend" && exec uv run --quiet uvicorn app.api.main:app --host 127.0.0.1 --port "$PORT" --log-level warning) &
API_PID=$!

ok=0
for _ in $(seq 1 60); do
  if curl -fsS -H "Host: 127.0.0.1:$PORT" "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then ok=1; break; fi
  kill -0 "$API_PID" 2>/dev/null || break
  sleep 0.5
done
if ((!ok)); then
  echo "A API não respondeu em 30 s / API did not respond within 30 s."
  cleanup
  exit 1
fi
open "http://127.0.0.1:$PORT" 2>/dev/null || true
echo "==> Pronto / ready: http://127.0.0.1:$PORT  (Ctrl+C para sair)"

restarts=()
while true; do
  if ! kill -0 "$API_PID" 2>/dev/null; then
    echo "A API parou / API stopped."
    cleanup
    exit 1
  fi
  if ! kill -0 "$WORKER_PID" 2>/dev/null; then
    now=$(date +%s)
    recent=()
    for t in "${restarts[@]+"${restarts[@]}"}"; do
      ((now - t < 300)) && recent+=("$t")
    done
    restarts=("${recent[@]+"${recent[@]}"}")
    if ((${#restarts[@]} >= 3)); then
      echo "O worker caiu 3 vezes em 5 min; encerrando / worker crashed 3 times in 5 min; exiting."
      cleanup
      exit 1
    fi
    echo "O worker parou; reiniciando / worker stopped; restarting..."
    restarts+=("$now")
    start_worker
  fi
  sleep 1
done
