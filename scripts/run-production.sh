#!/usr/bin/env bash
# Production server: one HTTPS uvicorn on 0.0.0.0:443 serving the built app and /api,
# with the scheduler on. Run by the com.offlinebudget.server LaunchAgent.
# Usage: scripts/run-production.sh [--check]   (--check prints the command and exits)
set -euo pipefail

# launchd gives a minimal PATH; make uv resolvable.
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$HOME/.bun/bin:$PATH"

cd "$(dirname "$0")/.."

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

CMD=(uv run --locked uvicorn backend.main:app --host 0.0.0.0 --port 443
     --ssl-certfile "$SSL_DIR/server.crt" --ssl-keyfile "$SSL_DIR/server.key" --no-proxy-headers)

# Env must not be able to turn on --reload, other ports, etc.
for v in $(compgen -e | grep '^UVICORN_' || true); do unset "$v"; done

export SCHEDULER_ENABLED=true
export FRONTEND_DIST_DIR="$DIST_DIR"

if [ "${1:-}" = "--check" ]; then
  echo "uvicorn_env_vars=$(env | grep -c '^UVICORN_' || true)"
  echo "SCHEDULER_ENABLED=true FRONTEND_DIST_DIR=$DIST_DIR ${CMD[*]}"
  exit 0
fi

exec "${CMD[@]}"
