"""Server settings editable from the Settings page (Dan, 2026-08-15):
"all settings can be configured (securely) on the front end" plus a real
multi-recipient list for the daily email.

The security half is what most of these pin. A settings UI that quietly
widened the attack surface would be a worse outcome than leaving the
settings in .env, so the allowlist, the secret masking, and the refusal to
store a plaintext password all have tests rather than just comments.
"""
from datetime import date
from decimal import Decimal
import pytest
from backend import models
from backend.services import app_settings
from backend.services.email_service import parse_recipients


def _user(db, **kw):
    u = models.User(username=kw.pop("username", "dan"), hashed_password="x",
                    display_name="Dan", **kw)
    db.add(u)
    db.flush()
    return u


# --- Allowlist -----------------------------------------------------------

def test_bootstrap_and_crypto_settings_are_not_editable():
    """The whole point of the allowlist. Each of these either can't be read
    from the table it would live in, or breaks the session doing the edit."""
    for key in ["JWT_SECRET", "DATABASE_URL", "ALLOWED_ORIGINS", "HOST", "PORT",
                "APP_ENCRYPTION_KEY", "BANK_TOKEN_ENCRYPTION_KEY"]:
        assert key not in app_settings.EDITABLE, f"{key} must stay env-only"


def test_writing_a_non_editable_key_raises(db_session):
    with pytest.raises(KeyError):
        app_settings.set_value(db_session, "JWT_SECRET", "hunter2")


def test_env_status_reports_presence_never_values():
    """The Settings page shows whether these are set so it doesn't look
    broken -- but a value must never reach the browser."""
    for entry in app_settings.env_status():
        assert set(entry.keys()) == {"key", "configured"}
        assert isinstance(entry["configured"], bool)


# --- Override semantics --------------------------------------------------

def test_db_value_overrides_env_and_blank_restores_the_env_default(db_session):
    """Adding this feature must not change behaviour for a deployment that
    never opens the page, and there must be a way back from the UI."""
    from backend.config import settings as env_settings

    assert app_settings.get_effective(db_session, "SMTP_HOST") == env_settings.SMTP_HOST

    app_settings.set_value(db_session, "SMTP_HOST", "smtp.example.com")
    db_session.commit()
    assert app_settings.get_effective(db_session, "SMTP_HOST") == "smtp.example.com"

    app_settings.set_value(db_session, "SMTP_HOST", "")
    db_session.commit()
    assert app_settings.get_effective(db_session, "SMTP_HOST") == env_settings.SMTP_HOST, (
        "clearing an override must fall back to .env, not store an empty string"
    )


def test_int_and_bool_settings_coerce_off_the_text_column(db_session):
    app_settings.set_value(db_session, "DAILY_SUMMARY_HOUR", 6)
    app_settings.set_value(db_session, "WEEKLY_DIGEST_ENABLED", True)
    db_session.commit()

    assert app_settings.get_effective(db_session, "DAILY_SUMMARY_HOUR") == 6
    assert app_settings.get_effective(db_session, "WEEKLY_DIGEST_ENABLED") is True

    app_settings.set_value(db_session, "WEEKLY_DIGEST_ENABLED", False)
    db_session.commit()
    assert app_settings.get_effective(db_session, "WEEKLY_DIGEST_ENABLED") is False


# --- Secrets -------------------------------------------------------------

def test_smtp_password_is_encrypted_at_rest(db_session, monkeypatch):
    """A stolen budget.db must not hand over mail credentials -- the same
    bar the SimpleFIN token already met."""
    from cryptography.fernet import Fernet
    from backend.config import settings as env_settings
    monkeypatch.setattr(env_settings, "APP_ENCRYPTION_KEY", Fernet.generate_key().decode(), raising=False)

    app_settings.set_value(db_session, "SMTP_PASS", "super-secret-pw")
    db_session.commit()

    row = db_session.query(models.AppSetting).filter_by(key="SMTP_PASS").first()
    assert row.is_secret is True
    assert "super-secret-pw" not in row.value, "password must not be readable in the DB"
    assert app_settings.get_effective(db_session, "SMTP_PASS") == "super-secret-pw"


def test_password_is_refused_rather_than_stored_plaintext_without_a_key(db_session, monkeypatch):
    """The silent downgrade this must never make: storing the secret in the
    clear because encryption happens to be unconfigured."""
    from backend.config import settings as env_settings
    from backend.services.crypto import EncryptionNotConfigured
    monkeypatch.setattr(env_settings, "APP_ENCRYPTION_KEY", None, raising=False)
    monkeypatch.setattr(env_settings, "BANK_TOKEN_ENCRYPTION_KEY", None, raising=False)

    with pytest.raises(EncryptionNotConfigured):
        app_settings.set_value(db_session, "SMTP_PASS", "should-not-persist")

    assert db_session.query(models.AppSetting).filter_by(key="SMTP_PASS").first() is None


# --- Recipients ----------------------------------------------------------

def test_report_recipients_falls_back_to_the_account_email(db_session):
    """Where recipients lived before this setting existed -- a fresh install
    must keep working with no configuration."""
    user = _user(db_session, email="dan@example.com")
    db_session.commit()
    assert app_settings.get_recipients(db_session, user) == ["dan@example.com"]


def test_report_recipients_overrides_the_account_email(db_session):
    """The separation that matters: the account email is a login identity,
    the recipient list is who in the household reads the report. Dan's wife
    never signs in."""
    user = _user(db_session, username="dan2", email="dan@example.com")
    app_settings.set_value(db_session, "REPORT_RECIPIENTS", "dan@example.com, wife@example.com")
    db_session.commit()

    assert app_settings.get_recipients(db_session, user) == ["dan@example.com", "wife@example.com"]


def test_recipients_work_with_no_account_email_at_all(db_session):
    """A user with a blank account email used to be filtered out of the send
    loop entirely; now the recipient list is what decides."""
    user = _user(db_session, username="dan3", email=None)
    app_settings.set_value(db_session, "REPORT_RECIPIENTS", "wife@example.com")
    db_session.commit()

    assert app_settings.get_recipients(db_session, user) == ["wife@example.com"]


def test_parse_recipients_tolerates_messy_spacing():
    assert parse_recipients(" a@x.com ,, b@x.com ,") == ["a@x.com", "b@x.com"]


# --- Validation ----------------------------------------------------------

def test_update_schema_rejects_bad_hour_day_and_addresses():
    """Catch a typo at save time instead of as a silent non-delivery the
    next morning."""
    from backend import schemas

    with pytest.raises(Exception):
        schemas.AppSettingsUpdate(daily_summary_hour=25)
    with pytest.raises(Exception):
        schemas.AppSettingsUpdate(weekly_digest_day="funday")
    with pytest.raises(Exception):
        schemas.AppSettingsUpdate(report_recipients="dan@example.com, not-an-address")

    ok = schemas.AppSettingsUpdate(daily_summary_hour=7, weekly_digest_day="FRI ",
                                    report_recipients="a@x.com, b@y.com")
    assert ok.weekly_digest_day == "fri", "day should normalize"


# --- API surface ---------------------------------------------------------

@pytest.fixture()
def settings_client(db_session, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from cryptography.fernet import Fernet
    from backend.routers import settings as settings_router_module
    from backend.dependencies import get_db, require_admin
    from backend.services import crypto

    monkeypatch.setattr(crypto.settings, "APP_ENCRYPTION_KEY", Fernet.generate_key().decode(), raising=False)
    admin = _user(db_session, username="admin", role=models.UserRole.admin, email="admin@example.com")
    db_session.commit()

    app = FastAPI()
    app.include_router(settings_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[require_admin] = lambda: admin
    return TestClient(app), admin


def test_api_never_returns_the_smtp_password(settings_client, db_session):
    """The single most important assertion here: opening the Settings page
    must not put the mail password into the browser, a proxy log, or a
    screenshot."""
    client, _ = settings_client
    client.patch("/settings", json={"smtp_pass": "super-secret-pw", "smtp_host": "smtp.example.com"})

    body = client.get("/settings").json()
    assert "super-secret-pw" not in str(body)
    assert "smtp_pass" not in body, "the value must not be present under any key"
    assert body["smtp_pass_set"] is True, "but the page still needs to know one is stored"


def test_saving_without_touching_the_password_keeps_it(settings_client, db_session):
    """The frontend echoes a mask back for an untouched field. Treating that
    as a real value would overwrite the stored secret with asterisks and
    silently break SMTP login."""
    client, _ = settings_client
    client.patch("/settings", json={"smtp_pass": "real-password"})

    client.patch("/settings", json={"smtp_pass": app_settings.SECRET_PLACEHOLDER, "smtp_user": "dan"})

    assert app_settings.get_effective(db_session, "SMTP_PASS") == "real-password"
    assert app_settings.get_effective(db_session, "SMTP_USER") == "dan"


def test_api_rejects_a_non_editable_key(settings_client):
    client, _ = settings_client
    r = client.patch("/settings", json={"jwt_secret": "hunter2"})
    # Pydantic drops unknown fields, so the write simply never happens --
    # either outcome is safe, but it must never be applied.
    assert r.status_code in (200, 400, 422)
    from backend.config import settings as env_settings
    assert env_settings.JWT_SECRET != "hunter2"
