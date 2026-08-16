#!/usr/bin/env bash
# One-command dev server: deps + env + uvicorn.
#   ./run.sh            start on :8000
#   PORT=9000 ./run.sh  start on another port
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8000}"

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
echo "Studio   http://localhost:${PORT}"
echo "Eval Lab http://localhost:${PORT}/eval.html"
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --reload
