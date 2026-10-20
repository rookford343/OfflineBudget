# Secure Access, Plan 1: App Changes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the app safe to reach over a private network from anywhere. That means server-side cookie sessions, CSRF protection, per-account login limits, a security event log, passkeys, a single HTTPS origin, a phone-installable PWA, and a working Docker production build.

**Architecture:** A `user_sessions` table plus an `HttpOnly; Secure; SameSite=Strict` cookie replace the script-readable 7-day JWT. An Origin check guards every state-changing request. Passkeys use WebAuthn (`py_webauthn` / `@simplewebauthn/browser`) and create the same sessions. The frontend calls the API at `/api/...`, which nginx (production) and Vite (development) proxy to the backend, so there is one origin. A service worker caches only the app shell.

**Tech Stack:** FastAPI, SQLAlchemy 2, SQLite, Pydantic v2; React + TS + TanStack Query; bun; uv; Docker Compose + nginx.

**Spec:** `docs/superpowers/specs/2026-10-19-secure-remote-access-design.md` (Plan 2, which covers server setup, cut-over and backups, comes later.)

## Global Constraints

- Public repo: use made-up names and round figures only, and never real hostnames, tailnet names or emails.
- Python through uv only (`cd backend && uv run --locked python -m pytest -q`, `uv run --locked ruff check .`, `uv run --locked python -c "import backend.main, cli.budget"`). Frontend: bun/bunx only, never npm.
- Type-check baseline: `cd frontend && bunx tsc -b --force 2>&1 | grep -c "error TS"` is at most 37, with no new files in the list. `bunx vite build` and `bun test tests/` pass.
- **Third-party dependencies:** the controller reviews `py_webauthn` and `@simplewebauthn/browser` and gets the user's approval BEFORE Task 4 starts. Pin both exactly, and keep the 7-day uv `exclude-newer` cooldown.
- Every security behavior gets a test in `backend/tests/test_security_regressions.py`, with a line in its module docstring, and must be proven to fail without the fix.
- New routes that write through the user use `backend.dependencies.get_db` (the same session as user resolution).
- The live backend auto-reloads against real data, so never touch `data/`. The controller backs up the DB before Task 1.
- Commit on `main` and never push. Commit messages describe behavior only and end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## File map

| Area | Files |
|---|---|
| Sessions, CSRF | `backend/models.py` (UserSession), `backend/services/sessions.py` (new), `backend/dependencies.py`, `backend/routers/auth.py`, `backend/middleware.py`, `backend/config.py`, `backend/main.py`, `frontend/src/api/client.ts`, `frontend/src/store/auth.ts` |
| Single origin, Docker | `frontend/vite.config.ts`, `frontend/nginx.conf`, `frontend/Dockerfile.frontend`, `docker-compose.yml`, `frontend/src/api/client.ts` |
| Limits, events | `backend/services/rate_limiter.py`, `backend/models.py` (SecurityEvent), `backend/services/security_events.py` (new), `backend/routers/auth.py` |
| Passkeys | `backend/models.py` (WebAuthnCredential, WebAuthnChallenge, `users.password_login_disabled`), `backend/services/passkeys.py` (new), `backend/routers/passkeys.py` (new), `frontend/src/pages/settings/SecurityTab.tsx` (new), `frontend/src/pages/Login.tsx` |
| PWA | `frontend/public/manifest.webmanifest`, `frontend/public/icons/*`, `frontend/src/sw.ts` or `frontend/public/sw.js`, `frontend/src/lib/swRoutes.ts` (+ test), `frontend/index.html`, `frontend/src/main.tsx` |

---

### Task 1: Server-side sessions in a secure cookie, plus CSRF origin check

**Files:**
- Create: `backend/services/sessions.py`
- Modify: `backend/models.py`, `backend/database.py`, `backend/config.py`, `backend/dependencies.py`, `backend/routers/auth.py`, `backend/middleware.py`, `backend/main.py`, `frontend/src/api/client.ts`, `frontend/src/store/auth.ts`, plus every test that authenticates with `create_access_token`
- Test: `backend/tests/test_sessions.py`, `backend/tests/test_security_regressions.py`

**Interfaces:**
- **Produces:**
  - `sessions.create_session(db, user, *, user_agent: str | None, ip: str | None) -> str`, which returns the raw token. Only `sha256(token)` is stored.
  - `sessions.resolve_session(db, raw_token) -> models.User | None`. It enforces the idle and absolute expiry, and bumps `last_seen_at` at most once a minute.
  - `sessions.revoke_session(db, raw_token) -> None`
  - `sessions.revoke_all(db, user_id) -> int`
  - `SESSION_COOKIE = "ob_session"`
  - `sessions.set_session_cookie(response, raw_token)` and `sessions.clear_session_cookie(response)`
  - Settings:
    - `SESSION_IDLE_HOURS = 24`
    - `SESSION_MAX_DAYS = 30`
    - `COOKIE_SECURE: bool = True` (set False only in local HTTP dev, through `.env`)
    - `APP_ORIGINS: str` (comma list of exact allowed origins for the CSRF check; defaults to `ALLOWED_ORIGINS`)
  - Routes:
    - `POST /auth/login` sets the cookie and returns `{user}`. It still returns `access_token: null` so the schema stays valid; drop the field if nothing reads it.
    - `POST /auth/logout`
    - `POST /auth/sessions/revoke-all`
    - `GET /auth/sessions`, which lists this user's sessions: created, last_seen, user_agent, current flag.

- [ ] **Step 1: Model and migration.**
  - Add a `UserSession` model with these fields:
    - `id` (int PK)
    - `user_id` (FK users, ondelete CASCADE)
    - `token_hash` (String(64), unique, indexed)
    - `created_at`, `last_seen_at`, `expires_at` (DateTime)
    - `user_agent` (String(256), nullable)
    - `ip` (String(64), nullable)
  - Wire it into `User` with `cascade="all, delete-orphan"`. The new table comes from `create_all`.
- [ ] **Step 2: Write failing tests** in `backend/tests/test_sessions.py`:
  - Login sets a cookie named `ob_session` with `HttpOnly`, `Secure` (with the setting on), `SameSite=Strict` and `Path=/`.
  - The raw token is never stored: the DB holds only its sha256.
  - A request with the cookie resolves the user. A request without it gets 401.
  - Idle expiry: with `last_seen_at` more than 24h ago, the request gets 401 and the session row is deleted.
  - Absolute expiry: with `expires_at` in the past, the request gets 401.
  - Logout deletes the session and clears the cookie.
  - Revoke-all kills other sessions too.
  - A viewer can still read but not write (the existing rule, now through the cookie).
  - Use FastAPI's `TestClient` with the real dependencies. Set the cookie through the login endpoint, not dependency overrides.
- [ ] **Step 3: Implement `backend/services/sessions.py`.**
  - Tokens come from `secrets.token_urlsafe(32)`.
  - Compare hashes with `hmac.compare_digest`.
  - Timestamps are UTC-naive, consistent with the existing models.
- [ ] **Step 4: Switch user resolution in `backend/dependencies.py`.**
  - `_resolve_user` reads `request.cookies[SESSION_COOKIE]` and calls `resolve_session`.
  - Remove `OAuth2PasswordBearer` from `get_requester` and `get_current_user`; both take `request: Request`.
  - Keep `require_admin`, the viewer rule and linked-owner resolution exactly as they are.
  - Update `backend/middleware.py`, the audit middleware that decodes the bearer token to find `user_id`, so it resolves the user from the session cookie instead. Read-only: it must never bump `last_seen`.
- [ ] **Step 5: CSRF origin check.** Add middleware (or extend the existing one) so that for POST, PUT, PATCH and DELETE:
  - If an `Origin` header is present, it must be in `APP_ORIGINS`. Otherwise respond 403 with `{"detail":"Cross-origin request refused"}`.
  - If `Origin` is absent, fall back to `Referer`'s origin.
  - If both are absent, allow the request only when it carries no session cookie, which covers CLI and tests without cookies.
  - Add security-regression tests: a cross-origin POST with a valid cookie gets 403, and a same-origin POST succeeds. Prove the first test fails with the middleware removed.
- [ ] **Step 6: Login, logout and revoke routes** in `backend/routers/auth.py`.
  - Login keeps the existing rate limit (Task 3 tightens it).
  - On success, call `create_session(...)` and set the cookie.
  - `/auth/register`, if it logs the new user in, also sets the cookie.
  - The password-reset flows revoke all of the user's sessions after a reset.
- [ ] **Step 7: Update tests that use bearer tokens.** Find them with `git grep -ln "create_access_token\|Authorization" backend/tests`, then:
  - Replace the bearer auth with a test helper `login_client(client, username, password)`, or a fixture that creates a session row and sets the cookie on the TestClient.
  - Keep each test's intent.
  - Delete `create_access_token` and `decode_token` once nothing uses them, along with the security-regression tests that only covered JWT decoding. Replace those with session equivalents (a tampered or unknown cookie gets 401), and update the docstring list.
- [ ] **Step 8: Frontend.**
  - In `client.ts`, remove the bearer interceptor and set `withCredentials: true`. The 401 handling stays.
  - In `store/auth.ts`, drop the token. Keep only the non-secret cached `AuthUser` for UI, and base `isAuthenticated()` on that cached user. The server remains the authority: a 401 clears it.
  - Add `authApi.logout()`. The existing logout UI calls it, then clears the cache.
  - Update the Login page to use the new response shape.
- [ ] **Step 9: Run all checks** (backend suite, ruff, import check, tsc, vite build, bun test), then commit.

### Task 2: Single origin (`/api` proxy), production Docker build, bun everywhere

**Files:**
- Modify: `frontend/vite.config.ts`, `frontend/src/api/client.ts`, `frontend/nginx.conf`, `frontend/Dockerfile.frontend`, `docker-compose.yml`, `backend/config.py` (defaults), `README.md`/`docs/technical-guide.md` (dev instructions)
- Test: `frontend/tests/apiBase.test.ts` (if a helper is extracted), and a docker smoke script `scripts/docker_smoke.sh`

**Steps:**
- [ ] **Step 1: Point the frontend at `/api`.** Set the frontend `baseURL` to `import.meta.env.VITE_API_URL ?? "/api"`.
- [ ] **Step 2: Dev proxy.** In `vite.config.ts`, proxy `/api` to `http://127.0.0.1:8000`, rewriting `^/api` to `""`, with `ws: false`. Existing local dev keeps working through `scripts/start.sh`.
- [ ] **Step 3: nginx.**
  - `location /api/ { proxy_pass http://backend:8000/; ... }` strips the prefix and sets `Host`, `X-Forwarded-For` and `X-Forwarded-Proto`.
  - Keep the SPA fallback.
  - Add security headers:
    - `Content-Security-Policy` (default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' if Tailwind needs it; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none')
    - `X-Content-Type-Options: nosniff`
    - `Referrer-Policy: same-origin`
    - `Permissions-Policy` (camera=(), geolocation=())
  - Serve `sw.js` with `Cache-Control: no-cache`.
- [ ] **Step 4: Backend trusts the proxy only from the proxy.** Run uvicorn with `--proxy-headers --forwarded-allow-ips` set to the compose network (or the nginx container), so `request.client.host` is the real client for rate limiting.
- [ ] **Step 5: Dockerfile.frontend uses bun.** Use an `oven/bun` image pinned by digest, the same way `Dockerfile.backend` pins its base images, then `bun install --frozen-lockfile` and `bun run build`. Delete `frontend/package-lock.json` if nothing else uses it.
- [ ] **Step 6: docker-compose.**
  - The backend gets no published ports; it is reachable only from nginx.
  - The frontend publishes `127.0.0.1:8080:80` only, because Tailscale Serve fronts it in Plan 2.
  - Pass the new settings `COOKIE_SECURE`, `APP_ORIGINS` and `JWT_SECRET`. Drop `JWT_SECRET` if Task 1 removed JWT entirely; `SESSION_*` keep their defaults.
  - Mount `./data`.
- [ ] **Step 7: Smoke script.**
  - `scripts/docker_smoke.sh` builds both images, starts compose on an alternate project name with a temp data dir, waits for `GET http://127.0.0.1:8080/api/health` to return 200, checks the SPA index at `/` and the security headers, then tears down.
  - Run it if Docker is available. If not, report that clearly as not run; the controller will run it.
- [ ] **Step 8: Docs and commit.** Update the dev docs (`/api`, the proxy and `COOKIE_SECURE=false` for local HTTP), run all checks, then commit.

### Task 3: Per-account login limit and security event log, with alerts

**Files:**
- Modify: `backend/services/rate_limiter.py` (if needed), `backend/routers/auth.py`, `backend/models.py`, `backend/database.py`
- Create: `backend/services/security_events.py`
- Test: `backend/tests/test_security_events.py`, `backend/tests/test_security_regressions.py`

**Interfaces:**
- **Produces:**
  - `security_events.record(db, user_id: int | None, event: str, *, ip: str | None, user_agent: str | None, detail: str | None = None) -> None`
  - Event names: `login_success`, `login_failure`, `login_blocked`, `logout`, `sessions_revoked`, `password_changed`, `passkey_added`, `passkey_removed`, `password_login_disabled`, `password_login_enabled`
  - `GET /auth/security-events?limit=50` returns this user's newest events.

**Steps:**
- [ ] **Step 1: SecurityEvent model.** Fields: `id`, `user_id` (no FK, so events survive user deletion), `event`, `ip`, `user_agent`, `detail`, `created_at`. It must never hold secrets.
- [ ] **Step 2: Failing tests.**
  - **Per-account limit:** after 5 failed logins for one username, a 6th attempt from a DIFFERENT IP is still 429 within 15 minutes.
  - **Per-IP limit:** the existing per-IP+username limit still applies.
  - **Success doesn't count:** a successful login doesn't count toward the limit.
  - **Every login logs:** each outcome writes an event.
  - **No secrets logged:** the password never appears in any event field.
  - **Events endpoint:** returns only the caller's events.
  - **Prove the limit:** show the per-account limit test fails without it.
- [ ] **Step 3: Implement.**
  - In `/auth/login`, check `rate_limit_allow(f"login-acct:{username}", limit=5, window_seconds=900)` alongside the existing key. Record events for success, failure and blocked.
  - Record `logout` and `sessions_revoked` from Task 1's routes.
  - Record `password_changed` from the password-change and reset routes.
- [ ] **Step 4: Email alert helper.** Add `security_events.alert(db, user, subject, text)`, which sends through the existing email service when the user has an email and SMTP is configured, and otherwise does nothing. It is used by Task 4. Test it with the email sender mocked.
- [ ] **Step 5: Checks and commit.**

### Task 4: Passkeys (WebAuthn)

> **GATE:** before this task starts, the controller reviews `py_webauthn` (PyPI `webauthn`) and `@simplewebauthn/browser`. The review covers source, maintainers, network calls and install scripts, and the user must approve. The implementer adds them only after approval, pinned exactly: `uv add 'webauthn==X.Y.Z'` respecting the cooldown, and `bun add @simplewebauthn/browser@X.Y.Z --exact`.

**Files:**
- Create: `backend/services/passkeys.py`, `backend/routers/passkeys.py`, `frontend/src/pages/settings/SecurityTab.tsx`
- Modify: `backend/models.py`, `backend/database.py`, `backend/config.py` (`WEBAUTHN_RP_ID`, `WEBAUTHN_RP_NAME = "OfflineBudget"`, `WEBAUTHN_ORIGINS`), `backend/main.py`, `backend/routers/auth.py`, `frontend/src/pages/Login.tsx`, `frontend/src/api/index.ts`, settings navigation
- Test: `backend/tests/test_passkeys.py`, `backend/tests/test_security_regressions.py`

**Interfaces:**
- **Models:**
  - `WebAuthnCredential`: `id`, `user_id` (FK CASCADE), `credential_id` (LargeBinary, unique), `public_key` (LargeBinary), `sign_count` (int), `transports` (String, nullable), `name` (String(64)), `created_at`, `last_used_at` (nullable)
  - `WebAuthnChallenge`: `id`, `challenge` (LargeBinary), `purpose` ("register" | "login"), `user_id` (nullable for login), `expires_at` (5 min), single-use
  - `users.password_login_disabled` (Boolean, default False), with an ALTER
- **Routes** (under the `/auth/passkeys` prefix):
  - `POST /register/options`: requires a session; returns WebAuthn options JSON
  - `POST /register/verify`: requires a session; body `{name, credential}`; stores the credential, records `passkey_added`, sends the email alert
  - `POST /login/options`: no session; body `{username?}`; returns options (allowCredentials for that user if given, else discoverable/empty)
  - `POST /login/verify`: no session; body `{credential}`; verifies, updates `sign_count`, creates a session cookie exactly as password login does, records `login_success` with detail `passkey`
  - `GET /`: lists the caller's passkeys (id, name, created, last used)
  - `DELETE /{id}`: own credential only (404 otherwise); refuses to delete the last passkey while password login is disabled (409); records `passkey_removed`
  - `PUT /password-login` with `{disabled: bool}`: disabling requires ≥1 passkey (409 otherwise); records the event
- **Password login when disabled:** `/auth/login` for a user with `password_login_disabled` returns 403 "Password sign-in is turned off for this account; use your passkey" and counts toward the rate limit.

**Steps:**
- [ ] **Step 1: Models, migration and settings.** In dev, `WEBAUTHN_RP_ID` defaults to `localhost` and the origin to `http://localhost:5173`. Production values come from env in Plan 2.
- [ ] **Step 2: Failing tests** (use py_webauthn's documented test helpers or recorded fixture responses; never real devices):
  - Registration round-trip stores the credential.
  - A challenge is single-use and expires.
  - Login verify creates a session cookie.
  - The sign count must increase, so a replayed or cloned authenticator is refused.
  - Another user's credential can't log in as you.
  - Deleting another user's passkey returns 404.
  - Disabling password login with no passkey returns 409.
  - Password login is refused when disabled.
  - The email alert fires on passkey add (mock the email).
  - Security regressions: cross-user delete, and password login while disabled. Prove both fail without their guards.
- [ ] **Step 3: Implement** `services/passkeys.py` (wrapping py_webauthn's generate/verify functions) and the router.
- [ ] **Step 4: Frontend.**
  - **SecurityTab** (Settings → Security):
    - Passkeys list with Add (uses `startRegistration` and prompts for a name such as "iPhone") and Remove (ConfirmDialog).
    - Password-login toggle, shown only when ≥1 passkey exists.
    - "Sign out all devices" (ConfirmDialog).
    - Active sessions list.
    - Recent security events.
  - **Login page:** a "Sign in with passkey" button (uses `startAuthentication`), plus the existing password form.
  - Clear error messages, aria-labels, dark mode.
- [ ] **Step 5: Run checks and commit.**

### Task 5: Installable PWA (shell-only caching)

**Files:**
- Create: `frontend/public/manifest.webmanifest`, `frontend/public/icons/icon-192.png`, `icon-512.png`, `apple-touch-icon.png` (simple generated mark, no third-party assets), `frontend/public/sw.js`, `frontend/src/lib/swRoutes.ts`, `frontend/tests/swRoutes.test.ts`
- Modify: `frontend/index.html`, `frontend/src/main.tsx`

**Steps:**
- [ ] **Step 1: Write `swRoutes.ts`** as a pure function `shouldCache(url: URL, method: string): boolean`. It is true only for same-origin GET requests to built assets (`/assets/*`, icons, manifest, `/` and `index.html`). It is false for anything under `/api/`, any non-GET request, and any cross-origin URL. Write the test first and cover each case.
- [ ] **Step 2: `sw.js`.** Pre-cache the shell on install. On fetch:
  - For requests where `shouldCache` is false: go to the network only and never put the response in the cache.
  - For requests where it is true: use stale-while-revalidate.
  - Version the cache name with the build hash, and delete old caches on activate.
  
  Keep the routing rule in sync with `swRoutes.ts`: either import the same logic at build time, or document the duplication and add a test that reads `sw.js` and asserts the `/api/` exclusion.
- [ ] **Step 3: Manifest and iOS tags.**
  - Manifest: name "OfflineBudget", `display: standalone`, `start_url: /`, theme and background colors from the app palette.
  - `index.html`: link the manifest, add `apple-touch-icon` and `apple-mobile-web-app-capable`, and set the status bar style.
  - Register the service worker in `main.tsx` only when `import.meta.env.PROD`.
- [ ] **Step 4: Checks and commit.**

---

## After the tasks (controller)

1. Run a final whole-branch review on the most capable model.
2. Run the Docker smoke test.
3. Verify in the browser with Interceptor:
   - login with a password;
   - the cookie flags in devtools-equivalent checks;
   - passkey registration and login on localhost, if the test profile supports a virtual authenticator; otherwise note it as a manual iPhone check after Plan 2;
   - the PWA manifest is served.
4. The user's live login switches from a bearer token to a cookie session when this deploys, so tell the user they will need to log in again once.
5. Ask before pushing.
