#!/usr/bin/env bash
# One-command dev server: deps + env + uvicorn (+ optional Vite).
#   ./run.sh                          SPA built/served by FastAPI on :8000
#   PORT=9000 ./run.sh
#   DEV_FRONTEND=1 ./run.sh           dual-process: Vite :5173 + API on PORT
set -euo pipefail
cd "$(dirname "$0")"

# Force UTF-8: the real data-designer package logs emoji via `rich`, which
# crashes on Windows cp1252 consoles; uvicorn also benefits from it.
export PYTHONUTF8=1

export PORT="${PORT:-8000}"

# .env is optional (and gitignored): KEY=value lines, exported into the app's
# environment. The app itself only reads os.environ, so sourcing is enough.
if [ -f .env ]; then
  set -a; . ./.env; set +a
fi

if [ -n "${NVIDIA_API_KEY:-}" ]; then
  echo "NVIDIA_API_KEY set (${NVIDIA_API_KEY:0:7}...) - LLM-backed generation enabled"
else
  echo "NVIDIA_API_KEY not set - offline Faker fallback mode"
fi

pip install -q -r requirements.txt

FRONTEND_DIR="frontend"
DIST_DIR="$FRONTEND_DIR/dist"

if [ "${DEV_FRONTEND:-}" = "1" ]; then
  if [ -f "$FRONTEND_DIR/package.json" ]; then
    if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
      (cd "$FRONTEND_DIR" && npm install)
    fi
    (cd "$FRONTEND_DIR" && npm run dev) &
    VITE_PID=$!
    trap 'kill "$VITE_PID" 2>/dev/null || true' EXIT
    echo "Wizard UI  http://localhost:5173  (Vite dev; /api proxied to backend)"
    echo "API        http://localhost:${PORT}"
  else
    echo "DEV_FRONTEND=1 but frontend/package.json not found — starting API only"
  fi
elif [ -f "$FRONTEND_DIR/package.json" ]; then
  if [ ! -d "$DIST_DIR" ]; then
    echo "Building frontend (frontend/dist missing)..."
    (cd "$FRONTEND_DIR" && { [ -d node_modules ] || npm install; } && npm run build)
  fi
  echo "Wizard UI  http://localhost:${PORT}  (React SPA)"
  echo "Legacy UI  http://localhost:${PORT}/legacy/"
else
  echo "Studio     http://localhost:${PORT}"
  echo "Eval Lab   http://localhost:${PORT}/eval.html"
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --reload
