#!/usr/bin/env bash
# Start OfflineBudget: backend API + frontend dev server
# Usage: ./scripts/start.sh
# For production frontend: PROD=1 ./scripts/start.sh (serves built dist via backend)
# For HTTPS: run ./scripts/setup-ssl.sh first, then start normally.

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

# Detect SSL certificate
SSL_BACKEND_ARGS=""
SSL_FRONTEND_ARGS=""
SCHEME="http"
if [ -f "ssl/cert.pem" ] && [ -f "ssl/key.pem" ]; then
  SSL_BACKEND_ARGS="--ssl-certfile ssl/cert.pem --ssl-keyfile ssl/key.pem"
  SSL_FRONTEND_ARGS="--https"
  SCHEME="https"
fi

echo ""
echo "  OfflineBudget v2"
echo "  ─────────────────────────────────────────"
echo "  Backend  → ${SCHEME}://localhost:8000"
echo "  Frontend → ${SCHEME}://localhost:5173"
echo "  API docs → ${SCHEME}://localhost:8000/docs"
if [ -n "$SSL_BACKEND_ARGS" ]; then
  echo "  HTTPS    → enabled (self-signed cert)"
fi
echo ""

# Start backend in background
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload $SSL_BACKEND_ARGS &
BACKEND_PID=$!

# Start frontend dev server
cd frontend
if [ -n "$SSL_FRONTEND_ARGS" ]; then
  npm run dev -- --https &
else
  npm run dev &
fi
FRONTEND_PID=$!

# Clean up both on Ctrl+C
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" SIGINT SIGTERM

wait
