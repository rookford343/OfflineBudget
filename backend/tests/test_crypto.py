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
    with pytest.raises(EncryptionNotConfigured):
        crypto.encrypt("secret")


def test_decrypt_raises_on_wrong_key(monkeypatch):
    monkeypatch.setattr(crypto.settings, "BANK_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    ciphertext = crypto.encrypt("secret")
    monkeypatch.setattr(crypto.settings, "BANK_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    with pytest.raises(EncryptionNotConfigured):
        crypto.decrypt(ciphertext)
