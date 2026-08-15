"""Fernet-based encryption for secrets at rest -- the SimpleFIN access URL and
the SMTP password set from the Settings page -- so a stolen budget.db does not
itself leak live bank access or mail credentials. Uses a key separate from
JWT_SECRET so rotating one never affects the other."""
from __future__ import annotations
from cryptography.fernet import Fernet, InvalidToken
from backend.config import settings


class EncryptionNotConfigured(Exception):
    """Raised when the app encryption key is unset or wrong -- callers must
    never fall back to storing the secret in plaintext."""


def _fernet() -> Fernet:
    key = settings.app_encryption_key
    if not key:
        raise EncryptionNotConfigured(
            "APP_ENCRYPTION_KEY (or legacy BANK_TOKEN_ENCRYPTION_KEY) is not set in .env"
        )
    try:
        return Fernet(key.encode())
    except Exception as exc:
        raise EncryptionNotConfigured(f"App encryption key is not a valid Fernet key: {exc}") from exc


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
