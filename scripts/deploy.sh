#!/usr/bin/env bash
# Build the SPA, back up the DB, restart the LaunchAgent, wait for /api/health.
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$HOME/.bun/bin:$PATH"
cd "$(dirname "$0")/.."

if [ ! -f data/budget.db ]; then
  echo "ERROR: data/budget.db not found; refusing to deploy (would back up an empty DB)." >&2
  exit 1
fi

if [ -n "$(git status --porcelain)" ]; then
  echo "ERROR: working tree has uncommitted changes; commit or stash before deploying (the deployed commit must be reproducible)." >&2
  exit 1
fi

# Build into a temp dir, then swap into frontend/dist with mv, so the running
# server never serves a half-written dist.
(cd frontend && bun install --frozen-lockfile)
BUILD_DIR="$(mktemp -d "$PWD/frontend/.dist-build.XXXXXX")"
trap 'rm -rf "$BUILD_DIR"' EXIT
(cd frontend && bunx vite build --outDir "$BUILD_DIR" --emptyOutDir)
[ -f "$BUILD_DIR/index.html" ] || { echo "ERROR: build produced no index.html" >&2; exit 1; }
chmod 755 "$BUILD_DIR"
rm -rf frontend/dist.old
if [ -d frontend/dist ]; then mv frontend/dist frontend/dist.old; fi
mv "$BUILD_DIR" frontend/dist
rm -rf frontend/dist.old

mkdir -p data/backups data/logs
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="data/backups/pre-deploy-$STAMP.db"
uv run --locked python -c "from backend.services.db_backup import backup_database; backup_database('data/budget.db', '$BACKUP')"
echo "Backed up DB to $BACKUP"
git rev-parse HEAD > data/logs/deployed-commit
echo "Deployed commit $(cat data/logs/deployed-commit)"

launchctl kickstart -k "gui/$(id -u)/com.offlinebudget.server"

# One URL to change: FRONTEND_URL in .env (https://df-macbookpro16.local:8443 in Mac-only mode,
# https://df-macbookpro16.local in LAN mode).
BASE_URL="$(sed -n 's/^FRONTEND_URL=//p' .env 2>/dev/null | tail -n1 | tr -d '"'"'"' ' | sed 's|/*$||')"
URL="${BASE_URL:-https://df-macbookpro16.local:8443}/api/health"
for _ in $(seq 1 30); do
  code="$(curl -s --max-time 3 -o /dev/null -w '%{http_code}' --cacert "$HOME/.offlinebudget-ca/ca.crt" "$URL" || true)"
  if [ "$code" = "200" ]; then
    echo "Deployed: $URL returned 200"
    exit 0
  fi
  sleep 1
done
echo "ERROR: $URL did not return 200 within 30s. See data/logs/server.err.log." >&2
exit 1
