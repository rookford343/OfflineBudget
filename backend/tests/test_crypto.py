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


def test_adding_new_key_name_still_decrypts_legacy_secrets(monkeypatch):
    """Adding APP_ENCRYPTION_KEY to a deployment that already had
    BANK_TOKEN_ENCRYPTION_KEY must not strand existing secrets.

    Regression: `app_encryption_key` resolves APP_ENCRYPTION_KEY first, so
    introducing that name flipped which key was tried and every previously
    stored secret failed with "Stored token could not be decrypted -- key may
    have changed". Dan hit this on his live bank connection.
    """
    legacy_key = Fernet.generate_key().decode()
    monkeypatch.setattr(crypto.settings, "APP_ENCRYPTION_KEY", None, raising=False)
    monkeypatch.setattr(crypto.settings, "BANK_TOKEN_ENCRYPTION_KEY", legacy_key, raising=False)
    ciphertext = crypto.encrypt("simplefin-access-url")

    # The upgrade: a new primary key appears alongside the legacy one.
    monkeypatch.setattr(crypto.settings, "APP_ENCRYPTION_KEY", Fernet.generate_key().decode(), raising=False)
    assert crypto.decrypt(ciphertext) == "simplefin-access-url"


def test_reencrypt_under_primary_migrates_without_changing_plaintext(monkeypatch):
    legacy_key = Fernet.generate_key().decode()
    monkeypatch.setattr(crypto.settings, "APP_ENCRYPTION_KEY", None, raising=False)
    monkeypatch.setattr(crypto.settings, "BANK_TOKEN_ENCRYPTION_KEY", legacy_key, raising=False)
    old = crypto.encrypt("simplefin-access-url")

    primary_key = Fernet.generate_key().decode()
    monkeypatch.setattr(crypto.settings, "APP_ENCRYPTION_KEY", primary_key, raising=False)
    migrated = crypto.reencrypt_under_primary(old)

    assert crypto.decrypt(migrated) == "simplefin-access-url"
    # After migration the primary key alone must suffice, so retiring the
    # legacy name is safe.
    monkeypatch.setattr(crypto.settings, "BANK_TOKEN_ENCRYPTION_KEY", None, raising=False)
    assert crypto.decrypt(migrated) == "simplefin-access-url"
