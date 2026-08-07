# Self-Service Password Reset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user reset their own forgotten password, via an emailed link when SMTP + their email are configured, or a self-generated one-time recovery code when they aren't.

**Architecture:** Two new backend service modules (`password_reset.py` for tokens/codes, `rate_limiter.py` for a generic in-memory sliding-window limiter) sit behind four new thin endpoints on the existing `auth` router. Two new frontend pages (`ForgotPassword`, `ResetPassword`) plus a Settings addition drive the two flows. No new dependencies — reuses the existing `passlib` bcrypt context, `email_service.send_email`, and SQLAlchemy setup.

**Tech Stack:** FastAPI + SQLAlchemy + SQLite (backend), React + TypeScript + `@tanstack/react-query` + Tailwind (frontend). No alembic in this repo — schema changes go through `backend/database.py`'s `upgrade_schema()` (ALTER TABLE, ignore-if-exists) and `create_tables()` (SQLAlchemy `metadata.create_all`, which alone is enough to add brand-new tables to existing DBs).

## Global Constraints

- Reset tokens and recovery codes are hashed at rest with the existing `pwd_context` (bcrypt) from `backend/auth.py` — never store either raw.
- Reset token expiry: 15 minutes.
- Recovery code: single-use — cleared on successful use, user must generate a fresh one afterward.
- Rate limit: 5 attempts per username per hour on `reset-password-with-code` (the guessable-secret path). `reset-password` (email-link token) is deliberately **not** rate-limited by username — its payload carries no username, and the token is a 256-bit random value (`secrets.token_urlsafe(32)`), making brute force infeasible regardless of attempt throttling; its 15-minute expiry is the operative control. This narrows the design spec's "both reset endpoints" language — flagged for Dan's review alongside the plan.
- `POST /auth/forgot-password` always returns 204 with no body, regardless of whether the username exists, has an email set, or SMTP is configured — no enumeration signal.
- Minimum password length stays 6 characters, matching the existing `change_password` and admin-reset endpoints.
- `bun`/TypeScript conventions don't apply here — this is the existing Python/FastAPI + Vite/React stack; follow its established patterns (Pydantic schemas, `Mapped[...]` SQLAlchemy columns, Tailwind utility classes, `useMutation` from react-query).
- The frontend has no test framework configured (no test script, no `*.test.*` files) — don't introduce one as a side effect of this plan. Frontend tasks are verified by reading the diff and a manual run-through, not new test files.

---

## File Structure

**Backend:**
- `backend/models.py` — add `recovery_code_hash` / `recovery_code_created_at` to `User`; add `PasswordResetToken` table.
- `backend/database.py` — add `ALTER TABLE users ADD COLUMN ...` entries to `upgrade_schema()`.
- `backend/services/password_reset.py` — new. All token/code generation, hashing, verification, and expiry logic. No FastAPI imports — pure service functions taking a `Session` and plain args, matching the existing `services/forecast_engine.py` style.
- `backend/services/rate_limiter.py` — new. Generic in-memory sliding-window limiter, reusable beyond this feature.
- `backend/config.py` — add `FRONTEND_URL` setting.
- `backend/schemas.py` — add request/response models for the four new endpoints.
- `backend/routers/auth.py` — add the four endpoints, thin wrappers over the service module.
- `backend/tests/test_password_reset_service.py` — new.
- `backend/tests/test_rate_limiter.py` — new.
- `backend/tests/test_auth_reset_endpoints.py` — new, isolated `TestClient` (own throwaway `FastAPI()` wrapping just `auth.router`, not the real app/lifespan/scheduler).

**Frontend:**
- `frontend/src/api/index.ts` — add `authApi.forgotPassword`, `resetPassword`, `resetPasswordWithCode`, `generateRecoveryCode`.
- `frontend/src/pages/ForgotPassword.tsx` — new.
- `frontend/src/pages/ResetPassword.tsx` — new.
- `frontend/src/pages/Login.tsx` — add "Forgot password?" link.
- `frontend/src/pages/Settings.tsx` — add "Generate recovery code" control in the Profile section.
- `frontend/src/App.tsx` — register the two new public routes.

**Docs:**
- `.env.example` — document `FRONTEND_URL`.
- `docs/start-guide.md` — short "Forgot your password?" subsection.
- `SECURITY.md` — note on recovery codes and reset tokens.

---

## Task 1: Data model — recovery code fields + reset token table

**Files:**
- Modify: `backend/models.py`
- Modify: `backend/database.py`
- Test: `backend/tests/test_password_reset_service.py` (created here, extended in Task 2/3)

**Interfaces:**
- Produces: `models.User.recovery_code_hash: str | None`, `models.User.recovery_code_created_at: datetime | None`, `models.PasswordResetToken` (fields: `id`, `user_id`, `token_hash`, `expires_at`, `used_at`).

- [ ] **Step 1: Add the two columns to `User`**

In `backend/models.py`, inside `class User(Base):`, add near the existing `email` field:

```python
    recovery_code_hash: Mapped[str | None] = mapped_column(String(256))
    recovery_code_created_at: Mapped[datetime | None] = mapped_column(DateTime)
```

- [ ] **Step 2: Add the `PasswordResetToken` model**

Add a new section after `TransactionRule` (around line 476) in `backend/models.py`:

```python
# ── Password Reset ───────────────────────────────────────────────────────────

class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User] = relationship()
```

- [ ] **Step 3: Register the migration for existing databases**

`create_tables()` (`Base.metadata.create_all`) already picks up the brand-new `password_reset_tokens` table on every startup, for both fresh and existing DBs — no manual statement needed there. The two new `User` columns need explicit `ALTER TABLE` entries since `create_all` doesn't alter existing tables. In `backend/database.py`, add to the `stmts` list in `upgrade_schema()` (near the other `users` ALTERs):

```python
        "ALTER TABLE users ADD COLUMN recovery_code_hash TEXT",
        "ALTER TABLE users ADD COLUMN recovery_code_created_at DATETIME",
```

- [ ] **Step 4: Write a test confirming the schema is usable**

Create `backend/tests/test_password_reset_service.py`:

```python
from datetime import datetime, timedelta, timezone
from backend import models


def _make_user(db_session, username="alice"):
    user = models.User(
        username=username,
        hashed_password="x",
        display_name="Alice",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_user_recovery_fields_default_to_none(db_session):
    user = _make_user(db_session)
    assert user.recovery_code_hash is None
    assert user.recovery_code_created_at is None


def test_password_reset_token_round_trips(db_session):
    user = _make_user(db_session)
    token = models.PasswordResetToken(
        user_id=user.id,
        token_hash="hashed-value",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )
    db_session.add(token)
    db_session.commit()
    db_session.refresh(token)
    assert token.used_at is None
    assert token.user_id == user.id
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_password_reset_service.py -v`
Expected: both tests PASS (this step is verifying the schema, not TDD-ing new behavior — there's no failing-first here since it's a data model addition).

- [ ] **Step 6: Commit**

```bash
git add backend/models.py backend/database.py backend/tests/test_password_reset_service.py
git commit -m "feat: add recovery code fields and password_reset_tokens table"
```

---

## Task 2: Recovery-code service functions

**Files:**
- Create: `backend/services/password_reset.py`
- Test: `backend/tests/test_password_reset_service.py` (extend)

**Interfaces:**
- Consumes: `models.User`, `backend.auth.hash_password`, `backend.auth.verify_password` (existing, `backend/auth.py:9-14`).
- Produces: `issue_recovery_code(db: Session, user: models.User) -> str`, `verify_and_consume_recovery_code(db: Session, user: models.User, code: str) -> bool`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_password_reset_service.py`:

```python
from backend.services.password_reset import (
    issue_recovery_code,
    verify_and_consume_recovery_code,
)


def test_issue_recovery_code_returns_raw_and_stores_hash_only(db_session):
    user = _make_user(db_session)
    code = issue_recovery_code(db_session, user)
    assert len(code) >= 12
    assert user.recovery_code_hash is not None
    assert user.recovery_code_hash != code
    assert user.recovery_code_created_at is not None


def test_verify_and_consume_recovery_code_succeeds_and_rotates(db_session):
    user = _make_user(db_session)
    code = issue_recovery_code(db_session, user)
    assert verify_and_consume_recovery_code(db_session, user, code) is True
    # single-use: the same code fails on a second attempt
    assert user.recovery_code_hash is None
    assert verify_and_consume_recovery_code(db_session, user, code) is False


def test_verify_and_consume_recovery_code_rejects_wrong_code(db_session):
    user = _make_user(db_session)
    issue_recovery_code(db_session, user)
    assert verify_and_consume_recovery_code(db_session, user, "wrong-code") is False
    # a wrong attempt does not consume the real code
    assert user.recovery_code_hash is not None


def test_verify_and_consume_recovery_code_false_when_none_set(db_session):
    user = _make_user(db_session)
    assert verify_and_consume_recovery_code(db_session, user, "anything") is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_password_reset_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.services.password_reset'`

- [ ] **Step 3: Implement `issue_recovery_code` and `verify_and_consume_recovery_code`**

Create `backend/services/password_reset.py`:

```python
import secrets
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from backend import models
from backend.auth import hash_password, verify_password

# Unambiguous charset — no 0/O, 1/I/l — so a hand-copied code doesn't misread.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_GROUP_LEN = 4
_CODE_GROUPS = 3

RESET_TOKEN_TTL = timedelta(minutes=15)


def _generate_recovery_code() -> str:
    groups = [
        "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_GROUP_LEN))
        for _ in range(_CODE_GROUPS)
    ]
    return "-".join(groups)


def issue_recovery_code(db: Session, user: models.User) -> str:
    """Generates a new recovery code, stores only its hash, and returns the
    raw code once. Overwrites any previously issued code."""
    code = _generate_recovery_code()
    user.recovery_code_hash = hash_password(code)
    user.recovery_code_created_at = datetime.now(timezone.utc)
    db.commit()
    return code


def verify_and_consume_recovery_code(db: Session, user: models.User, code: str) -> bool:
    """Verifies a recovery code and, on success, clears it (single-use)."""
    if not user.recovery_code_hash:
        return False
    if not verify_password(code, user.recovery_code_hash):
        return False
    user.recovery_code_hash = None
    user.recovery_code_created_at = None
    db.commit()
    return True
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_password_reset_service.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/password_reset.py backend/tests/test_password_reset_service.py
git commit -m "feat: recovery code issue/verify service functions"
```

---

## Task 3: Reset-token service functions

**Files:**
- Modify: `backend/services/password_reset.py`
- Test: `backend/tests/test_password_reset_service.py` (extend)

**Interfaces:**
- Consumes: `models.PasswordResetToken`, `models.User`, `RESET_TOKEN_TTL` (from Task 2).
- Produces: `create_reset_token(db: Session, user: models.User) -> str`, `consume_reset_token(db: Session, raw_token: str, new_password: str) -> bool`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_password_reset_service.py`:

```python
from backend.services.password_reset import create_reset_token, consume_reset_token
from backend.auth import verify_password


def test_create_reset_token_returns_raw_and_stores_only_hash(db_session):
    user = _make_user(db_session)
    raw = create_reset_token(db_session, user)
    stored = db_session.query(models.PasswordResetToken).filter_by(user_id=user.id).one()
    assert stored.token_hash != raw
    assert stored.used_at is None


def test_consume_reset_token_sets_new_password_and_marks_used(db_session):
    user = _make_user(db_session)
    raw = create_reset_token(db_session, user)
    assert consume_reset_token(db_session, raw, "new-password-123") is True
    db_session.refresh(user)
    assert verify_password("new-password-123", user.hashed_password)
    stored = db_session.query(models.PasswordResetToken).filter_by(user_id=user.id).one()
    assert stored.used_at is not None


def test_consume_reset_token_rejects_reuse(db_session):
    user = _make_user(db_session)
    raw = create_reset_token(db_session, user)
    assert consume_reset_token(db_session, raw, "first-password") is True
    assert consume_reset_token(db_session, raw, "second-password") is False


def test_consume_reset_token_rejects_expired(db_session):
    user = _make_user(db_session)
    raw = create_reset_token(db_session, user)
    stored = db_session.query(models.PasswordResetToken).filter_by(user_id=user.id).one()
    stored.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()
    assert consume_reset_token(db_session, raw, "new-password-123") is False


def test_consume_reset_token_rejects_unknown_token(db_session):
    assert consume_reset_token(db_session, "not-a-real-token", "new-password-123") is False


def test_create_reset_token_invalidates_prior_outstanding_tokens(db_session):
    user = _make_user(db_session)
    first = create_reset_token(db_session, user)
    create_reset_token(db_session, user)  # second, current token
    # the first token must no longer work once a new one is issued
    assert consume_reset_token(db_session, first, "new-password-123") is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_password_reset_service.py -v`
Expected: FAIL — `create_reset_token`/`consume_reset_token` not defined.

- [ ] **Step 3: Implement `create_reset_token` and `consume_reset_token`**

Append to `backend/services/password_reset.py`:

```python
def create_reset_token(db: Session, user: models.User) -> str:
    """Invalidates any outstanding tokens for this user, issues a new one,
    and returns the raw token (only its hash is persisted)."""
    now = datetime.now(timezone.utc)
    outstanding = (
        db.query(models.PasswordResetToken)
        .filter(models.PasswordResetToken.user_id == user.id)
        .filter(models.PasswordResetToken.used_at.is_(None))
        .all()
    )
    for t in outstanding:
        t.used_at = now

    raw_token = secrets.token_urlsafe(32)
    record = models.PasswordResetToken(
        user_id=user.id,
        token_hash=hash_password(raw_token),
        expires_at=now + RESET_TOKEN_TTL,
    )
    db.add(record)
    db.commit()
    return raw_token


def consume_reset_token(db: Session, raw_token: str, new_password: str) -> bool:
    """Verifies a raw reset token, sets the new password, and marks the
    token used. Bcrypt hashes aren't lookup-able by value, so this scans
    unused, unexpired tokens — a small, bounded set in a single-household
    deployment — and verifies each candidate."""
    now = datetime.now(timezone.utc)
    candidates = (
        db.query(models.PasswordResetToken)
        .filter(models.PasswordResetToken.used_at.is_(None))
        .filter(models.PasswordResetToken.expires_at > now)
        .all()
    )
    for candidate in candidates:
        if verify_password(raw_token, candidate.token_hash):
            user = db.get(models.User, candidate.user_id)
            if not user:
                return False
            user.hashed_password = hash_password(new_password)
            candidate.used_at = now
            db.commit()
            return True
    return False
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_password_reset_service.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/password_reset.py backend/tests/test_password_reset_service.py
git commit -m "feat: reset token issue/consume service functions"
```

---

## Task 4: Generic rate limiter

**Files:**
- Create: `backend/services/rate_limiter.py`
- Test: `backend/tests/test_rate_limiter.py`

**Interfaces:**
- Produces: `allow(key: str, limit: int, window_seconds: int) -> bool` — returns `True` and records the attempt if under the limit for that key within the trailing window, `False` (and does not record) if at/over the limit.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_rate_limiter.py`:

```python
from backend.services.rate_limiter import allow, _reset_for_tests


def setup_function():
    _reset_for_tests()


def test_allows_up_to_the_limit():
    for _ in range(5):
        assert allow("alice", limit=5, window_seconds=3600) is True


def test_blocks_once_limit_exceeded():
    for _ in range(5):
        allow("alice", limit=5, window_seconds=3600)
    assert allow("alice", limit=5, window_seconds=3600) is False


def test_keys_are_isolated():
    for _ in range(5):
        allow("alice", limit=5, window_seconds=3600)
    assert allow("bob", limit=5, window_seconds=3600) is True


def test_window_expiry_resets_the_limit(monkeypatch):
    import backend.services.rate_limiter as rl

    t = [1000.0]
    monkeypatch.setattr(rl.time, "time", lambda: t[0])

    for _ in range(5):
        assert allow("alice", limit=5, window_seconds=60) is True
    assert allow("alice", limit=5, window_seconds=60) is False

    t[0] += 61  # advance past the window
    assert allow("alice", limit=5, window_seconds=60) is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_rate_limiter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.services.rate_limiter'`

- [ ] **Step 3: Implement the limiter**

Create `backend/services/rate_limiter.py`:

```python
import time
from collections import defaultdict

# key -> list of attempt timestamps within the current window.
# In-memory and per-process, matching this app's single-process local
# deployment (no Redis/shared-state dependency).
_attempts: dict[str, list[float]] = defaultdict(list)


def allow(key: str, limit: int, window_seconds: int) -> bool:
    now = time.time()
    cutoff = now - window_seconds
    recent = [t for t in _attempts[key] if t > cutoff]
    if len(recent) >= limit:
        _attempts[key] = recent
        return False
    recent.append(now)
    _attempts[key] = recent
    return True


def _reset_for_tests() -> None:
    _attempts.clear()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_rate_limiter.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/rate_limiter.py backend/tests/test_rate_limiter.py
git commit -m "feat: generic in-memory sliding-window rate limiter"
```

---

## Task 5: Auth endpoints — forgot-password, reset-password, reset-password-with-code, recovery-code

**Files:**
- Modify: `backend/config.py`
- Modify: `backend/schemas.py`
- Modify: `backend/routers/auth.py`
- Modify: `.env.example`
- Test: `backend/tests/test_auth_reset_endpoints.py`

**Interfaces:**
- Consumes: everything from Task 2/3/4 (`issue_recovery_code`, `verify_and_consume_recovery_code`, `create_reset_token`, `consume_reset_token`, `allow`), `backend.services.email_service.send_email` (existing, `backend/services/email_service.py:10`), `backend.dependencies.get_db`/`get_requester` (existing).
- Produces: `POST /auth/forgot-password`, `POST /auth/reset-password`, `POST /auth/reset-password-with-code`, `POST /auth/me/recovery-code`.

- [ ] **Step 1: Add `FRONTEND_URL` config**

In `backend/config.py`, add near `ALLOWED_ORIGINS`:

```python
    FRONTEND_URL: str | None = None  # base URL for links in emails; falls back to first ALLOWED_ORIGINS entry
```

And a property near `allowed_origins_list`:

```python
    @property
    def frontend_url(self) -> str:
        if self.FRONTEND_URL:
            return self.FRONTEND_URL.rstrip("/")
        return self.allowed_origins_list[0].rstrip("/")
```

- [ ] **Step 2: Document it in `.env.example`**

Add under the CORS section:

```
# Base URL used to build links in emails (e.g. password reset).
# Leave unset to reuse the first ALLOWED_ORIGINS entry.
# FRONTEND_URL=http://192.168.1.10:5173
```

- [ ] **Step 3: Add request/response schemas**

In `backend/schemas.py`, add near `LoginRequest`:

```python
class ForgotPasswordRequest(BaseModel):
    username: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class ResetPasswordWithCodeRequest(BaseModel):
    username: str
    code: str
    new_password: str


class RecoveryCodeOut(BaseModel):
    code: str
    created_at: datetime
```

- [ ] **Step 4: Write the failing endpoint tests**

Create `backend/tests/test_auth_reset_endpoints.py`. This uses its own throwaway `FastAPI()` app wrapping just the auth router — not the real `backend.main.app` — so tests don't trigger the real app's lifespan (which runs schema migrations and starts an APScheduler against the real `data/budget.db`):

```python
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.routers import auth as auth_router_module
from backend.dependencies import get_db
from backend.auth import hash_password
from backend.services.rate_limiter import _reset_for_tests


@pytest.fixture()
def client(db_session):
    app = FastAPI()
    app.include_router(auth_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    _reset_for_tests()
    return TestClient(app)


def _make_user(db_session, username="alice", email=None):
    user = models.User(
        username=username,
        hashed_password=hash_password("old-password"),
        display_name="Alice",
        email=email,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.mark.parametrize("username,email,smtp_host", [
    ("nonexistent", None, "smtp.example.com"),
    ("alice", None, "smtp.example.com"),   # user exists, no email
    ("alice", "a@example.com", None),      # user + email exist, no SMTP configured
])
def test_forgot_password_always_returns_204(client, db_session, username, email, smtp_host):
    if username == "alice":
        _make_user(db_session, email=email)
    with patch("backend.routers.auth.settings.SMTP_HOST", smtp_host), \
         patch("backend.routers.auth.send_email") as mock_send:
        resp = client.post("/auth/forgot-password", json={"username": username})
        assert resp.status_code == 204
        mock_send.assert_not_called()


def test_forgot_password_sends_email_when_configured(client, db_session):
    _make_user(db_session, email="a@example.com")
    with patch("backend.routers.auth.settings.SMTP_HOST", "smtp.example.com"), \
         patch("backend.routers.auth.send_email") as mock_send:
        resp = client.post("/auth/forgot-password", json={"username": "alice"})
        assert resp.status_code == 204
        mock_send.assert_called_once()
        assert mock_send.call_args.args[0] == "a@example.com"


def test_reset_password_with_valid_token(client, db_session):
    from backend.services.password_reset import create_reset_token
    user = _make_user(db_session)
    raw = create_reset_token(db_session, user)
    resp = client.post("/auth/reset-password", json={"token": raw, "new_password": "brand-new-pw"})
    assert resp.status_code == 204


def test_reset_password_rejects_bad_token(client):
    resp = client.post("/auth/reset-password", json={"token": "bogus", "new_password": "brand-new-pw"})
    assert resp.status_code == 400


def test_reset_password_with_code_round_trip(client, db_session):
    from backend.services.password_reset import issue_recovery_code
    user = _make_user(db_session)
    code = issue_recovery_code(db_session, user)
    resp = client.post(
        "/auth/reset-password-with-code",
        json={"username": "alice", "code": code, "new_password": "brand-new-pw"},
    )
    assert resp.status_code == 204


def test_reset_password_with_code_rate_limited_after_five_attempts(client, db_session):
    _make_user(db_session)
    for _ in range(5):
        client.post(
            "/auth/reset-password-with-code",
            json={"username": "alice", "code": "wrong", "new_password": "x123456"},
        )
    resp = client.post(
        "/auth/reset-password-with-code",
        json={"username": "alice", "code": "wrong", "new_password": "x123456"},
    )
    assert resp.status_code == 429


def test_generate_recovery_code_requires_auth(client):
    resp = client.post("/auth/me/recovery-code")
    assert resp.status_code == 401
```

- [ ] **Step 5: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_auth_reset_endpoints.py -v`
Expected: FAIL — 404s, the four routes don't exist yet.

- [ ] **Step 6: Implement the endpoints**

In `backend/routers/auth.py`, update imports:

```python
from backend.config import settings
from backend.services.email_service import send_email
from backend.services.password_reset import (
    create_reset_token,
    consume_reset_token,
    issue_recovery_code,
    verify_and_consume_recovery_code,
)
from backend.services.rate_limiter import allow as rate_limit_allow
```

Add the four endpoints (after `send_test_email`, before `delete_account`):

```python
@router.post("/forgot-password", status_code=status.HTTP_204_NO_CONTENT)
def forgot_password(body: schemas.ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Always returns 204, whether or not the account/email/SMTP exist —
    prevents username and email-configuration enumeration."""
    user = db.query(models.User).filter(models.User.username == body.username).first()
    if user and user.email and settings.SMTP_HOST:
        raw_token = create_reset_token(db, user)
        link = f"{settings.frontend_url}/reset-password?token={raw_token}"
        send_email(
            user.email,
            "OfflineBudget — Reset Your Password",
            f"<p>Click below to reset your password. This link expires in 15 minutes.</p>"
            f"<p><a href='{link}'>{link}</a></p>",
            f"Reset your password (expires in 15 minutes): {link}",
        )


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(body: schemas.ResetPasswordRequest, db: Session = Depends(get_db)):
    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    if not consume_reset_token(db, body.token, body.new_password):
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")


@router.post("/reset-password-with-code", status_code=status.HTTP_204_NO_CONTENT)
def reset_password_with_code(body: schemas.ResetPasswordWithCodeRequest, db: Session = Depends(get_db)):
    if not rate_limit_allow(f"reset-code:{body.username}", limit=5, window_seconds=3600):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")
    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    user = db.query(models.User).filter(models.User.username == body.username).first()
    if not user or not verify_and_consume_recovery_code(db, user, body.code):
        raise HTTPException(status_code=400, detail="Invalid recovery code")
    user.hashed_password = hash_password(body.new_password)
    db.commit()


@router.post("/me/recovery-code", response_model=schemas.RecoveryCodeOut)
def generate_recovery_code(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_requester),
):
    code = issue_recovery_code(db, current_user)
    return schemas.RecoveryCodeOut(code=code, created_at=current_user.recovery_code_created_at)
```

Note: `reset-password-with-code` both verifies the code (which clears the hash on success, via `verify_and_consume_recovery_code`) and then sets the new password — matching Task 2's single-use contract while keeping password-setting explicit in the router, consistent with `reset_password`'s style above.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_auth_reset_endpoints.py -v`
Expected: all PASS

- [ ] **Step 8: Run the full backend suite**

Run: `cd backend && python -m pytest -v`
Expected: all PASS, no regressions.

- [ ] **Step 9: Commit**

```bash
git add backend/config.py backend/schemas.py backend/routers/auth.py .env.example backend/tests/test_auth_reset_endpoints.py
git commit -m "feat: forgot-password, reset-password, and recovery-code endpoints"
```

---

## Task 6: Frontend — forgot-password and reset-password pages

**Files:**
- Modify: `frontend/src/api/index.ts`
- Create: `frontend/src/pages/ForgotPassword.tsx`
- Create: `frontend/src/pages/ResetPassword.tsx`
- Modify: `frontend/src/pages/Login.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `backend` endpoints from Task 5 (`POST /auth/forgot-password`, `POST /auth/reset-password`, `POST /auth/reset-password-with-code`).
- Produces: `authApi.forgotPassword(username)`, `authApi.resetPassword(token, new_password)`, `authApi.resetPasswordWithCode(username, code, new_password)`; routes `/forgot-password` and `/reset-password`.

- [ ] **Step 1: Add the API client methods**

In `frontend/src/api/index.ts`, extend `authApi` (near `sendTestEmail`):

```typescript
  forgotPassword: (username: string) =>
    api.post("/auth/forgot-password", { username }),
  resetPassword: (token: string, new_password: string) =>
    api.post("/auth/reset-password", { token, new_password }),
  resetPasswordWithCode: (username: string, code: string, new_password: string) =>
    api.post("/auth/reset-password-with-code", { username, code, new_password }),
```

- [ ] **Step 2: Build the ForgotPassword page**

Create `frontend/src/pages/ForgotPassword.tsx`:

```tsx
import { useState } from "react";
import { Link } from "react-router-dom";
import { authApi } from "../api";
import { DollarSign } from "lucide-react";

export default function ForgotPassword() {
  const [username, setUsername] = useState("");
  const [code, setCode] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [codeError, setCodeError] = useState("");
  const [codeSuccess, setCodeSuccess] = useState(false);
  const [loading, setLoading] = useState(false);

  async function submitUsername(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    try {
      await authApi.forgotPassword(username);
    } finally {
      setLoading(false);
      setSubmitted(true);
    }
  }

  async function submitCode(e: React.FormEvent) {
    e.preventDefault();
    setCodeError("");
    if (newPassword.length < 6) {
      setCodeError("Password must be at least 6 characters");
      return;
    }
    setLoading(true);
    try {
      await authApi.resetPasswordWithCode(username, code, newPassword);
      setCodeSuccess(true);
    } catch (err: any) {
      setCodeError(err.response?.data?.detail ?? "Invalid recovery code");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-indigo-50 to-white px-4">
      <div className="w-full max-w-sm">
        <div className="flex flex-col items-center mb-8">
          <div className="w-12 h-12 bg-indigo-600 rounded-xl flex items-center justify-center mb-3">
            <DollarSign className="text-white" size={24} />
          </div>
          <h1 className="text-2xl font-bold text-gray-900">Reset Your Password</h1>
        </div>

        <div className="card space-y-6">
          {codeSuccess ? (
            <p className="text-sm text-green-700 bg-green-50 rounded-lg px-3 py-2">
              Password reset. <Link to="/login" className="underline">Sign in</Link>.
            </p>
          ) : (
            <>
              {!submitted ? (
                <form onSubmit={submitUsername} className="space-y-4">
                  <div>
                    <label className="label">Username</label>
                    <input
                      className="input"
                      autoComplete="username"
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      required
                    />
                  </div>
                  <button type="submit" className="btn-primary w-full" disabled={loading}>
                    {loading ? "Please wait…" : "Send Reset Link"}
                  </button>
                </form>
              ) : (
                <p className="text-sm text-gray-600 bg-gray-50 rounded-lg px-3 py-2">
                  If that account has an email on file, a reset link is on its way.
                </p>
              )}

              <div className="border-t pt-4">
                <p className="text-sm text-gray-500 mb-3">Have a recovery code instead?</p>
                <form onSubmit={submitCode} className="space-y-3">
                  <input
                    className="input"
                    placeholder="Username"
                    autoComplete="username"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    required
                  />
                  <input
                    className="input"
                    placeholder="Recovery code"
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                    required
                  />
                  <input
                    type="password"
                    className="input"
                    placeholder="New password"
                    autoComplete="new-password"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    required
                  />
                  {codeError && (
                    <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{codeError}</p>
                  )}
                  <button type="submit" className="btn-primary w-full" disabled={loading}>
                    {loading ? "Please wait…" : "Reset with Code"}
                  </button>
                </form>
              </div>
            </>
          )}
        </div>
        <p className="text-center text-xs text-gray-400 mt-6">
          <Link to="/login" className="underline">Back to sign in</Link>
        </p>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Build the ResetPassword page (email-link landing)**

Create `frontend/src/pages/ResetPassword.tsx`:

```tsx
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { authApi } from "../api";
import { DollarSign } from "lucide-react";

export default function ResetPassword() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [newPassword, setNewPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (newPassword !== confirm) {
      setError("Passwords don't match");
      return;
    }
    if (newPassword.length < 6) {
      setError("Password must be at least 6 characters");
      return;
    }
    setLoading(true);
    try {
      await authApi.resetPassword(token, newPassword);
      setSuccess(true);
    } catch (err: any) {
      setError(err.response?.data?.detail ?? "This reset link is invalid or has expired.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-indigo-50 to-white px-4">
      <div className="w-full max-w-sm">
        <div className="flex flex-col items-center mb-8">
          <div className="w-12 h-12 bg-indigo-600 rounded-xl flex items-center justify-center mb-3">
            <DollarSign className="text-white" size={24} />
          </div>
          <h1 className="text-2xl font-bold text-gray-900">Set a New Password</h1>
        </div>

        <div className="card">
          {success ? (
            <p className="text-sm text-green-700 bg-green-50 rounded-lg px-3 py-2">
              Password reset. <Link to="/login" className="underline">Sign in</Link>.
            </p>
          ) : (
            <form onSubmit={submit} className="space-y-4">
              <div>
                <label className="label">New Password</label>
                <input
                  type="password"
                  className="input"
                  autoComplete="new-password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  required
                />
              </div>
              <div>
                <label className="label">Confirm Password</label>
                <input
                  type="password"
                  className="input"
                  autoComplete="new-password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  required
                />
              </div>
              {error && (
                <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>
              )}
              <button type="submit" className="btn-primary w-full" disabled={loading}>
                {loading ? "Please wait…" : "Reset Password"}
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Wire the routes**

In `frontend/src/App.tsx`, import the two new pages and add public routes alongside `/login`:

```tsx
import ForgotPassword from "./pages/ForgotPassword";
import ResetPassword from "./pages/ResetPassword";
```

```tsx
        <Route path="/login" element={<Login />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/reset-password" element={<ResetPassword />} />
```

- [ ] **Step 5: Add the "Forgot password?" link to Login**

In `frontend/src/pages/Login.tsx`, import `Link` from `react-router-dom` (already imports `useNavigate` from there) and add below the password field, before the submit button:

```tsx
            {mode === "login" && (
              <div className="text-right -mt-2">
                <Link to="/forgot-password" className="text-xs text-indigo-600 hover:underline">
                  Forgot password?
                </Link>
              </div>
            )}
```

- [ ] **Step 6: Manual verification**

Run: `./scripts/start.sh`, then in a browser:
1. Log in as `danford` (has an email set) → Settings → note no recovery code exists yet.
2. Go to `/login` → "Forgot password?" → enter `danford` → confirm the generic "check your email" message appears regardless of whether SMTP is configured locally.
3. Confirm `/reset-password?token=bogus` shows the invalid-link error on submit.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/index.ts frontend/src/pages/ForgotPassword.tsx frontend/src/pages/ResetPassword.tsx frontend/src/pages/Login.tsx frontend/src/App.tsx
git commit -m "feat: forgot-password and reset-password frontend flow"
```

---

## Task 7: Frontend — recovery code generation in Settings

**Files:**
- Modify: `frontend/src/api/index.ts`
- Modify: `frontend/src/pages/Settings.tsx`

**Interfaces:**
- Consumes: `POST /auth/me/recovery-code` (Task 5), returns `{ code: string, created_at: string }`.
- Produces: a "Generate recovery code" control in the existing Profile section of Settings, next to the email field.

- [ ] **Step 1: Add the API client method**

In `frontend/src/api/index.ts`, extend `authApi`:

```typescript
  generateRecoveryCode: (): Promise<{ code: string; created_at: string }> =>
    api.post("/auth/me/recovery-code").then((r) => r.data),
```

- [ ] **Step 2: Add state, mutation, and modal to Settings**

In `frontend/src/pages/Settings.tsx`, near the other profile-section state (around the `testEmailStatus` state used by `sendTestEmailMut`), add:

```tsx
  const [recoveryCode, setRecoveryCode] = useState<string | null>(null);
  const generateRecoveryCodeMut = useMutation({
    mutationFn: authApi.generateRecoveryCode,
    onSuccess: (data) => { setRecoveryCode(data.code); qc.invalidateQueries({ queryKey: ["me"] }); },
  });
```

Add the button in the profile section's JSX, near the "Send Test Email" button referenced at `frontend/src/pages/Settings.tsx:670-678`:

```tsx
          <div className="pt-2 border-t">
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
              A recovery code lets you reset your password without email. Generating a new one
              replaces any existing code.
            </p>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => generateRecoveryCodeMut.mutate()}
              disabled={generateRecoveryCodeMut.isPending}
            >
              {generateRecoveryCodeMut.isPending ? "Generating…" : "Generate Recovery Code"}
            </button>
          </div>

          {recoveryCode && (
            <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4">
              <div className="card max-w-sm w-full space-y-4">
                <h3 className="font-semibold text-gray-900">Save Your Recovery Code</h3>
                <p className="text-sm text-gray-500">
                  This won't be shown again. Store it somewhere safe — it's the only way to reset
                  your password without email.
                </p>
                <code className="block text-center text-lg font-mono bg-gray-100 rounded-lg py-3 tracking-wider">
                  {recoveryCode}
                </code>
                <button
                  type="button"
                  className="btn-primary w-full"
                  onClick={() => {
                    navigator.clipboard.writeText(recoveryCode);
                  }}
                >
                  Copy to Clipboard
                </button>
                <button
                  type="button"
                  className="text-sm text-gray-500 w-full text-center"
                  onClick={() => setRecoveryCode(null)}
                >
                  I've saved it — close
                </button>
              </div>
            </div>
          )}
```

`btn-secondary` is a defined utility class (`frontend/src/index.css:26`) already used elsewhere in the app — safe to reuse as-is.

- [ ] **Step 3: Manual verification**

Run: `./scripts/start.sh`, log in, go to Settings → Profile, click "Generate Recovery Code", confirm the modal shows a code in `XXXX-XXXX-XXXX` format, copy it, close the modal, refresh the page, and confirm the code is not re-displayed (it's write-once).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/index.ts frontend/src/pages/Settings.tsx
git commit -m "feat: recovery code generation in Settings"
```

---

## Task 8: Docs

**Files:**
- Modify: `docs/start-guide.md`
- Modify: `SECURITY.md`

**Interfaces:**
- Consumes: nothing (documentation only).

- [ ] **Step 1: Add a "Forgot your password?" subsection to the start guide**

In `docs/start-guide.md`, add a new numbered section after "3. Create Your Account" (renumbering subsequent sections isn't required — this repo's guide uses sequential numbers loosely tied to workflow order, so append as a new "3a" callout instead of renumbering everything):

```markdown
---

## Forgot Your Password?

1. From the login page, click **Forgot password?**
2. Enter your username. If you have an email address saved on your account
   **and** SMTP is configured in `.env`, a reset link is emailed to you
   (expires in 15 minutes).
3. No email configured, or don't have access to it? Use a **recovery code**
   instead — generate one ahead of time from **Settings → Profile →
   Generate Recovery Code**. Codes are single-use; generate a new one after
   each reset.

> Set `FRONTEND_URL` in `.env` if the emailed reset link should point
> somewhere other than the first `ALLOWED_ORIGINS` entry.
```

- [ ] **Step 2: Note the security model in SECURITY.md**

Read `SECURITY.md` first to match its existing heading style and voice, then add a short section covering: reset tokens and recovery codes are bcrypt-hashed at rest same as passwords, tokens expire in 15 minutes, codes are single-use, and both reset paths are rate-limited at 5 attempts/hour.

- [ ] **Step 3: Commit**

```bash
git add docs/start-guide.md SECURITY.md
git commit -m "docs: self-service password reset"
```
