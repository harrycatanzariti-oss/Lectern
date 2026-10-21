#!/usr/bin/env bash
# ./run.sh setup   install backend and frontend dependencies
# ./run.sh dev     API on :8000 and the Vite dev server on :5173
# ./run.sh serve   build the frontend and serve everything from :8000
# ./run.sh test    backend tests + frontend typecheck/build
set -euo pipefail
cd "$(dirname "$0")"

case "${1:-}" in
  setup)
    python3 -m venv .venv
    .venv/bin/pip install -q -r backend/requirements.txt
    (cd frontend && npm install)
    ;;
  dev)
    trap 'kill 0' EXIT
    (cd backend && ../.venv/bin/uvicorn lectern.api:app --reload --port 8000) &
    (cd frontend && npm run dev)
    ;;
  serve)
    (cd frontend && npm run build)
    cd backend && exec ../.venv/bin/uvicorn lectern.api:app --host 0.0.0.0 --port "${PORT:-8000}"
    ;;
  test)
    (cd backend && ../.venv/bin/python -m pytest -q)
    (cd frontend && npm run build)
    ;;
  *)
    sed -n '2,5p' "$0"
    exit 1
    ;;
esac
