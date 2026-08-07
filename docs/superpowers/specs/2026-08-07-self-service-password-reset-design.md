# Self-Service Password Reset — Design

**Date:** 2026-08-07
**Status:** Approved

## Problem

Users can't recover their account today if they forget their password. The only
existing path is admin-assisted (`PATCH /admin/users/{id}/password`), which
requires another admin account to already be logged in — no help for a sole
admin locked out of their own account.

## Constraints

- App is local-network-only, self-hosted via docker-compose, no public URL.
- `User.email` is optional and nullable — not every account has one set.
- SMTP is optional (`SMTP_HOST` in config); the app runs fine with it unset,
  and `send_email()` silently no-ops when it is. A reset flow that only works
  by email is unusable for zero-SMTP or zero-email deployments (both accounts
  in the current dev DB — `demo` and `danford` — illustrate this gap; `demo`
  has no email set at all).

## Approach

Hybrid: email-link reset when SMTP + a user email are both available, and a
recovery-code fallback that needs neither. Chosen over email-only (fails
silently for unconfigured/no-email accounts) and code-only (worse UX for the
common case where SMTP is already set up).

## Data model

New fields on `User` (`backend/models.py`):

- `recovery_code_hash: str | None` — bcrypt hash via the existing
  `pwd_context`, never stored raw.
- `recovery_code_created_at: datetime | None` — surfaced in Settings so the
  user can tell if their saved code is stale.

New table `PasswordResetToken`:

- `id, user_id, token_hash, expires_at, used_at`
- Token expiry: 15 minutes.
- Only the hash is persisted; the raw token exists solely in the emailed
  link, mirroring how passwords and the recovery code are handled.

## Backend flow

**Email path**

- `POST /auth/forgot-password` — body `{username}`. Always returns 204
  regardless of whether the account exists, has an email set, or SMTP is
  configured — no enumeration signal either way.
- If the user exists, has `email` set, and `SMTP_HOST` is configured: create
  a `PasswordResetToken` and email a link to `/reset-password?token=...`.
- `POST /auth/reset-password` — body `{token, new_password}`. Looks up the
  token by hash, checks `expires_at`/`used_at`, sets the new password, marks
  the token used, and invalidates any other outstanding tokens for that user.

**Recovery-code path**

- `POST /auth/reset-password-with-code` — body `{username, code,
  new_password}`. Verifies `code` against `recovery_code_hash` via
  `pwd_context.verify`, same as login.
- On success: sets the new password and nulls `recovery_code_hash` —
  single-use, like a backup code. The user must generate a fresh one
  afterward.
- Rate limit: 5 attempts per username per hour, in-memory (matches the app's
  single-process local deployment — no Redis dependency).

**Settings**

- `POST /auth/me/recovery-code` (authenticated) — generates a new code,
  returns it once in the response body, stores only the hash. Existing code
  (if any) is overwritten.

## Frontend flow

- Login page: "Forgot password?" link.
- Forgot-password form: username only → generic response screen ("if that
  account exists, check your email") that also contains an inline
  recovery-code + new-password form on the same screen.
- `/reset-password?token=...` — standalone page for the emailed link, new
  password + confirm.
- Settings → Profile: "Generate recovery code" button → modal showing the
  code once, copy-to-clipboard, explicit warning it won't be shown again.

## Security

- Reset tokens and recovery codes are never logged.
- Token expiry: 15 minutes. Recovery code: single-use, rotated on use.
- Rate limit: 5 attempts/hour/username on both reset endpoints.
- `forgot-password` response is identical (204, no body) whether or not the
  account/email/SMTP exist — prevents username and email-configuration
  enumeration.
- Existing `AdminPasswordReset` endpoint is unchanged — still available for
  admin-assisted resets of other users.

## Testing

Backend:

- Token expiry and reuse rejection.
- Recovery code: correct code succeeds and rotates; wrong code fails; used
  code rejected on retry.
- Rate limit trips after 5 attempts and resets after the window.
- `forgot-password` returns 204 for nonexistent username, no-email account,
  and no-SMTP config alike (enumeration-safety check).

Frontend:

- One flow test per path: email-link reset, recovery-code reset.

## Out of scope

- Multi-admin recovery / account delegation.
- SMS or other non-email delivery channels.
- Forcing existing users through a mandatory recovery-code setup step.
