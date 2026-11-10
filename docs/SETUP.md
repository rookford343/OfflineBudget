# Setup

## Mac-only HTTPS (default)

OfflineBudget runs as one HTTPS uvicorn process under a macOS LaunchAgent. By default (`OB_EXPOSURE=mac-only`) it listens on `127.0.0.1:8443` only, so nothing on Wi-Fi can reach it. (macOS lets a normal user bind port 443 only on all interfaces, which is why loopback uses 8443.) Open `https://df-macbookpro16.local:8443`. It serves the built app and `/api`, and it is the only process with the scheduler on. Host name: `df-macbookpro16.local`.

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
   ALLOWED_ORIGINS=https://df-macbookpro16.local:8443
   FRONTEND_URL=https://df-macbookpro16.local:8443
   ```

   `FRONTEND_URL` is also the URL `scripts/deploy.sh` health-checks (`<FRONTEND_URL>/api/health`).

4. Make the Mac use loopback for its own name (otherwise mDNS may resolve it to the Wi-Fi address, which is closed). Add this line to `/etc/hosts` (`sudo nano /etc/hosts`):

   ```
   127.0.0.1 df-macbookpro16.local
   ```

Only then continue with steps 1 to 5 below (certificate, trust, build, LaunchAgent, deploy). No firewall change is needed in Mac-only mode.

### 1. Private CA and server certificate

```bash
scripts/tls/make-ca.sh                                  # writes ~/.offlinebudget-ca/ca.crt
scripts/tls/issue-cert.sh ~/.offlinebudget-ca df-macbookpro16.local ssl
```

The CA is limited to `pathlen:0` and name-constrained to `df-macbookpro16.local` and `budget.thedigitaltrailhead.com`: a certificate it signs for any other domain is rejected by clients. If you created a CA before this constraint existed, it is not constrained. Delete `~/.offlinebudget-ca`, then recreate the CA, reissue the certificate and re-trust it (step 2; on a phone, remove the old profile first).

`issue-cert.sh` prints the expiry date (825 days). To renew before then, reissue with the same CA (the old pair moves to `ssl/server.<timestamp>.bak.*`) and redeploy:

```bash
scripts/tls/issue-cert.sh --renew ~/.offlinebudget-ca df-macbookpro16.local ssl
scripts/deploy.sh
```

Delete the `ssl/server.*.bak.*` files once the renewed certificate is verified.

### 2. Trust the CA on the Mac

```bash
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain ~/.offlinebudget-ca/ca.crt
# or, login keychain only (no sudo):
security add-trusted-cert -r trustRoot -k ~/Library/Keychains/login.keychain-db ~/.offlinebudget-ca/ca.crt
```

Then open `https://df-macbookpro16.local:8443` in the browser.

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

### 5. Deploy

```bash
scripts/deploy.sh
```

Refuses to run with uncommitted changes. Builds the frontend into a temporary directory and swaps it into `frontend/dist`, backs up the database to `data/backups/pre-deploy-<timestamp>.db` (it refuses if `data/budget.db` is missing), records the deployed commit in `data/logs/deployed-commit`, restarts the LaunchAgent, and waits up to 30 seconds for `<FRONTEND_URL>/api/health` (default `https://df-macbookpro16.local:8443`) to return 200.

## Optional: phone access on home Wi-Fi

Off by default and not actively developed (see [the retrospective](phone-access-retrospective.md)). To turn it on:

1. **Expose the server.** In `~/Library/LaunchAgents/com.offlinebudget.server.plist` change the `OB_EXPOSURE` value to `lan` (binds `0.0.0.0:443`), then reload: `launchctl bootout gui/$(id -u)/com.offlinebudget.server && launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.offlinebudget.server.plist`.
2. **URLs.** In `.env` set `ALLOWED_ORIGINS` and `FRONTEND_URL` to `https://df-macbookpro16.local` (no `:8443`). The Mac's `/etc/hosts` line can stay.
3. **Trust the CA on the iPhone.** AirDrop `~/.offlinebudget-ca/ca.crt` to the phone and install the profile (Settings, General, VPN & Device Management). Then Settings, General, About, Certificate Trust Settings: turn on full trust. Open `https://df-macbookpro16.local` in Safari (type the exact name; `df-macbookpro.local` is wrong).
4. **Firewall.** Needed so the phone can connect:

```bash
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --setglobalstate on --setstealthmode on
PY="$(ps -o comm= -p "$(lsof -tnP -iTCP:443 -sTCP:LISTEN)")"
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add "$PY" --unblockapp "$PY"
```

Run this after the server is up (step 5): `PY` is the binary that is actually listening on port 443. Do not use `sys.executable`: Homebrew's framework Python re-execs into `.../Resources/Python.app/Contents/MacOS/Python`, and that is the binary `lsof` and the firewall see, not `.../bin/python3.11`. If the command prints nothing, the server is not listening yet; check `data/logs/server.err.log`, or find the path by hand with `lsof -nP -iTCP:443 -sTCP:LISTEN` and `ps -p <PID> -o comm=`. Re-run both commands whenever uv's Python version changes (the path changes with it, and the firewall would block the new binary).

Also turn off automatic exceptions for signed software, so only the binary you added is allowed in:

```bash
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --setallowsigned off --setallowsignedapp off
```

(UI: System Settings, Network, Firewall, Options, turn off "Automatically allow built-in software" and "Automatically allow downloaded signed software".)

To turn it off again: set `OB_EXPOSURE` back to `mac-only`, reload the LaunchAgent, put the `:8443` URLs back in `.env`, and undo the firewall and phone items in the [reversal checklist](phone-access-retrospective.md#reversal-checklist).

## Development

`scripts/start.sh` runs a reloading backend and Vite on 127.0.0.1 with the scheduler off, against `data/dev.db`. On first run it creates `data/dev.db` from the live database with `backup_database()`. It refuses to run against `data/budget.db`. `scripts/start.sh --check` and `scripts/run-production.sh --check` print what they would run and change nothing.
