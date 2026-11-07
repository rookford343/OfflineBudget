# Phone on the Home Network Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve OfflineBudget from the Mac to the owner's iPhone over trusted HTTPS on home Wi-Fi. It installs as a home-screen app, has phone layouts for Dashboard, Forecast, Recurring and Spending, and a "Plan a one-off" preview-then-commit flow.

**Architecture:**
- **One origin.** A single uvicorn process terminates TLS with a certificate from a private CA. It serves the API under `/api` and the built React app from `frontend/dist`.
- **One production instance.** It runs under launchd and is the only process with the scheduler on. Dev runs are loopback-only, against a dev database.
- **Phone layouts** respond to width with Tailwind breakpoints.
- **Plan a one-off** reuses `ScenarioProposal` and `compute_budget_snapshot`, so there is no new money math.

**Tech Stack:**
- Backend: FastAPI, uvicorn, SQLAlchemy, pytest (uv).
- Frontend: React 19, Vite 8, Tailwind 3, recharts, axios, react-query; `bun test` for pure frontend logic.
- TLS: `openssl`. Process management: macOS `launchd`.

**Spec:** `docs/superpowers/specs/2026-11-07-phone-on-home-network-design.md` (approved 2026-11-07). Executors read both.

## Global Constraints

- **No new third-party dependency** (Python or JS) without the owner's review and approval. Use `openssl`, uvicorn's own TLS, FastAPI/Starlette built-ins, a hand-written service worker, and `bun test` (built into bun).
- **Tooling:**
  - uv only: `uv run --locked ...`. Lint with `uv run --locked ruff check .` (Bandit `S` + `F`). Never silence a finding without a same-line reason.
  - bun only, never npm/npx. The frontend gate is `bunx vite build`, not `tsc -b`.
- **Security fixes:** every one gets a test in `backend/tests/test_security_regressions.py`, and its module docstring list is updated.
- **Pre-push** (audit, CodeQL, tests, coverage floor in `backend/.coveragerc`) passes with no bypass. Never lower the floor.
- **Commits** go directly to `main`. Messages describe app behaviour, never real balances, amounts or dates. End each with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Live database:** back up with `backup_database()` (`backend/services/db_backup.py`), never `cp`, before anything that migrates it. Live data migrations need the owner's explicit OK.
- **Hostname:** `df-macbookpro16.local` (the Mac's current `LocalHostName`, `DF-MacBookPro16`). Fallback if Task 1 fails: `budget.thedigitaltrailhead.com`, resolved on the LAN only. The owner decides how before work continues.
- **The production HTTPS listener is the only socket bound to the LAN.** Dev uvicorn and Vite bind `127.0.0.1`.
- **No API response is cached** by the service worker or browser storage. The only thing stored besides the app shell is the existing auth token in `localStorage`.
- **Hide balances:** every new money figure on screen goes through the existing `maskIfHidden(balancesHidden, ...)`.
- **The desktop layout at ≥ 1024px (`lg`) is unchanged.**

## Review Focus

1. **The live app breaks mid-build.** The live backend runs `--reload` and the Vite dev server runs HMR from this working tree, so every implementer edit reaches the owner's real app and data. Task 0 freezes the live app before any code change. Reviewers confirm no task restarts it.
2. **Static-file path traversal through the SPA fallback** (`/../.env`, `/%2e%2e/data/budget.db`, `/assets/../../backend/config.py`) must be 404, never file contents. The test goes in Task 3.
3. **An unknown `/api/...` path** must return JSON 404, not `index.html`. Otherwise a typo'd endpoint looks like "success" to axios. The test goes in Task 3.
4. **A one-off naming another user's card or account** (`card_id`/`account_id` not owned) must be 404 on both preview and create. The existing create endpoint doesn't check ownership today. The test goes in Task 8.
5. **The phone loses the Mac** (asleep, rebooted, off Wi-Fi). The installed app shows "Can't reach your Mac" with a retry, not a blank page or stale numbers. The test goes in Task 6.

---

### Task 0: Freeze the live app (controller with the owner, no code)

The live backend (`uvicorn ... --reload`, PID on :8000) and Vite (`:5173`) run from this working tree, so later tasks would hot-reload into real use. Run this before Task 2 touches code, with the owner's OK.

- [ ] **Step 1:** Back up the database.
  - Run: `uv run --locked python -c "from backend.services.db_backup import backup_database; print(backup_database('data/budget.db', 'data/backups/pre-phone-$(date +%Y%m%d%H%M).db'))"`
  - Expected: a printed path. The file exists and is non-empty.
- [ ] **Step 2:** Create a frozen snapshot of the current code.
  - Run: `git worktree add ../OfflineBudget-live HEAD`
  - Copy `.env` into it, with `DATABASE_URL=sqlite:////Users/danford/Programming/Dev/OfflineBudget/data/budget.db` (absolute, the real DB).
  - Run `uv sync --locked` in it, and `bun install --frozen-lockfile && bunx vite build` in its `frontend/`.
- [ ] **Step 3:** Stop the current backend and Vite, then start the snapshot in their place.
  - Backend: `uv run --locked uvicorn backend.main:app --host 0.0.0.0 --port 8000` (no `--reload`).
  - Frontend: `bunx vite preview --host --port 5173`.
  - Expected: the owner's app works exactly as before (same URLs, same plain HTTP as today). The scheduler runs once, in the snapshot.
- [ ] **Step 4:** Record the PIDs and the start/stop commands in the session notes for Task 5's cutover.

### Task 1: Passkey and hostname spike (throwaway, gate)

**Files:**
- Create (kept): `scripts/tls/make-ca.sh`, `scripts/tls/issue-cert.sh`, `docs/ios-lessons.md`.
- Spike page and server: scratchpad only, never committed.

**Interfaces:**
- Produces:
  - `scripts/tls/make-ca.sh <out_dir>` writes `ca.key` (AES-256 encrypted with a passphrase prompt, mode 600) and `ca.crt`. RSA 4096 or P-256, 10-year validity, `basicConstraints=critical,CA:TRUE`, `keyUsage=critical,keyCertSign,cRLSign`.
  - `scripts/tls/issue-cert.sh <ca_dir> <hostname> <out_dir>` writes `server.key` (600) and `server.crt`, signed by the CA. Validity 825 days, `subjectAltName=DNS:<hostname>`, `extendedKeyUsage=serverAuth`. It prints the expiry date.
  - Default CA dir: `~/.offlinebudget-ca/` (outside the repo). Default cert dir: `ssl/` (already gitignored; verify with `git check-ignore ssl/server.key`).

The CA is independent of the hostname, so the real CA is made here once. A failed spike only means reissuing the server certificate. This saves the owner a second profile install.

- [ ] **Step 1:** Write both scripts. They refuse to overwrite existing keys and use `set -euo pipefail`.
- [ ] **Step 2:** Run `scripts/tls/make-ca.sh ~/.offlinebudget-ca`, then `scripts/tls/issue-cert.sh ~/.offlinebudget-ca df-macbookpro16.local ssl`.
  - Check: `openssl verify -CAfile ~/.offlinebudget-ca/ca.crt ssl/server.crt` prints `OK`.
  - Check: `openssl x509 -in ssl/server.crt -noout -ext subjectAltName` shows the hostname.
- [ ] **Step 3:** In the scratchpad, write a single-file spike: a page served over HTTPS on 443 with `ssl/server.*`. It has two buttons that call `navigator.credentials.create` and then `navigator.credentials.get`, with `rp.id = "df-macbookpro16.local"`, `userVerification: "required"` and a random challenge. It prints success or the exact error. Use `bun` with `Bun.serve({ tls })` (TypeScript), so there's no dependency.
- [ ] **Step 4 (owner):**
  - AirDrop `ca.crt` to the iPhone and install the profile.
  - Enable it under Settings → General → About → Certificate Trust Settings.
  - Open `https://df-macbookpro16.local/` in Safari, then again after Add to Home Screen. Tap both buttons each time.
  - Expected: no certificate warning. Create and get both succeed with Face ID in Safari and in the home-screen app.
- [ ] **Step 5:** Record the outcome (both contexts, exact errors) in `docs/ios-lessons.md` under "Passkeys on .local". Delete the spike passkey from the phone (Settings → Passwords).
- [ ] **Step 6: Gate.** If either context fails, stop. Report to the owner with the fallback `budget.thedigitaltrailhead.com` and ask how it should resolve on the LAN. Do not continue to Task 3's hostname-dependent steps.
- [ ] **Step 7:** Commit the scripts and `docs/ios-lessons.md`.

### Task 2: Scheduler gate and run-mode settings

**Files:**
- Modify: `backend/config.py` (`Settings`), `backend/main.py` (`_lifespan`, `FastAPI(...)` docs args).
- Test: `backend/tests/test_security_regressions.py`.

**Interfaces:**
- Produces these settings, read by Tasks 3 and 4:
  - `Settings.SCHEDULER_ENABLED: bool = False`.
  - `Settings.FRONTEND_DIST_DIR: str | None = None`.
  - `Settings.API_DOCS_ENABLED: bool = False`.
  - `Settings.LIVE_DATABASE_PATH: str = "data/budget.db"`.
- `_lifespan` calls `_scheduler.start()` only when `settings.SCHEDULER_ENABLED`.
- Docs live at `/api/docs` and `/api/redoc`, only when `API_DOCS_ENABLED`; otherwise `docs_url=None, redoc_url=None, openapi_url=None`.

- [ ] **Step 1: Write the failing tests.**
  - `test_scheduler__default_settings__does_not_start`: `Settings(_env_file=None).SCHEDULER_ENABLED is False`. Then run the lifespan with `TestClient(app)` and `settings.SCHEDULER_ENABLED=False` via monkeypatch, and assert `backend.main._scheduler.running is False`.
  - `test_api_docs__default__not_served`: with default settings, `GET /api/docs`, `/docs` and `/openapi.json` are all 404.
- [ ] **Step 2:** Run `uv run --locked python -m pytest backend/tests/test_security_regressions.py -k "scheduler or api_docs" -v`. Expected: FAIL.
- [ ] **Step 3:** Implement. App construction reads `settings` at import, so the docs test builds settings first. Use an `_build_app()` factory only if it's needed to test that.
- [ ] **Step 4:** Run the same command. Expected: PASS. Then run the full suite: `uv run --locked python -m pytest -q`.
- [ ] **Step 5:** Update the module docstring list and commit.

### Task 3: Single origin: `/api` prefix, SPA serving, security headers, CORS

**Files:**
- Modify: `backend/main.py` (router includes, `/health`, CORS).
- Create: `backend/web.py` (static and SPA mount plus headers middleware).
- Modify: the backend tests that import `backend.main.app` and call bare paths. Find them with `grep -rln "backend.main" backend/tests`; there are 7. Prefix their paths with `/api`.
- Modify: `frontend/src/api/client.ts` (`DEFAULT_API = "/api"`), `frontend/vite.config.ts` (dev `server.host: "127.0.0.1"`, `server.proxy["/api"] = "http://127.0.0.1:8000"`, remove the `https` block).
- Test: `backend/tests/test_web_single_origin.py`, `backend/tests/test_security_regressions.py`.

**Interfaces:**
- Consumes: `settings.FRONTEND_DIST_DIR` (Task 2).
- Produces:
  - Every router is included under one `APIRouter(prefix="/api")`; health is at `GET /api/health`.
  - `backend/web.py: mount_frontend(app: FastAPI, dist_dir: str) -> None`. It serves files under `dist_dir` and falls back to `index.html` for non-`/api` GETs. It's called from `main.py` only when `FRONTEND_DIST_DIR` is set.
  - `backend/web.py: SecurityHeadersMiddleware` (Starlette `BaseHTTPMiddleware` or pure ASGI) adds the headers below to every response.

Headers, exact values:
- `Strict-Transport-Security: max-age=31536000`
- `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; manifest-src 'self'; worker-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'`
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: no-referrer`

`style-src 'unsafe-inline'` is there because recharts and React set inline styles. Verify against the built app in Task 5; tighten if it isn't needed.

CORS: `allow_origins` = `settings.allowed_origins_list`. Production sets this to exactly `https://df-macbookpro16.local` (Task 5). Remove the `"*"` default by changing `ALLOWED_ORIGINS` to `"http://127.0.0.1:5173"`.

- [ ] **Step 1: Write the failing tests** in `test_web_single_origin.py`, using a temp `dist/` holding `index.html` (contents `SPA`) and `assets/app.js`:
  - `test_api_routes_live_under_api`: `GET /api/health` is 200 JSON. `GET /health` is not JSON health.
  - `test_spa_fallback_serves_index_for_client_routes`: `GET /dashboard` and `GET /forecast` return 200 with `SPA`.
  - `test_unknown_api_path_is_json_404`: `GET /api/nope` is 404 with `application/json` and its body isn't `SPA`.
  - `test_static_asset_served`: `GET /assets/app.js` is 200.
  - `test_security_headers_on_api_and_static`: all four headers above, exact values, on `/api/health` and `/dashboard`.
- [ ] **Step 2: Write the failing security regression tests:**
  - `test_spa_static__path_traversal__is_404`: parametrize over `/../.env`, `/%2e%2e/%2e%2e/data/budget.db`, `/assets/../../backend/config.py` and `/..%2fpyproject.toml`. Each returns 404 or the `SPA` index, and never contains `JWT_SECRET`, `SQLite format`, `class Settings` or `[project]`.
  - `test_cors__foreign_origin__gets_no_allow_origin`: an `OPTIONS /api/health` preflight with `Origin: https://evil.example` and `Access-Control-Request-Method: GET` gets no `access-control-allow-origin` header.
- [ ] **Step 3:** Run `uv run --locked python -m pytest backend/tests/test_web_single_origin.py backend/tests/test_security_regressions.py -v`. Expected: the new tests FAIL.
- [ ] **Step 4:** Implement. Resolve each requested file with `Path(dist_dir, rel).resolve()` and require `is_relative_to(Path(dist_dir).resolve())`. Never `os.path.join` an unchecked path.
- [ ] **Step 5:** Update the 7 tests that use `backend.main` to `/api/...` paths. Run the full suite `uv run --locked python -m pytest -q`. Expected: PASS.
- [ ] **Step 6:** Run `cd frontend && bunx vite build`. Expected: success. Then `grep -rn ":8000" frontend/src` returns nothing.
- [ ] **Step 7:** Commit.

### Task 4: Production runner, dev runner guard, launchd, deploy script

**Files:**
- Create: `scripts/run-production.sh`, `scripts/deploy.sh`, `scripts/launchd/com.offlinebudget.server.plist.template`.
- Modify: `scripts/start.sh` (dev only).
- Delete: `scripts/setup-ssl.sh`, which `scripts/tls/*` replaces.
- Test: `backend/tests/test_run_scripts.py`.

**Interfaces:**
- `scripts/run-production.sh [--check]`:
  - Requires `ssl/server.crt` and `ssl/server.key` (it exits 1 with a message if either is missing) and `frontend/dist/index.html`.
  - Then: `exec uv run --locked uvicorn backend.main:app --host 0.0.0.0 --port 443 --ssl-certfile ssl/server.crt --ssl-keyfile ssl/server.key --proxy-headers=false`.
  - Env: `SCHEDULER_ENABLED=true`, `FRONTEND_DIST_DIR=frontend/dist`.
  - Never `--reload`, never a plain-HTTP port. `--check` prints the resolved command and exits 0 without starting.
  - If binding 443 as a normal user fails on this macOS version, stop and report. Don't add `sudo` and don't switch ports on your own.
- `scripts/start.sh [--check]` (dev):
  - Uvicorn on `--host 127.0.0.1 --port 8000 --reload`, Vite on `127.0.0.1`, with `SCHEDULER_ENABLED=false`.
  - Uses `DATABASE_URL` from env, defaulting to `sqlite:///./data/dev.db`.
  - It refuses (exit 1, message names the file) if the resolved DB path is the live DB `data/budget.db`.
  - If `data/dev.db` is missing, it creates it from the live DB with `backup_database()` and says so.
- Plist template:
  - Label `com.offlinebudget.server`.
  - `ProgramArguments` = `/bin/bash <repo>/scripts/run-production.sh`, `WorkingDirectory` = `<repo>`.
  - `RunAtLoad` true, `KeepAlive` true.
  - `StandardOutPath`/`StandardErrorPath` = `<repo>/data/logs/server.{out,err}.log`.
  - `<repo>` is a placeholder filled in by the install step in `docs/SETUP.md`.
- `scripts/deploy.sh`:
  - `bun install --frozen-lockfile && bunx vite build` in `frontend/`.
  - Back up the DB with `backup_database()` to `data/backups/pre-deploy-<timestamp>.db`.
  - `launchctl kickstart -k gui/$(id -u)/com.offlinebudget.server`.
  - Poll `https://df-macbookpro16.local/api/health` with `curl --cacert ~/.offlinebudget-ca/ca.crt` until it returns 200 (30s timeout), and exit non-zero on failure.

- [ ] **Step 1: Write the failing tests** in `test_run_scripts.py` (subprocess, `--check` mode, temp copies of `ssl/` and `dist/` as needed):
  - `test_production__no_cert__refuses`: exit 1, and stderr mentions `ssl/server.crt`.
  - `test_production__check__https_only_no_reload`: the printed command contains `--ssl-certfile` and `--port 443`, and contains neither `--reload` nor `--port 8000`.
  - `test_dev__live_db__refuses`: with `DATABASE_URL=sqlite:///./data/budget.db`, `start.sh --check` exits 1.
  - `test_dev__check__loopback_and_scheduler_off`: the printed commands bind `127.0.0.1` and set `SCHEDULER_ENABLED=false`. `0.0.0.0` is absent.
- [ ] **Step 2:** Run `uv run --locked python -m pytest backend/tests/test_run_scripts.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement the scripts and the template. Use `set -euo pipefail`.
- [ ] **Step 4:** Run the same command. Expected: PASS. Also run `bash -n` on each script.
- [ ] **Step 5:** Write `docs/SETUP.md` section "Phone on home Wi-Fi":
  - CA creation, server certificate issuing, iPhone profile install and trust.
  - Plist install (`sed` the template into `~/Library/LaunchAgents/`, then `launchctl bootstrap gui/$(id -u) ...`).
  - Firewall: `sudo /usr/libexec/ApplicationFirewall/socketfilterfw --setglobalstate on --setstealthmode on`, and allow the uv-managed Python.
  - Deploy, and certificate renewal (expiry date printed by `issue-cert.sh`; reissue with the same CA).
  - After a reboot the server starts at login (accepted limitation).
  - Dev runs use `data/dev.db`.
- [ ] **Step 6:** Commit.

### Task 5: Cutover (controller with the owner; operational, approval required)

- [ ] **Step 1:** Show the owner the pending schema changes (`upgrade_schema` will run at first production start). Get an explicit OK. Then back up with `backup_database()`.
- [ ] **Step 2:** Set these in the main repo's `.env`:
  - `ALLOWED_ORIGINS=https://df-macbookpro16.local`
  - `FRONTEND_URL=https://df-macbookpro16.local`
- [ ] **Step 3:** Stop the Task 0 snapshot processes, so exactly one scheduler runs.
- [ ] **Step 4:** Install and bootstrap the LaunchAgent per `docs/SETUP.md`, then run `scripts/deploy.sh`. Expected: health is 200 over HTTPS.
- [ ] **Step 5:** Turn on the firewall per `docs/SETUP.md`.
- [ ] **Step 6:** Verify from another LAN device (the iPhone, or `curl` from any other machine):
  - `http://df-macbookpro16.local/` is refused or times out.
  - `:8000` and `:5173` are refused or time out.
  - `https://df-macbookpro16.local/` loads with no warning.
  - On the Mac, `lsof -nP -iTCP -sTCP:LISTEN` shows only `*:443` for the app. Any dev process shows only `127.0.0.1`.
- [ ] **Step 7:** Check the built app in real Chrome with the Interceptor skill: no CSP violations in the console. Tighten `style-src` if possible.
- [ ] **Step 8:** The next morning, confirm bank sync and the daily email ran once each (logs and the inbox). Then remove the `../OfflineBudget-live` worktree.

### Task 6: Installable app shell (PWA) and "Can't reach your Mac"

**Files:**
- Create:
  - `frontend/public/manifest.webmanifest`
  - `frontend/public/sw.js`
  - `frontend/public/sw-policy.js`
  - `frontend/public/icons/icon-180.png`, `icon-192.png`, `icon-512.png`, `icon-512-maskable.png`
  - `frontend/src/lib/registerServiceWorker.ts`
  - `frontend/src/components/ConnectionBanner.tsx`
  - `frontend/src/lib/connection.ts`
- Modify: `frontend/index.html`, `frontend/src/main.tsx`, `frontend/src/api/client.ts`, `frontend/src/components/Layout.tsx`, `frontend/package.json` (`"test": "bun test"`), `.githooks/pre-push` (run `bun test` in `frontend/` after install).
- Modify: `backend/web.py`, so `sw.js` and `manifest.webmanifest` are served with `Cache-Control: no-cache`.
- Test: `frontend/src/lib/swPolicy.test.ts`, `frontend/src/lib/connection.test.ts`, `backend/tests/test_web_single_origin.py`.

**Interfaces:**
- `sw-policy.js` is a classic script that defines `self.cacheStrategy = (url: URL, scopeOrigin: string) => "app-shell" | "network-only"`.
  - It returns `"app-shell"` only for same-origin GETs of `/`, `/index.html`, `/assets/*`, `/icons/*` and `/manifest.webmanifest`.
  - Everything else is `"network-only"`: `/api/*`, cross-origin, and query-bearing URLs on `/api`.
- `sw.js` does `importScripts("/sw-policy.js")`.
  - It caches the app shell at install and on fetch (stale-while-revalidate) under cache name `ob-shell-v<build hash or date>`.
  - It never calls `cache.put` for `"network-only"`.
  - Navigations to client routes fall back to the cached `/index.html` when offline.
  - It deletes old `ob-shell-*` caches on activate.
- `registerServiceWorker(): void` registers `/sw.js` only when `import.meta.env.PROD`.
- `connection.ts` exports `isUnreachable(error: unknown): boolean`. It is true for axios errors with no `response` (network failure or timeout), and false for any HTTP status.
- `ConnectionBanner` shows "Can't reach your Mac. It may be asleep or off this Wi-Fi." with a Retry button, which calls `queryClient.refetchQueries()`. It shows while the last request was unreachable and hides on the next success. It's driven by an axios response interceptor in `client.ts`. While it shows, the page keeps no figures from an earlier load on screen: react-query data is cleared for failed queries.
- Manifest:
  - `name: "OfflineBudget"`, `short_name: "Budget"`
  - `start_url: "/dashboard"`, `scope: "/"`, `display: "standalone"`
  - `theme_color`/`background_color` matching the app's current indigo/white
  - the icons above
- `index.html`:
  - `<title>OfflineBudget</title>`
  - `viewport` adds `viewport-fit=cover`
  - `<link rel="manifest">`, `apple-touch-icon` (180), `apple-mobile-web-app-capable`/`mobile-web-app-capable`
  - `apple-mobile-web-app-status-bar-style: default`
- Icons are made from `frontend/public/favicon.svg` with tools already on the Mac (e.g. `qlmanage -t -s 512 -o`, then `sips -z`). No new dependency.

- [ ] **Step 1: Write the failing tests.**
  - `swPolicy.test.ts` (set `globalThis.self = globalThis`, then `await import("../../public/sw-policy.js")`):
    - `/api/spending/budget-snapshot?account_id=1` → `"network-only"`.
    - `/api/health` → `"network-only"`.
    - `/assets/index-abc.js` → `"app-shell"`.
    - `/` → `"app-shell"`.
    - `https://evil.example/assets/x.js` → `"network-only"`.
    - `/dashboard` → `"network-only"` (navigations use the index fallback, not their own cache entry).
  - `connection.test.ts`:
    - `isUnreachable({ isAxiosError: true, response: undefined })` → `true`.
    - With `response: { status: 500 }` → `false`.
    - With `response: { status: 401 }` → `false`.
  - Backend: `test_sw_and_manifest_not_cached`: `/sw.js` and `/manifest.webmanifest` have `Cache-Control: no-cache`.
- [ ] **Step 2:** Run `cd frontend && bun test` and `uv run --locked python -m pytest backend/tests/test_web_single_origin.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the same commands. Expected: PASS. Also `bunx vite build`.
- [ ] **Step 5:** Deploy (`scripts/deploy.sh`), then verify:
  - On the iPhone: Add to Home Screen opens full-screen at Dashboard.
  - In Interceptor, Application → Cache Storage holds no `/api` entries after browsing all four pages.
  - With the server stopped (`launchctl kill TERM ...`), the installed app shows the banner, not a blank page or old numbers.
  - Note the iOS findings in `docs/ios-lessons.md`.
- [ ] **Step 6:** Update `docs/PRIVACY.md`: the phone stores the app code and the login token only. Commit.

### Task 7: Phone navigation and Dashboard phone layout

**Files:**
- Modify: `frontend/src/components/Layout.tsx`, `frontend/src/lib/navItems.ts`, `frontend/src/pages/Dashboard.tsx`.
- Create:
  - `frontend/src/components/MoreSheet.tsx`
  - `frontend/src/components/phone/SafetyMarginHero.tsx`
  - `frontend/src/components/phone/SpendableTile.tsx`
  - `frontend/src/components/phone/UpcomingOneOffs.tsx`
  - `frontend/src/lib/freshness.ts`
- Test: `frontend/src/lib/freshness.test.ts`.

**Interfaces:**
- `navItems.ts`:
  - Add `DEFAULT_PHONE_PINS = ["/spending", "/forecast", "/recurring"]`.
  - When no pins are saved, the phone bar uses these.
  - The bar becomes `[DASHBOARD_ITEM (label "Home"), ...3 pinned, MORE]`, where `MORE` opens `MoreSheet`. That's a bottom sheet listing every `NAV_GROUPS` item plus Settings and Log out.
  - Settings leaves the bar (it's in More).
- Bar sizing:
  - The bar shows below `lg`, not below `md`, so an unfolded phone also gets it.
  - It adds `padding-bottom: env(safe-area-inset-bottom)`.
  - Items are ≥ 44px tall.
  - Page content gets bottom padding equal to the bar height.
- `freshness.ts` exports `summarizePending(cards: { is_active?: boolean; pending_effective: string | number | null }[]): { count: number; total: number }`. It counts cards with a non-zero `pending_effective` and sums them; inactive cards are ignored.
  - The figure is per card, not per charge, so the line reads "Includes pending charges on N card(s) ($X)". This is the spec's "N pending card charges" made honest for the data that exists.
- `SafetyMarginHero` props: `{ weekly: number; month: number; perDay: number; pending: { count: number; total: number }; lastSync: Date | null; hidden: boolean }`.
  - Headline: "Safety Margin (this week)" with `weekly`, large. This is the same figure and label the desktop tile leads with.
  - Under it: "$<month> this month · $<perDay>/day".
  - Then the pending line and "Last bank sync: <relative time>". The sync time comes from the same source `BankSyncStatusLine` uses.
  - Red when negative, the existing amber otherwise.
- `SpendableTile`: Spendable this week (`left_to_spend_weekly`) and today (`spendable_today`), with on-pace colouring as on desktop.
- `UpcomingOneOffs`: the next 5 future planned outflows (existing planned-expenses list), as name · date · amount.
- `Dashboard.tsx` below `lg` renders the phone layout. At `lg` and up it renders the existing layout untouched.
  - Below `sm` (640px), one column: `SafetyMarginHero`, `SpendableTile`, a "+ Plan a one-off" button (Task 8 wires it; render it disabled until then), then the existing risk banner and bills-to-confirm blocks.
  - From `sm` to below `lg`, two columns. Left: hero, spendable, button. Right: the existing forecast `AreaChart` (fluid `ResponsiveContainer`, height 220), `RecentTransactions` (pending marked as today), `UpcomingOneOffs`.
  - Mockup reference: `.superpowers/brainstorm/26380-1794074150/content/phone-flows-v2.html` (local, gitignored).

- [ ] **Step 1: Write the failing test** `freshness.test.ts`:
  - `summarizePending([{pending_effective:"86.00"},{pending_effective:"0"},{pending_effective:null},{is_active:false,pending_effective:"10"}])` → `{count:1,total:86}`.
  - `summarizePending([])` → `{count:0,total:0}`.
- [ ] **Step 2:** Run `cd frontend && bun test src/lib/freshness.test.ts`. Expected: FAIL.
- [ ] **Step 3:** Implement `freshness.ts`, then the components, nav and Dashboard branch.
- [ ] **Step 4:** Run `bun test` and `bunx vite build`. Expected: PASS and success.
- [ ] **Step 5:** Verify with Interceptor at 390×844, 430×932, 700×900 and 1280×800:
  - No page-level horizontal scroll.
  - The hero is first below 1024px.
  - The chart shows only at ≥ 640px in the phone layout.
  - The desktop layout at 1280 is unchanged (compare a screenshot taken before the change).
  - Hide balances masks every new figure.
- [ ] **Step 6:** Deploy. The owner checks folded and unfolded on the Duo and reports the two CSS widths (`window.innerWidth`, shown temporarily in More → About). Record them in `docs/ios-lessons.md`. Commit.

### Task 8: Plan a one-off (preview, then commit)

**Files:**
- Create: `backend/services/one_off_preview.py`.
- Modify:
  - `backend/routers/planned_expenses.py` (add `POST /preview`, and an ownership check on create and patch)
  - `backend/schemas.py` (`OneOffPreviewOut`)
- Create (frontend):
  - `frontend/src/components/phone/PlanOneOffSheet.tsx`
  - `frontend/src/lib/useDebouncedValue.ts`
- Modify (frontend): `frontend/src/pages/Dashboard.tsx` (wire the button; it's also shown on desktop next to the existing snapshot).
- Test: `backend/tests/test_one_off_preview.py`, `backend/tests/test_security_regressions.py`.

**Interfaces:**
- `one_off_preview.preview_one_off(db: Session, user: models.User, account_id: int, draft: schemas.PlannedExpenseCreate) -> schemas.OneOffPreviewOut`.
  - Builds one transient `models.PlannedExpense(id=-1, user_id=user.id, ...)` from `draft`, never `db.add`ed.
  - Wraps it in `ScenarioProposal(expenses=(pe,))` (`backend/services/forecast_engine.py`).
  - Calls `compute_budget_snapshot(db, user, account_id)` and `compute_budget_snapshot(db, user, account_id, proposal=proposal)`.
  - For a card draft, also calls `card_payment_plan(db, user, account, today, draft.expected_date + 70 days, include_unbilled_card_bills=True, proposal=...)` with and without the proposal. It takes the first payment for `draft.card_id` with `due >= draft.expected_date`.
  - It ends with `db.rollback()` if `db.new` or `db.dirty` is non-empty, and logs a warning. That would be a bug. The test asserts it never happens.
- `schemas.OneOffPreviewOut`:
  - `safety_margin_weekly: BeforeAfter`
  - `safety_margin: BeforeAfter`
  - `card_payment: CardPaymentBeforeAfter | None`
  - `BeforeAfter = {before: Decimal, after: Decimal}`
  - `CardPaymentBeforeAfter = {card_id: int, due: date, before: Decimal, after: Decimal}`
- `POST /api/planned-expenses/preview?account_id=<int>`: body `PlannedExpenseCreate`, returns `OneOffPreviewOut`.
- Ownership helper `_require_owned(db, user, *, account_id, card_id, funding_account_id) -> None` raises `HTTPException(404, "Not found")` for any non-null id the user doesn't own. It's used by preview, create and patch.

**Spendable this week is not previewed.** `compute_budget_snapshot` deliberately keeps proposals out of its flat monthly aggregates (its docstring), so `left_to_spend_weekly` would not move in a preview but would after commit. Showing it would be a preview that lies. The sheet shows Safety Margin (headline: this week, before → after), Safety Margin this month, and the card payment line. This is a narrowing of the spec, flagged to the owner.

- [ ] **Step 1: Write the failing tests** in `test_one_off_preview.py`. Seed a user, a checking account with a balance, a card with a statement cycle, and a recurring bill, mirroring the fixtures in `test_planned_expense_card_routing.py`.
  - `test_preview_writes_nothing`: the `planned_expenses` row count and `db.new`/`db.dirty` are unchanged after `POST /api/planned-expenses/preview`.
  - `test_preview_matches_commit__checking`: the draft `{name:"Trip", amount:"600.00", expected_date:<today+20>, account_id:checking}`. `after` for `safety_margin_weekly` and `safety_margin` equals `compute_budget_snapshot` after `POST /api/planned-expenses` with the same body. `before` equals the snapshot before.
  - `test_preview_matches_commit__card`: the same, with `card_id` set. Also `card_payment.after - card_payment.before == Decimal("600.00")`, and it matches `card_payment_plan` after commit.
  - `test_cancel_leaves_no_trace`: preview twice, commit nothing. The row count is unchanged and the snapshot equals the baseline.
- [ ] **Step 2: Write the failing security regression tests:**
  - `test_planned_expense__other_users_card__is_404`: preview, create and patch with another user's `card_id` each return 404, and no row is written.
  - `test_planned_expense__other_users_account__is_404`: the same for `account_id` and `funding_account_id`.
- [ ] **Step 3:** Run `uv run --locked python -m pytest backend/tests/test_one_off_preview.py backend/tests/test_security_regressions.py -v`. Expected: FAIL.
- [ ] **Step 4:** Read `docs/architecture.md` (rows "Safety Margin", "Card payment amount", "Pending charges"), then implement the service, schema, route and ownership helper.
- [ ] **Step 5:** Run the same command, then the full suite. Expected: PASS.
- [ ] **Step 6:** Build `PlanOneOffSheet`:
  - A bottom sheet below `lg`, a dialog at `lg`+ (existing `@radix-ui/react-dialog`).
  - Fields: What, Amount, When, and Pay with. Pay with is a select of the user's checking accounts and active cards, card first by default, because the owner usually puts larger one-offs on a card.
  - It requests a preview 300ms after the last edit (`useDebouncedValue`), only when amount > 0 and date is set.
  - It shows a headline Safety Margin (this week) as `before → after` (red if after < 0), "this month" before → after, and for a card, "<card> payment due <date>: +$X".
  - **Add to plan** posts to `/api/planned-expenses`, closes, and invalidates the snapshot, forecast and planned-expense queries. **Cancel** closes without a request. All figures are masked when hidden.
- [ ] **Step 7:** Run `bunx vite build`. Verify in Interceptor at 390px and 1280px:
  - The preview updates while typing.
  - After Add to plan, the Dashboard hero equals the preview's `after`.
  - Cancel adds nothing.
  - Delete the test one-off afterwards on the live data, with the owner present.
- [ ] **Step 8:** Deploy. Update `docs/USER_GUIDE.md` with phone use and Plan a one-off. Commit.

### Task 9: Forecast, Recurring and Spending phone layouts

**Files:**
- Modify: `frontend/src/pages/Forecast.tsx`, `frontend/src/pages/Recurring.tsx`, `frontend/src/pages/Spending.tsx`, and any component they render that overflows.
- Create: `frontend/src/components/phone/ScrollX.tsx` (`({ children }) =>` a wrapper with `overflow-x-auto` and `-mx-4 px-4`, for tables that must stay tabular).

**Interfaces:**
- No new data. This is layout only, below `lg`. At `lg`+ nothing changes.
- Rules:
  - No page-level horizontal scroll.
  - Charts use `ResponsiveContainer` with `width="100%"` and a fixed height of 220–260 below `sm`.
  - Wide tables go in `ScrollX` or become stacked rows (builder's call per table).
  - Toolbars and filters wrap.
  - Tap targets are ≥ 44px.

- [ ] **Step 1:** Take baseline Interceptor screenshots of each page at 390, 700 and 1280 px wide.
- [ ] **Step 2:** Fix Forecast, run `bunx vite build`, and re-check at 390 and 700 (no horizontal scroll, chart readable) and 1280 (unchanged). Commit.
- [ ] **Step 3:** Do the same for Recurring. Commit.
- [ ] **Step 4:** Do the same for Spending. The Sankey goes in `ScrollX` below `sm`. Commit.
- [ ] **Step 5:** Deploy. The owner checks all three on the Duo, folded and unfolded. Record in `docs/ios-lessons.md` what each page needed at each width and what the owner actually used, as input for the iOS app. Commit.
