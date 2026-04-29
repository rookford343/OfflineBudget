#!/usr/bin/env bash
# Start OfflineBudget: backend API + frontend dev server
# Usage: ./scripts/start.sh
# For production frontend: PROD=1 ./scripts/start.sh (serves built dist via backend)

set -e
cd "$(dirname "$0")/.."

# Activate venv if it exists
if [ -d ".venv" ]; then
  source .venv/bin/activate
fi

# Copy .env if it doesn't exist yet
if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "Created .env from .env.example — update JWT_SECRET before exposing on LAN"
fi

echo ""
echo "  OfflineBudget v2"
echo "  ─────────────────────────────────────────"
echo "  Backend  → http://localhost:8000"
echo "  Frontend → http://localhost:5173"
echo "  API docs → http://localhost:8000/docs"
echo ""

# Start backend in background
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

# Start frontend dev server
cd frontend
npm run dev &
FRONTEND_PID=$!

# Clean up both on Ctrl+C
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" SIGINT SIGTERM

wait
