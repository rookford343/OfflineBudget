# Phone access retrospective

Written 2026-11-09 for the owner and a future iOS-app builder.

## Where it stands

Decision: stop investing in phone access for now. Production is HTTPS on `127.0.0.1:8443`, reachable only from the Mac (`OB_EXPOSURE=mac-only`, the default). Phone mode still works: one switch (`OB_EXPOSURE=lan`) plus the steps in [SETUP.md](SETUP.md#optional-phone-access-on-home-wi-fi).

## What went well

- A private, name-constrained CA (`pathlen:0`, only `df-macbookpro16.local` and `budget.thedigitaltrailhead.com`), so a leaked CA key cannot impersonate other sites.
- Passkeys work on a `.local` name in iOS Safari over that CA.
- One origin: the SPA and `/api` share it. The service worker never caches `/api`.
- A phone Dashboard that leads with Safety Margin.
- One-offs use preview-then-commit and reuse the Dashboard calculation, so there is no second set of money math.
- Startup database snapshots before any migration.
- The review loop caught: the Goals trailing-slash 404 under the SPA, preview leaking into audit logs, an unconstrained CA, an unsafe setup order, and money math in the frontend.

## What was hard

- The exact name: `df-macbookpro.local` loads but is not `df-macbookpro16.local`, and a passkey binds to the exact host.
- macOS lets a normal user bind ports below 1024 only on the wildcard address, so loopback mode uses 8443.
- The firewall sees Homebrew's `Python.app` binary, not `python3.11`. Bitdefender may be a second firewall.
- The Duo: a side status strip, and folded/unfolded widths of about 457 and 951 CSS px.
- The LaunchAgent starts at login, not at boot.

## For the iOS app

Read [ios-lessons.md](ios-lessons.md). Carries over: the `/api` contract, the preview endpoint, money masking, the per-width layout decisions. A native app would differ: Keychain instead of a localStorage token, no CA profile if the server gets a real certificate, push notifications.

## Reversal checklist

**iPhone**
- "OfflineBudget Home CA" profile (a full trust root on the phone): Settings, General, VPN & Device Management, the profile, Remove. The trust toggle goes with it.
- Test passkey for `df-macbookpro16.local`: Settings, Passwords, search, delete.
- Home-screen icon: remove it.

**Mac firewall** (already reverted by the owner on 2026-11-09 to its pre-project state)
- Stealth mode off and "automatically allow signed software" on were restored with:
  `sudo /usr/libexec/ApplicationFirewall/socketfilterfw --setstealthmode off` and `--setallowsigned on --setallowsignedapp on`.
- The bun allowance was removed (`socketfilterfw --remove <bun path>`).
- The Homebrew `Python.app` "allow incoming" entry pre-dated this work; leave it. (If you ever add one for LAN mode, undo with `socketfilterfw --remove <path>`.)
- Before 2026-11-09 the safer settings could break AirPlay Receiver and other local servers; that no longer applies.

**Mac**
- CA trust: `sudo security delete-certificate -c "OfflineBudget Home CA" /Library/Keychains/System.keychain` (for a login-keychain install, drop `sudo` and use `~/Library/Keychains/login.keychain-db`).
- `/etc/hosts`: delete the `127.0.0.1 df-macbookpro16.local` line.
- CA private key `~/.offlinebudget-ca/ca.key` (encrypted): keep it in a password manager, or delete it if abandoning. Deleting means re-issuing everything later.
- LaunchAgent: `launchctl bootout gui/$(id -u)/com.offlinebudget.server`, then delete `~/Library/LaunchAgents/com.offlinebudget.server.plist`, to go back to `scripts/start.sh`. Note `start.sh` now uses `data/dev.db`; going fully back to the old live-dev setup means running the backend against `data/budget.db` deliberately.

**Repo**
- `.env`: put `ALLOWED_ORIGINS` and `FRONTEND_URL` back to your old values.
- `ssl/` (gitignored): delete if abandoning.
- Old frozen worktree: `git worktree remove ../OfflineBudget-live`.

## Backups made during the work

In `data/backups/`: `pre-phone-202611071328.db`, `pre-setup-20261109.db`, `env.pre-setup-20261109`, `startup-*.db` (newest 10 kept), `pre-deploy-*.db`.
