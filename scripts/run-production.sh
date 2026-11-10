#!/usr/bin/env bash
# Production server: one HTTPS uvicorn serving the built app and /api, with the scheduler on.
# OB_EXPOSURE=mac-only (default) binds 127.0.0.1:8443; OB_EXPOSURE=lan binds 0.0.0.0:443. Run by the com.offlinebudget.server LaunchAgent.
# Usage: scripts/run-production.sh [--check]   (--check prints the command and exits)
set -euo pipefail

# launchd gives a minimal PATH; make uv resolvable.
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$HOME/.bun/bin:$PATH"

cd "$(dirname "$0")/.."

UV="${OB_UV_BIN:-uv}"   # overridable so tests can stub uv
SSL_DIR="${OB_SSL_DIR:-ssl}"
DIST_DIR="${OB_DIST_DIR:-frontend/dist}"

for f in "$SSL_DIR/server.crt" "$SSL_DIR/server.key"; do
  if [ ! -f "$f" ]; then
    echo "ERROR: missing ssl/server.crt or ssl/server.key ($f not found). Run scripts/tls/issue-cert.sh." >&2
    exit 1
  fi
done
if [ ! -f "$DIST_DIR/index.html" ]; then
  echo "ERROR: $DIST_DIR/index.html not found. Run scripts/deploy.sh (or bunx vite build in frontend/)." >&2
  exit 1
fi

# macOS only lets a normal user bind ports below 1024 on the wildcard address, so loopback uses 8443.
EXPOSURE="${OB_EXPOSURE:-mac-only}"
case "$EXPOSURE" in
  mac-only) BIND_HOST=127.0.0.1; BIND_PORT=8443 ;;
  lan)      BIND_HOST=0.0.0.0;   BIND_PORT=443 ;;
  *) echo "ERROR: OB_EXPOSURE must be 'mac-only' or 'lan' (got '$EXPOSURE')." >&2; exit 1 ;;
esac

CMD=("$UV" run --locked uvicorn backend.main:app --host "$BIND_HOST" --port "$BIND_PORT"
     --ssl-certfile "$SSL_DIR/server.crt" --ssl-keyfile "$SSL_DIR/server.key" --no-proxy-headers)

# Env must not be able to turn on --reload, other ports, etc.
for v in $(compgen -e | grep '^UVICORN_' || true); do unset "$v"; done

export SCHEDULER_ENABLED=true
export FRONTEND_DIST_DIR="$DIST_DIR"

if [ "${1:-}" = "--check" ]; then
  echo "uvicorn_env_vars=$(env | grep -c '^UVICORN_' || true)"
  echo "exposure=$EXPOSURE"
  echo "SCHEDULER_ENABLED=true FRONTEND_DIST_DIR=$DIST_DIR ${CMD[*]}"
  echo "startup_backup=data/backups/startup-*.db keep=10 min_interval=10m retain=48h"
  exit 0
fi

# Snapshot the database the app will actually open (settings.DATABASE_URL), WAL-safe,
# before the server can run startup migrations. If this fails, do not start:
# a server that can't snapshot must not migrate.
if ! "$UV" run --locked python -m backend.services.db_backup; then
  echo "ERROR: startup database backup failed; not starting the server." >&2
  exit 1
fi

exec "${CMD[@]}"
