"""Fernet-based encryption for the SimpleFIN access URL, so a stolen budget.db
does not itself leak live bank access. Uses a key separate from JWT_SECRET
so rotating one never affects the other."""
from __future__ import annotations
from cryptography.fernet import Fernet, InvalidToken
from backend.config import settings


class EncryptionNotConfigured(Exception):
    """Raised when BANK_TOKEN_ENCRYPTION_KEY is unset or wrong -- callers must
    never fall back to storing the token in plaintext."""


def _fernet() -> Fernet:
    if not settings.BANK_TOKEN_ENCRYPTION_KEY:
        raise EncryptionNotConfigured("BANK_TOKEN_ENCRYPTION_KEY is not set in .env")
    try:
        return Fernet(settings.BANK_TOKEN_ENCRYPTION_KEY.encode())
    except Exception as exc:
        raise EncryptionNotConfigured(f"BANK_TOKEN_ENCRYPTION_KEY is not a valid Fernet key: {exc}") from exc


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise EncryptionNotConfigured("Stored token could not be decrypted -- key may have changed") from exc
