#!/usr/bin/env bash
# Build the SPA, back up the DB, restart the LaunchAgent, wait for /api/health.
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$HOME/.bun/bin:$PATH"
cd "$(dirname "$0")/.."

if [ ! -f data/budget.db ]; then
  echo "ERROR: data/budget.db not found; refusing to deploy (would back up an empty DB)." >&2
  exit 1
fi

(cd frontend && bun install --frozen-lockfile && bunx vite build)

mkdir -p data/backups data/logs
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="data/backups/pre-deploy-$STAMP.db"
uv run --locked python -c "from backend.services.db_backup import backup_database; backup_database('data/budget.db', '$BACKUP')"
echo "Backed up DB to $BACKUP"

launchctl kickstart -k "gui/$(id -u)/com.offlinebudget.server"

URL="https://df-macbookpro16.local/api/health"
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
