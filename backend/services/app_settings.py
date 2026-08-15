"""Effective server configuration: a DB-backed override layer over .env.

Every consumer reads through `get_effective()` rather than touching
`config.settings` directly, so a value edited on the Settings page takes
hold immediately and an untouched one keeps falling back to .env. That
ordering matters -- it means adding this feature changed nothing for a
deployment that never opens the Settings page.

Two hard rules, both enforced here rather than trusted to callers:

  1. Only keys in EDITABLE can be written. Everything else in .env stays
     env-only, and the router 400s on anything outside the allowlist.
  2. Secrets are Fernet-encrypted at rest and never leave the process in
     plaintext except to the code that actually uses them (SMTP login).

What is deliberately NOT editable, and why -- this is the "securely" half
of the request and the reasoning belongs next to the allowlist:

  JWT_SECRET            rotating it invalidates every session including the
                        one performing the rotation; you would log yourself
                        out mid-save with no way to confirm it worked.
  APP_ENCRYPTION_KEY /  changing it makes every already-encrypted value
  BANK_TOKEN_ENCRYPTION undecryptable -- stored bank tokens and the SMTP
                        password would silently stop working, and bank sync
                        would fail with a decrypt error rather than anything
                        that points back at this form.
  DATABASE_URL          bootstrap: it is how this table is reached in the
                        first place, so it cannot live inside it.
  ALLOWED_ORIGINS       a CORS allowlist editable from a browser is a CSRF
                        foothold -- a tricked admin request could widen it
                        to '*' and open the API to any origin.

Those still surface on the Settings page as read-only status (configured /
not configured), never as values.
"""
from __future__ import annotations
import logging
from sqlalchemy.orm import Session
from backend import models
from backend.config import settings
from backend.services.crypto import encrypt, decrypt, EncryptionNotConfigured

logger = logging.getLogger(__name__)

# key -> (type, is_secret). The type drives coercion on read and validation
# on write; `str` covers anything free-form.
EDITABLE: dict[str, tuple[type, bool]] = {
    "SMTP_HOST": (str, False),
    "SMTP_PORT": (int, False),
    "SMTP_USER": (str, False),
    "SMTP_PASS": (str, True),
    "SMTP_FROM": (str, False),
    "DAILY_SUMMARY_HOUR": (int, False),
    "WEEKLY_DIGEST_DAY": (str, False),
    "WEEKLY_DIGEST_ENABLED": (bool, False),
    "REPORT_RECIPIENTS": (str, False),
}

# Read-only status shown on the Settings page: name -> whether .env set it.
# Values are never included, only whether something is there.
ENV_ONLY_KEYS = [
    "JWT_SECRET",
    "DATABASE_URL",
    "ALLOWED_ORIGINS",
    "APP_ENCRYPTION_KEY",
]

SECRET_PLACEHOLDER = "********"


def _coerce(raw: str | None, typ: type):
    if raw is None or raw == "":
        return None
    if typ is int:
        try:
            return int(raw)
        except ValueError:
            return None
    if typ is bool:
        return raw.strip().lower() in ("1", "true", "yes", "on")
    return raw


def _env_default(key: str):
    """The .env / config.py value a DB row overrides."""
    if key == "WEEKLY_DIGEST_ENABLED":
        return settings.weekly_digest_enabled
    if key == "REPORT_RECIPIENTS":
        # No .env equivalent -- recipients used to come from User.email.
        # Falling back to None lets get_recipients() do that lookup.
        return None
    return getattr(settings, key, None)


def get_effective(db: Session, key: str):
    """DB override if present, else the .env default. Secrets come back
    decrypted -- this is the accessor the SMTP code uses, not the API."""
    if key not in EDITABLE:
        raise KeyError(f"{key} is not an editable setting")
    typ, is_secret = EDITABLE[key]
    row = db.query(models.AppSetting).filter_by(key=key).first()
    if row is not None and row.value not in (None, ""):
        raw = row.value
        if is_secret:
            try:
                raw = decrypt(raw)
            except EncryptionNotConfigured:
                # A stored secret we can no longer read is strictly worse than
                # no secret: falling through to the .env value keeps mail
                # working instead of failing auth with a confusing error.
                logger.error("Could not decrypt %s -- falling back to .env", key)
                return _env_default(key)
        return _coerce(raw, typ)
    return _env_default(key)


def set_value(db: Session, key: str, value) -> None:
    """Write one setting. Blank clears the override and restores the .env
    default rather than storing an empty string, so there is always a way
    back to the file-based config from the UI."""
    if key not in EDITABLE:
        raise KeyError(f"{key} is not an editable setting")
    _, is_secret = EDITABLE[key]

    row = db.query(models.AppSetting).filter_by(key=key).first()
    if value is None or (isinstance(value, str) and value.strip() == ""):
        if row is not None:
            db.delete(row)
        return

    stored = str(value).strip() if not isinstance(value, bool) else ("true" if value else "false")
    if is_secret:
        # No key, no storage. Writing a plaintext password to the DB because
        # encryption happens to be unconfigured is exactly the silent
        # downgrade this refuses to make.
        stored = encrypt(stored)

    if row is None:
        db.add(models.AppSetting(key=key, value=stored, is_secret=is_secret))
    else:
        row.value = stored
        row.is_secret = is_secret


def get_recipients(db: Session, user: models.User) -> list[str]:
    """Who the daily summary actually goes to.

    REPORT_RECIPIENTS when set, otherwise the user's own account email --
    which is where recipients lived before this setting existed, and still
    the sensible default for a fresh install. Separating the two matters
    because the account email is a login identity, while the report list is
    "who in the household wants to read this" (Dan's wife never signs in).
    """
    from backend.services.email_service import parse_recipients

    configured = get_effective(db, "REPORT_RECIPIENTS")
    if configured:
        return parse_recipients(configured)
    return parse_recipients(user.email)


def env_status() -> list[dict]:
    """Read-only view of the env-only keys: name + whether it is set. Never
    the value."""
    out = []
    for key in ENV_ONLY_KEYS:
        if key == "APP_ENCRYPTION_KEY":
            configured = bool(settings.app_encryption_key)
        else:
            configured = bool(getattr(settings, key, None))
        out.append({"key": key, "configured": configured})
    return out
