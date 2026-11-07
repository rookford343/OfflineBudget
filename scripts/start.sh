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

# Resolve to an absolute, normalized path without requiring directories to
# exist: "." and ".." are folded away lexically first (so data/../data/x.db is
# data/x.db even in a fresh clone with no data/), then the directory is
# physically resolved when it exists (symlinked directories).
resolve() {
  local d b part IFS=/
  local -a out=()
  for part in $1; do
    case "$part" in
      ""|.) ;;
      ..) if [ ${#out[@]} -gt 0 ]; then unset 'out[${#out[@]}-1]'; fi ;;
      *) out+=("$part") ;;
    esac
  done
  IFS=' '
  d="/"; b=""
  if [ ${#out[@]} -gt 0 ]; then
    b="${out[${#out[@]}-1]}"
    unset 'out[${#out[@]}-1]'
    IFS=/; d="/${out[*]-}"; IFS=' '
  fi
  if [ -d "$d" ]; then d="$(cd "$d" && pwd -P)"; fi
  echo "${d%/}/$b"
}
RESOLVED="$(resolve "$DB_PATH")"
# One source for the live path: Settings.LIVE_DATABASE_PATH (default data/budget.db).
LIVE_REL="$(uv run --locked --no-sync python -c "from backend.config import settings; print(settings.LIVE_DATABASE_PATH)" 2>/dev/null | tail -n 1 || true)"
LIVE_REL="${LIVE_REL:-data/budget.db}"
case "$LIVE_REL" in /*) ;; *) LIVE_REL="$ROOT/$LIVE_REL" ;; esac
LIVE="$(resolve "$LIVE_REL")"

lower() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }
same_file=0
if [ -e "$RESOLVED" ] && [ -e "$LIVE" ] && [ "$RESOLVED" -ef "$LIVE" ]; then same_file=1; fi
# Case-insensitive compare (APFS), plus inode compare for symlinks and hard links.
if [ "$(lower "$RESOLVED")" = "$(lower "$LIVE")" ] || [ $same_file -eq 1 ]; then
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

mkdir -p data
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
