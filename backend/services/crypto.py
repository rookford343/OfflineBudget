"""Fernet-based encryption for secrets at rest -- the SimpleFIN access URL and
the SMTP password set from the Settings page -- so a stolen budget.db does not
itself leak live bank access or mail credentials. Uses a key separate from
JWT_SECRET so rotating one never affects the other."""
from __future__ import annotations
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from backend.config import settings


class EncryptionNotConfigured(Exception):
    """Raised when the app encryption key is unset or wrong -- callers must
    never fall back to storing the secret in plaintext."""


def _fernet() -> MultiFernet:
    """Every configured key, primary first.

    A deployment that already had BANK_TOKEN_ENCRYPTION_KEY and later adds
    APP_ENCRYPTION_KEY flips which key `app_encryption_key` returns, which
    used to strand every secret already written under the old one ("Stored
    token could not be decrypted"). MultiFernet decrypts with any key in the
    list while always encrypting under the first, so adding the new name is
    non-destructive and the migration can happen lazily via rotate().
    """
    keys = []
    seen = set()
    for raw in (settings.APP_ENCRYPTION_KEY, settings.BANK_TOKEN_ENCRYPTION_KEY):
        if not raw or raw in seen:
            continue
        seen.add(raw)
        try:
            keys.append(Fernet(raw.encode()))
        except Exception as exc:
            raise EncryptionNotConfigured(f"App encryption key is not a valid Fernet key: {exc}") from exc
    if not keys:
        raise EncryptionNotConfigured(
            "APP_ENCRYPTION_KEY (or legacy BANK_TOKEN_ENCRYPTION_KEY) is not set in .env"
        )
    return MultiFernet(keys)


def reencrypt_under_primary(ciphertext: str) -> str:
    """Re-wrap an existing secret under the primary key, for one-time
    migration after a key is added. Returns the new ciphertext."""
    try:
        return _fernet().rotate(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise EncryptionNotConfigured("Stored token could not be decrypted -- key may have changed") from exc


def is_encryption_configured() -> bool:
    """Non-raising probe, so the Settings page can show whether secrets can be
    stored without forcing the caller into a try/except."""
    try:
        _fernet()
        return True
    except EncryptionNotConfigured:
        return False


def assert_encryption_configured() -> None:
    """Raise EncryptionNotConfigured if the key is missing or invalid, without
    needing a plaintext in hand. Lets callers fail BEFORE spending a one-time
    resource (e.g. a SimpleFIN setup token, which can only be claimed once)."""
    _fernet()


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise EncryptionNotConfigured("Stored token could not be decrypted -- key may have changed") from exc
