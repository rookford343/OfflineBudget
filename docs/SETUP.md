# Setup

## Phone on home Wi-Fi

OfflineBudget runs as one HTTPS uvicorn process on port 443 under a macOS LaunchAgent. It serves the built app and `/api`, and it is the only process with the scheduler on. Host name: `df-macbookpro16.local`.

### 1. Private CA and server certificate

```bash
scripts/tls/make-ca.sh                                  # writes ~/.offlinebudget-ca/ca.crt
scripts/tls/issue-cert.sh ~/.offlinebudget-ca df-macbookpro16.local ssl
```

`issue-cert.sh` prints the expiry date (825 days). To renew, rerun it with the same CA before then and redeploy.

### 2. Trust the CA on the iPhone

1. AirDrop `~/.offlinebudget-ca/ca.crt` to the phone and install the profile (Settings, Profile Downloaded).
2. Settings, General, About, Certificate Trust Settings: turn on full trust for the CA.
3. Open `https://df-macbookpro16.local` in Safari.

### 3. Install the LaunchAgent

```bash
mkdir -p data/logs
sed "s|__REPO__|$(pwd)|g" scripts/launchd/com.offlinebudget.server.plist.template \
  > ~/Library/LaunchAgents/com.offlinebudget.server.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.offlinebudget.server.plist
```

The server starts at login, not at boot (accepted limitation after a reboot). Logs: `data/logs/server.{out,err}.log`.

### 4. Firewall

```bash
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --setglobalstate on --setstealthmode on
```

Then allow incoming connections for the uv-managed Python when macOS asks (or add it in System Settings, Network, Firewall, Options).

### 5. Deploy

```bash
scripts/deploy.sh
```

Builds the frontend, backs up the database to `data/backups/pre-deploy-<timestamp>.db`, restarts the LaunchAgent, and waits up to 30 seconds for `https://df-macbookpro16.local/api/health` to return 200.

### Development

`scripts/start.sh` runs a reloading backend and Vite on 127.0.0.1 with the scheduler off, against `data/dev.db`. On first run it creates `data/dev.db` from the live database with `backup_database()`. It refuses to run against `data/budget.db`. `scripts/start.sh --check` and `scripts/run-production.sh --check` print what they would run and change nothing.
