from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.routers import auth as auth_router_module
from backend.dependencies import get_db
from backend.auth import hash_password, verify_password
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


def test_forgot_password_rate_limited_after_five_attempts_still_returns_204(client, db_session):
    """Rate limiting must not leak a distinguishable signal — a rate-limited
    request still returns 204 with no email sent, same as any other no-op."""
    _make_user(db_session, email="a@example.com")
    with patch("backend.routers.auth.settings.SMTP_HOST", "smtp.example.com"), \
         patch("backend.routers.auth.send_email") as mock_send:
        for _ in range(5):
            client.post("/auth/forgot-password", json={"username": "alice"})
        mock_send.reset_mock()
        resp = client.post("/auth/forgot-password", json={"username": "alice"})
        assert resp.status_code == 204
        mock_send.assert_not_called()


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


def test_reset_password_with_code_actually_changes_password_and_clears_code(client, db_session):
    """End-to-end version of the atomicity fix: not just a 204, but proof
    the password really changed and the recovery code was really cleared,
    in what should be a single atomic operation."""
    from backend.services.password_reset import issue_recovery_code
    user = _make_user(db_session)
    code = issue_recovery_code(db_session, user)
    resp = client.post(
        "/auth/reset-password-with-code",
        json={"username": "alice", "code": code, "new_password": "brand-new-pw"},
    )
    assert resp.status_code == 204
    db_session.refresh(user)
    assert verify_password("brand-new-pw", user.hashed_password)
    assert user.recovery_code_hash is None


def test_forgot_password_then_reset_password_actually_changes_password(client, db_session):
    """End-to-end emailed-link path: forgot-password queues an email with a
    reset link (captured via the mocked send_email background task), and
    submitting that exact token to reset-password really changes the
    password — not just a 204."""
    user = _make_user(db_session, email="a@example.com")
    with patch("backend.routers.auth.settings.SMTP_HOST", "smtp.example.com"), \
         patch("backend.routers.auth.send_email") as mock_send:
        resp = client.post("/auth/forgot-password", json={"username": "alice"})
        assert resp.status_code == 204
        mock_send.assert_called_once()
        text_body = mock_send.call_args.args[3]
        token = text_body.rsplit("token=", 1)[-1]

    resp = client.post("/auth/reset-password", json={"token": token, "new_password": "brand-new-pw"})
    assert resp.status_code == 204
    db_session.refresh(user)
    assert verify_password("brand-new-pw", user.hashed_password)


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
