# Phone access on the home network: design

Status: agreed in chat on 2026-11-07; builder check done; awaiting approval of this document.

This document narrows and re-orders
[2026-10-19-secure-remote-access-design.md](2026-10-19-secure-remote-access-design.md).
That design remains the long-term target. The order is now:

1. **This phase:** use the app from the iPhone on home Wi-Fi, served from the
   Mac, over HTTPS.
2. **Next phase (its own design later):** passwordless login (passkeys) and
   server-side sessions, from section 2 of the Oct 19 design.
3. **Later:** a dedicated server, then a native iOS app.

## Why

The owner wants three things from the phone:

- Check the **Safety Margin** (the "true line in the sand") and know whether
  it already counts recent card charges.
- Plan a future one-off expense with his wife in the moment, without going
  to the computer. They need to see what it does to their numbers first, and
  then commit it.
- Use the phone's two screen sizes. The owner has an "iPhone Duo"; this
  author doesn't know its screen dimensions. It has a folded (narrow) and an
  unfolded (wide) mode.

A native iOS app is planned later. What this phase teaches about layout and
use on a phone should carry over to it.

## Guiding principle: zero trust

The owner treats HTTPS and secure data transfer as always a priority, and
zero trust as a guiding principle. The home network is **not** trusted:

- Every connection is encrypted.
- Nothing listens on the network that doesn't have to.
- No financial data is stored on the phone.

## Goals

1. The app opens on the iPhone from home Wi-Fi at a stable HTTPS address the
   phone trusts. There is no certificate warning and no click-through.
2. The phone can install it to the home screen (Safari "Add to Home Screen")
   and it runs full-screen.
3. Dashboard, Forecast, Recurring and Spending get real phone layouts at both
   narrow and wide widths.
4. "Plan a one-off" lets the owner preview the effect on the Safety Margin,
   then commit.
5. A running lessons log for the future iOS app.

## Non-goals

- Access from outside the home network, by any route. This includes
  Tailscale, tunnels and port forwarding.
- Passkeys and session changes (next phase). Password login stays as it is,
  but now only over HTTPS.
- A dedicated server or Docker deployment (later phase).
- A native iOS app.
- Phone redesigns of the other pages (Credit Cards, Goals, Calendar, Net
  Worth, Wish List, Adventures, Transactions, Import, Budget, Tax, Settings).
  They stay reachable from a "More" menu and must not be unusable, but they
  get no dedicated layout.
- Web Push and notifications.
- Access for the owner's wife. She doesn't log in; her weekly email
  continues.

## Anti-goals (failure even if it "works")

- Any port on the network serving plain HTTP, or the API reachable on its own
  port.
- Financial data (API responses) cached on the phone by the service worker or
  any browser storage, other than the existing auth token.
- A second copy of money math for the phone. The preview must use the same
  Safety Margin calculation the Dashboard uses.
- Bank sync or the daily/weekly email running twice because two backend
  instances are up.
- The live database reachable from a `--reload` dev server. Today, a file save
  auto-migrates real data.
- A Tailscale (or any internet-reaching agent) install on the Mac. The owner
  rejected it: it runs 24/7, and a recent Tailscale vulnerability makes it
  risk he doesn't want on this machine.

## Current state (as found on 2026-11-07)

- `uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload` and the Vite
  dev server on `0.0.0.0:5173` are both listening on every interface, over
  plain HTTP. There is no `ssl/` folder.
- `scripts/setup-ssl.sh` makes a *self-signed* certificate keyed to the LAN
  IP. It needs a click-through, and an installed home-screen app on iOS can't
  click through.
- The frontend calls the API at `<same host>:8000`. Backend routers have no
  `/api` prefix, and their paths collide with frontend routes
  (`/forecast`, `/recurring`, ...).
- The auth token is a 7-day JWT kept in `localStorage`.
- APScheduler runs inside the backend process: bank sync, the daily email,
  the weekly digest and catch-up sweeps.
- `planned_expenses` (create/patch/delete/settle) already exists. The forecast
  already accepts a transient `proposal` built from a saved scenario
  (`/forecast/quarters-scenario`, `scenario_service.resolve_scenario`).
- `docker-compose.yml` exists but is not the live path.
- Pending card charges already feed the Safety Margin. Fresh `card_pending`
  (≤ 7 days old) goes into the card payment estimates the Safety Margin walk
  uses (`docs/architecture.md`, rows "Safety Margin", "Card payment amount",
  "Pending charges"). The freshness line only **surfaces** this. It is not new
  money math.
- Email links come from `FRONTEND_URL`, falling back to the first
  `ALLOWED_ORIGINS` entry. `cli/budget.py` and the scheduled jobs call
  services in-process, not over HTTP.

## Design

### 1. Network and HTTPS

- **Private certificate authority (CA)**, made with `openssl`, so there is no
  new tool to vet. It issues one server certificate for the Mac's stable
  hostname.
  - The CA private key lives outside the repo with `600` permissions, and
    should be passphrase-protected.
  - The server certificate stays within Apple's limit for user-installed roots
    (≤ 825 days). The setup doc records its expiry date and how to renew.
  - This replaces the current self-signed `setup-ssl.sh` flow.
- **Hostname:** a stable `.local` name served by the Mac's own Bonjour, not an
  IP. Builder picks the exact name. *My call:* the Mac's `LocalHostName`,
  set to something stable such as `budget`.
  - See the passkey risk in section 6. It may change this choice.
- **iPhone trust:** the CA's root certificate is installed on the phone once
  (profile install, then Settings → General → About → Certificate Trust
  Settings). This is documented step by step.
- **Single origin:**
  - One HTTPS listener serves both the built frontend and the API, which moves
    under `/api`.
  - Port 443 if practical, so the address needs no port. macOS lets ordinary
    users bind 443.
  - The frontend's `DEFAULT_API` becomes same-origin `/api`.
  - CORS shrinks to that one origin, or goes away.
  - *My call:* uvicorn terminates TLS itself, with no reverse proxy and so no
    new dependency.
    - The routers get a real `/api` prefix (one `APIRouter` or a mount).
    - FastAPI serves the built `dist/`, falling back to `index.html` for
      client-side routes.
    - Security headers come from a small middleware.
  - `FRONTEND_URL` is set to the new HTTPS address, so email links point at
    it.
  - On the phone the owner logs in once, after installing to the home screen.
    The installed app has its own storage. This is accepted.
- **Least exposure:**
  - The HTTPS listener is the only thing bound to the LAN.
  - Dev servers (Vite and any dev backend) bind to `127.0.0.1` only.
  - The macOS firewall is on in stealth mode and allows only that listener.
- **Security headers** on every response: HSTS, a strict
  Content-Security-Policy (no inline script, `connect-src 'self'`,
  `frame-ancestors 'none'`), `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: no-referrer`. The CSP matters more while the token is
  still in `localStorage`. *Accepted for this phase*; the next phase moves to
  an `HttpOnly` cookie.

### 2. The live instance on the Mac

- **Production mode:** the always-on backend runs without `--reload`, under a
  `launchd` LaunchAgent, serving the built frontend.
  - *My call:* native `launchd` on the Mac, not Docker. Docker is deferred to
    the server phase.
  - The existing wake-window agent stays as is.
- **Availability:**
  - The owner has set the Mac to stay awake while on power, so it is meant to
    be reachable at all times.
  - After a reboot, a LaunchAgent starts only once the owner logs in (FileVault
    needs that login anyway). *Accepted limitation*, documented in SETUP.
  - The phone shows a plain "can't reach the Mac" state, not a broken page.
- **Exactly one scheduler:**
  - Add a setting that turns the in-process scheduler off.
  - Only the production instance runs it.
  - Any dev instance runs with it off and against a separate dev database
    (e.g. a copy made with `backup_database()`, or the demo seed).
- **Deploy script:** build the frontend, take a `backup_database()` backup,
  then restart the agent. Startup migrations hit real data, so the backup comes
  first.
  - Live migrations still need the owner's explicit approval, per existing
    practice.
- `scripts/start.sh` is updated or split so a dev run can't accidentally bind
  to the LAN or start the scheduler against the live DB.

### 3. Installable phone app (PWA)

- Web manifest, icons, `display: standalone`, theme color, and iOS
  safe-area handling.
- The service worker caches **only the app shell** (built JS/CSS/icons).
  Everything under `/api` is network-only.
- The app works on a wide window and on a phone from the same build.

### 4. Phone layouts

Layout responds to **available width**, not to a device check, so it works on
both Duo modes and on any future phone.

- **Rules everywhere:**
  - No horizontal scrolling of the page; wide tables get their own scroll box
    or become stacked cards.
  - Touch targets at least 44pt.
  - Bottom tab bar on narrow widths: Home (Dashboard), Spending, Forecast,
    Recurring, More.
  - "Hide balances" keeps working everywhere (see the hidden-balance checks).
- **Dashboard, narrow** (mockup v2, `.superpowers/brainstorm/*/content/phone-flows-v2.html`),
  in this order:
  1. **Safety Margin** as the large headline number.
  2. Right under it, a freshness line: "Includes N pending card charges ($X)"
     and "Last bank sync: <time>".
  3. A secondary tile with Spendable this week and Spendable today.
  4. A "+ Plan a one-off" button.
- **Dashboard, wide:**
  - Two columns: the narrow content on the left; recent transactions
    (pending marked) and upcoming one-offs on the right.
  - The **forecast chart** is visible on the wide Dashboard (the owner asked
    for this).
- **Forecast, Recurring, Spending:** usable and readable at narrow width,
  with charts sized to the viewport. Builder chooses per-page layouts within
  the rules above.

### 5. Plan a one-off

- **Fields:**
  - What
  - Amount
  - Date
  - Pay with: any checking account or credit card. The owner usually puts
    larger one-offs on a card.
- **Live preview** while typing, with nothing saved:
  - Safety Margin before → after, as the headline.
  - The effect on the affected card's next payment, when paid by card.
  - Spendable this week before → after.
  - *My call:* all three numbers come from `compute_budget_snapshot` and
    `card_payment_plan`, run with the draft injected. No parallel formula.
- **Add to plan** creates a normal planned expense (existing
  `planned_expenses` create). **Cancel** discards. After commit, the Dashboard
  shows the same Safety Margin the preview showed.
- **How the preview is computed:**
  - It must run the same calculation as the Dashboard's Safety Margin, with
    the unsaved one-off injected as a transient item. It must not create or
    alter any rows.
  - The existing `proposal` mechanism is the likely place to hook in, but it
    currently needs a saved scenario. Builder decides how to pass an unsaved
    one, e.g. a preview endpoint that takes the draft in the request body.
  - Read `docs/architecture.md` first, per the repo rule for money
    calculations.

### 6. Risk to test first: passkeys and `.local`

The next phase needs passkeys bound to this hostname. WebAuthn may refuse a
`.local` name as a relying-party ID, or Safari on iOS may treat it
differently. Before building the rest of this phase, do a throwaway spike:
register and use a test passkey on the iPhone against the chosen hostname over
the private-CA HTTPS.

- **If it works:** keep the hostname.
- **If not:** pick a hostname that will work (e.g. a subdomain of a domain the
  owner controls, resolved only on the LAN) before anything depends on the
  name.
- **The owner's fallback name:** a subdomain of `thedigitaltrailhead.com`
  (e.g. `budget.thedigitaltrailhead.com`).
  - The domain currently hosts a WordPress site, which must not be disturbed.
  - The name resolves only on the LAN. The iPhone can't edit a hosts file,
    so this needs a local DNS override on the router or a small resolver.
  - The CA approach stays the same.
  - The exact resolution method is decided with the owner only if the spike
    fails.
- *My call on order:* this spike is the **first task**. It uses a throwaway
  certificate, so a failed result throws away almost nothing. If it fails,
  stop and bring the hostname decision back to the owner.
- Record the result in the iOS lessons log.

### 7. iOS lessons log

`docs/ios-lessons.md`, updated as work happens:

- What each screen needed at narrow and wide widths.
- What the owner actually taps.
- What iOS Safari/PWA did unexpectedly (certificate trust, safe areas,
  standalone quirks, the passkey spike).
- Anything that should shape the native app.

## Constraints

- The repo's security gates apply (CLAUDE.md):
  - uv only; ruff with Bandit `S`.
  - bun only, with exact pins and the 7-day cooldown.
  - The pre-push hook (audit, CodeQL, tests, coverage floor) passes with no
    bypass.
- **No new third-party dependency without review and approval.** That covers
  any PWA or service-worker helper library; a small hand-written service
  worker is preferred.
- Commits go to `main`. Commit messages describe behaviour, never real
  balances, amounts or dates.
- Back up with `backup_database()` (never a bare `cp`) before anything that
  migrates the live DB.
- Docs ship with it:
  - `docs/SETUP.md`: CA creation, iPhone trust steps, hostname, firewall,
    deploy script, certificate renewal.
  - `docs/USER_GUIDE.md`: phone use and Plan a one-off.
  - `docs/PRIVACY.md`: what the phone stores (app code and the auth token
    only).

## Testing

- **Security regression tests** (`backend/tests/test_security_regressions.py`):
  - The production config binds no plain-HTTP listener.
  - The API is served only under `/api` on the HTTPS origin.
  - Security headers are present.
  - A cross-origin request is refused.
  - A dev config cannot start the scheduler against the live DB path.
- **Service worker:** a test asserts `/api` responses are never cached.
- **Plan a one-off:**
  - Preview writes nothing to the DB.
  - Preview Safety Margin equals the Dashboard Safety Margin after commit, for
    both a card-paid and a checking-paid one-off.
  - Cancel leaves no trace.
- **Verification:**
  - Interceptor in real Chrome at narrow (~360–430px) and wide (~700–900px)
    widths for the four pages.
  - The owner checks on the actual iPhone in both modes, installed to the home
    screen, with no certificate warning.
  - From another device on the Wi-Fi, confirm that port 8000, port 5173 and
    plain HTTP are unreachable.

## Left to the builder

- Exact hostname (subject to the spike), port, and how the CA key is
  protected.
- How the preview endpoint takes an unsaved one-off.
- Per-page phone layouts for Forecast, Recurring and Spending within the
  rules above.
- Breakpoint values. Test both Duo modes once the owner reports their widths.
- How `start.sh` is split between dev and production.
