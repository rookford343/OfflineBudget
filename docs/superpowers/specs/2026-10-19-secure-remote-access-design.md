# Secure remote access, passkeys, and a phone app: design

Status: approved section by section in chat, 2026-10-19.

## Goal

Use the app from anywhere, including an iPhone, without exposing it to the
public internet, and replace password-only login with passkeys.

## Threat model (what this defends against)

| Threat | Defense |
|---|---|
| Internet scanning and exploitation of the app | Never publicly reachable. Only devices enrolled in a private network can connect. |
| Stolen password, credential stuffing, phishing | Passkeys (phishing-resistant, device-bound). Password login can be turned off. The password fallback is rate-limited. |
| XSS stealing a session | Session moves from script-readable storage to an `HttpOnly; Secure; SameSite=Strict` cookie. |
| Lost or stolen phone with a live session | Server-side sessions with idle expiry, plus "sign out all devices". |
| Stolen server disk | Full-disk encryption (TPM-sealed key). |
| Someone silently adding a passkey | Audit log plus an email alert on every new passkey. |
| Data loss | Nightly encrypted, off-box backups with a tested restore. |

Out of scope: an attacker with physical access to the whole running server
(TPM auto-unlock accepts this), and compromise of the user's enrolled devices.

## 1. Server and network

- A dedicated always-on desktop running **Ubuntu Server 24.04 LTS**, minimal
  and headless, with unattended security upgrades.
- **Full-disk encryption (LUKS)** with the key sealed to the **TPM**, so the
  machine reboots unattended after a power loss. A recovery passphrase is kept
  offline.
- **Tailscale** is the only way in:
  - The app is served over HTTPS on the device's private tailnet name.
  - Tailscale ACLs allow only the owner's devices.
  - SSH runs only over Tailscale.
- **Firewall (ufw):** deny all inbound except on the Tailscale interface. No
  router port forwarding.
- The app runs under **Docker Compose** as a production build, not the dev
  servers. The backend binds only to localhost or the tailnet interface.

## 2. Login and sessions

1. **Passkeys (WebAuthn)**
   - Register and remove passkeys under Settings → Security. Sign in with a
     passkey (Face ID / Touch ID).
   - Server: `py_webauthn`. Browser: `@simplewebauthn/browser`. Both are
     reviewed before install and pinned exactly. Python dependencies use the
     7-day uv cooldown.
   - The relying-party ID is the app's single HTTPS hostname.
   - A per-user setting turns off password login once at least one passkey
     exists.
2. **Sessions**
   - A server-side session table replaces the 7-day stateless bearer token.
   - The session ID lives in an `HttpOnly; Secure; SameSite=Strict` cookie.
   - Idle expiry is 24h, plus an absolute lifetime cap.
   - "Sign out all devices" deletes every session for the user.
   - State-changing requests are protected against CSRF (SameSite=Strict plus
     an origin check).
3. **Password fallback**
   - Rate-limited per account and per client: about 5 failures per 15 minutes,
     then a cool-down.
   - Recovery codes remain.
4. **Audit log and alerts**
   - Logged events: login success and failure, passkey added or removed,
     password-login toggled, sign-out-all.
   - Adding a passkey sends an email alert.
5. **Single origin**
   - The frontend and API are served from one HTTPS origin (no separate API
     port). Passkeys and the secure cookie both require this.

## 3. Phone app

- **Progressive Web App:** a web manifest, icons and standalone display mode.
  On iPhone it is installed with Safari's Add to Home Screen from the private
  HTTPS address.
- **The service worker caches only the app shell** (code and assets). API
  responses are network-only, so no financial data is stored on the phone.
- Passkeys work in the installed app (Face ID).
- Later, optional: Web Push (iOS 16.4+), for example for low-balance alerts.

## 4. Rollout

1. **Mac (development):** sessions, passkeys, single origin, PWA and a working,
   tested Docker image. Every change gets tests, including security regression
   tests for session and login abuse.
2. **Desktop:** a step-by-step install guide (`docs/SERVER_SETUP.md`) covering
   OS, TPM unlock, Tailscale and ACLs, firewall, Docker, unattended upgrades and
   backups, plus idempotent setup scripts where practical.
3. **Cut-over:**
   - Copy the database with the app's WAL-safe backup routine.
   - Move secrets over Tailscale only.
   - Disable the Mac's scheduler jobs and wake schedule so bank sync and email
     never run twice.
   - Verify sync, the daily email and login from the iPhone.
4. **Backups:** a nightly encrypted backup to another device over Tailscale,
   30-day retention, and a documented restore that is actually tested once.

## Testing

- **Sessions:** cookie flags, idle and absolute expiry, sign-out-all, and
  rejecting a cross-origin state change.
- **Rate limiting:** the Nth failure is blocked and the cool-down releases it.
  Successful logins are unaffected.
- **Passkeys:** a registration and authentication round-trip using the
  library's test helpers. A passkey belonging to another user is refused.
  Disabling password login blocks password auth.
- **Audit and alerts:** events are written, and a new passkey triggers the
  email.
- **PWA:** the service worker never caches `/api` responses.
- **Deployment:** the Docker image builds and passes a smoke test. The restore
  procedure is exercised.

## Decisions made

- Private network (Tailscale) over a public tunnel or port forwarding.
- TPM auto-unlock over a passphrase on every boot.
- A PWA first, not a native app.
- Passwords stay available as a fallback until the user turns them off.
