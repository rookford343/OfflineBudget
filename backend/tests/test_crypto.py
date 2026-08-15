import pytest
from cryptography.fernet import Fernet
from backend.services import crypto
from backend.services.crypto import EncryptionNotConfigured


def test_encrypt_decrypt_round_trip(monkeypatch):
    monkeypatch.setattr(crypto.settings, "BANK_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    plaintext = "https://user:pass@bridge.simplefin.org/simplefin"
    ciphertext = crypto.encrypt(plaintext)
    assert ciphertext != plaintext
    assert crypto.decrypt(ciphertext) == plaintext


def test_encrypt_raises_when_key_unset(monkeypatch):
    monkeypatch.setattr(crypto.settings, "BANK_TOKEN_ENCRYPTION_KEY", None)
    # Both names must be cleared: APP_ENCRYPTION_KEY is the current name
    # and BANK_TOKEN_ENCRYPTION_KEY only its legacy alias, so clearing one
    # leaves encryption configured. Also keeps this test independent of
    # whatever the developer happens to have in their real .env.
    monkeypatch.setattr(crypto.settings, "APP_ENCRYPTION_KEY", None, raising=False)
    with pytest.raises(EncryptionNotConfigured):
        crypto.encrypt("secret")


def test_decrypt_raises_on_wrong_key(monkeypatch):
    """Rotating the key must fail loudly rather than returning garbage --
    this is what makes the key non-editable from the Settings page.

    Drives APP_ENCRYPTION_KEY, the name crypto actually resolves first, and
    clears the legacy alias. Setting only the legacy name left the real key
    from the developer's .env in play, so both encrypt and decrypt used it
    and nothing raised."""
    monkeypatch.setattr(crypto.settings, "BANK_TOKEN_ENCRYPTION_KEY", None, raising=False)

    monkeypatch.setattr(crypto.settings, "APP_ENCRYPTION_KEY", Fernet.generate_key().decode(), raising=False)
    ciphertext = crypto.encrypt("secret")

    monkeypatch.setattr(crypto.settings, "APP_ENCRYPTION_KEY", Fernet.generate_key().decode(), raising=False)
    with pytest.raises(EncryptionNotConfigured):
        crypto.decrypt(ciphertext)
