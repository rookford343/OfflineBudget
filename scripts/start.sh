#!/usr/bin/env bash
# Development runner: backend (reload) + Vite, both loopback-only, scheduler off,
# against data/dev.db. Never touches the live DB (data/budget.db).
# Production is scripts/run-production.sh. Usage: scripts/start.sh [--check]
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$HOME/.bun/bin:$PATH"
cd "$(dirname "$0")/.."
ROOT="$(pwd -P)"

DB_URL="${DATABASE_URL:-sqlite:///./data/dev.db}"
DB_PATH="${DB_URL#sqlite:///}"
case "$DB_PATH" in /*) ;; *) DB_PATH="$ROOT/$DB_PATH" ;; esac

# Resolve to an absolute path (dir part must exist for symlinks/.. to resolve).
DB_DIR="$(dirname "$DB_PATH")"
if [ -d "$DB_DIR" ]; then
  DB_DIR="$(cd "$DB_DIR" && pwd -P)"
fi
RESOLVED="$DB_DIR/$(basename "$DB_PATH")"
LIVE="$(cd "$ROOT/data" && pwd -P)/budget.db"

if [ "$RESOLVED" = "$LIVE" ]; then
  echo "ERROR: refusing to run dev against the live database ($LIVE). Use data/dev.db." >&2
  exit 1
fi

BACKEND=(uv run --locked uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload)

if [ "${1:-}" = "--check" ]; then
  [ -f "$RESOLVED" ] || echo "(would create $RESOLVED from the live DB via backup_database())"
  echo "DATABASE_URL=$DB_URL SCHEDULER_ENABLED=false ${BACKEND[*]}"
  echo "(cd frontend && bun run dev)   # vite binds 127.0.0.1"
  exit 0
fi

uv sync --locked

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

if [ ! -f "$RESOLVED" ] && [ -f "$LIVE" ]; then
  echo "Creating $RESOLVED from the live DB with backup_database() (first dev run)."
  uv run --locked python -c "from backend.services.db_backup import backup_database; backup_database('$LIVE', '$RESOLVED')"
fi

export DATABASE_URL="$DB_URL"
export SCHEDULER_ENABLED=false

echo ""
echo "  OfflineBudget (dev, loopback only)"
echo "  Backend  -> http://127.0.0.1:8000"
echo "  Frontend -> http://127.0.0.1:5173"
echo "  Database -> $RESOLVED"
echo ""

"${BACKEND[@]}" &
BACKEND_PID=$!

(cd frontend && exec bun run dev) &
FRONTEND_PID=$!

trap 'kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit' SIGINT SIGTERM
wait
