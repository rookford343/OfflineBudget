# Setup

## Phone on home Wi-Fi

OfflineBudget runs as one HTTPS uvicorn process on port 443 under a macOS LaunchAgent. It serves the built app and `/api`, and it is the only process with the scheduler on. Host name: `df-macbookpro16.local`.

### 0. Before you start (do these first, in order)

Starting the LaunchAgent runs database migrations immediately, and a second running backend would double-run bank sync and emails. So:

1. Back up the live database (never `cp`; the WAL file makes a plain copy stale):

   ```bash
   mkdir -p data/backups
   uv run --locked python -c "from backend.services.db_backup import backup_database; backup_database('data/budget.db', 'data/backups/pre-setup.db')"
   ```

2. Stop every other backend and dev server (the old frozen backend, `scripts/start.sh`, Vite), then confirm nothing is listening. This must print nothing:

   ```bash
   lsof -nP -iTCP:8000 -iTCP:5173 -iTCP:443 -sTCP:LISTEN
   ```

3. Set the production origin in `.env`:

   ```
   ALLOWED_ORIGINS=https://df-macbookpro16.local
   FRONTEND_URL=https://df-macbookpro16.local
   ```

Only then continue with steps 1 to 6 below (certificate, build, LaunchAgent, firewall, deploy).

### 1. Private CA and server certificate

```bash
scripts/tls/make-ca.sh                                  # writes ~/.offlinebudget-ca/ca.crt
scripts/tls/issue-cert.sh ~/.offlinebudget-ca df-macbookpro16.local ssl
```

The CA is limited to `pathlen:0` and name-constrained to `df-macbookpro16.local` and `budget.thedigitaltrailhead.com`: a certificate it signs for any other domain is rejected by clients. If you created a CA before this constraint existed, it is not constrained. Delete `~/.offlinebudget-ca` and remove the old profile from the phone (Settings, General, VPN & Device Management), then recreate the CA, reissue the certificate and reinstall the profile (step 2).

`issue-cert.sh` prints the expiry date (825 days). To renew before then, reissue with the same CA (the old pair moves to `ssl/server.<timestamp>.bak.*`) and redeploy:

```bash
scripts/tls/issue-cert.sh --renew ~/.offlinebudget-ca df-macbookpro16.local ssl
scripts/deploy.sh
```

Delete the `ssl/server.*.bak.*` files once the renewed certificate is verified on the phone.

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

Every start first snapshots the database to `data/backups/startup-<timestamp>.db` (at most one per 10 minutes; the newest 10 are kept, and older ones are deleted only after 48 hours); if the snapshot fails, the server does not start.

### 5. Firewall

```bash
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --setglobalstate on --setstealthmode on
PY="$(uv run --locked python -c "import sys,os;print(os.path.realpath(sys.executable))")"
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add "$PY" --unblockapp "$PY"
```

`PY` is the real path of the uv-managed venv Python that serves the app. Re-run these two commands whenever uv's Python version changes (the path changes with it, and the firewall would block the new binary).

Also turn off automatic exceptions for signed software, so only the binary you added is allowed in:

```bash
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --setallowsigned off --setallowsignedapp off
```

(UI: System Settings, Network, Firewall, Options, turn off "Automatically allow built-in software" and "Automatically allow downloaded signed software".)

### 6. Deploy

```bash
scripts/deploy.sh
```

Refuses to run with uncommitted changes. Builds the frontend into a temporary directory and swaps it into `frontend/dist`, backs up the database to `data/backups/pre-deploy-<timestamp>.db` (it refuses if `data/budget.db` is missing), records the deployed commit in `data/logs/deployed-commit`, restarts the LaunchAgent, and waits up to 30 seconds for `https://df-macbookpro16.local/api/health` to return 200.

### Development

`scripts/start.sh` runs a reloading backend and Vite on 127.0.0.1 with the scheduler off, against `data/dev.db`. On first run it creates `data/dev.db` from the live database with `backup_database()`. It refuses to run against `data/budget.db`. `scripts/start.sh --check` and `scripts/run-production.sh --check` print what they would run and change nothing.
