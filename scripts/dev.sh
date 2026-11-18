#!/usr/bin/env bash
# Start backend (inline workers, SQLite) and frontend for local development on Linux/macOS.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"
[ -d .venv ] || { python3 -m venv .venv && .venv/bin/pip install -r requirements.txt; }
.venv/bin/python -m uvicorn app.main:app --port 8000 &
BACK=$!
trap 'kill $BACK' EXIT
cd "$ROOT/frontend"
[ -d node_modules ] || npm install
npm run dev
