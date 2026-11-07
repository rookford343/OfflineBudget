# Setup

## Phone on home Wi-Fi

OfflineBudget runs as one HTTPS uvicorn process on port 443 under a macOS LaunchAgent. It serves the built app and `/api`, and it is the only process with the scheduler on. Host name: `df-macbookpro16.local`.

### 1. Private CA and server certificate

```bash
scripts/tls/make-ca.sh                                  # writes ~/.offlinebudget-ca/ca.crt
scripts/tls/issue-cert.sh ~/.offlinebudget-ca df-macbookpro16.local ssl
```

`issue-cert.sh` prints the expiry date (825 days). To renew before then, reissue with the same CA (the old pair moves to `ssl/server.<timestamp>.bak.*`) and redeploy:

```bash
scripts/tls/issue-cert.sh --renew ~/.offlinebudget-ca df-macbookpro16.local ssl
scripts/deploy.sh
```

### 2. Trust the CA on the iPhone

1. AirDrop `~/.offlinebudget-ca/ca.crt` to the phone, then install the profile from Settings, General, VPN & Device Management.
2. Settings, General, About, Certificate Trust Settings: turn on full trust for the CA.
3. Open `https://df-macbookpro16.local` in Safari.

### 3. Build the app

The server refuses to start without `frontend/dist/index.html`, so build first:

```bash
(cd frontend && bun install --frozen-lockfile && bunx vite build)
```

### 4. Install the LaunchAgent

```bash
mkdir -p data/logs ~/Library/LaunchAgents
sed "s|__REPO__|$(pwd)|g" scripts/launchd/com.offlinebudget.server.plist.template \
  > ~/Library/LaunchAgents/com.offlinebudget.server.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.offlinebudget.server.plist
```

To reinstall after changing the plist, unload it first:

```bash
launchctl bootout gui/$(id -u)/com.offlinebudget.server
```

The server starts at login, not at boot (accepted limitation after a reboot). Logs: `data/logs/server.{out,err}.log`.

### 5. Firewall

```bash
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --setglobalstate on --setstealthmode on
PY="$(uv run --locked python -c "import sys,os;print(os.path.realpath(sys.executable))")"
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add "$PY" --unblockapp "$PY"
```

`PY` is the real path of the uv-managed venv Python that serves the app.

### 6. Deploy

```bash
scripts/deploy.sh
```

Builds the frontend, backs up the database to `data/backups/pre-deploy-<timestamp>.db` (it refuses if `data/budget.db` is missing), restarts the LaunchAgent, and waits up to 30 seconds for `https://df-macbookpro16.local/api/health` to return 200.

### Development

`scripts/start.sh` runs a reloading backend and Vite on 127.0.0.1 with the scheduler off, against `data/dev.db`. On first run it creates `data/dev.db` from the live database with `backup_database()`. It refuses to run against `data/budget.db`. `scripts/start.sh --check` and `scripts/run-production.sh --check` print what they would run and change nothing.
