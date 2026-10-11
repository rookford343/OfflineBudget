"""Security regression tests: one per fixed Bandit (ruff S-rule) finding or
security defect. Each feeds the previously-unsafe input and asserts the code
now refuses or neutralizes it.

  - S105 JWT_SECRET: a missing secret, or the one published in this public
    repo, must never sign tokens; the app generates a random one instead.
  - S110 audit middleware: a failing audit write is logged, never silently
    swallowed, and never breaks the request it was auditing.
"""
import logging
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.config import Settings, _PUBLISHED_DEFAULT_SECRET
from backend.middleware import AuditMiddleware


@pytest.mark.parametrize("configured", [None, "", _PUBLISHED_DEFAULT_SECRET])
def test_jwt_secret__missing_or_published_default__is_replaced_by_a_random_one(monkeypatch, configured):
    if configured is None:
        monkeypatch.delenv("JWT_SECRET", raising=False)
    else:
        monkeypatch.setenv("JWT_SECRET", configured)
    first = Settings(_env_file=None)
    second = Settings(_env_file=None)
    assert first.JWT_SECRET not in ("", _PUBLISHED_DEFAULT_SECRET)
    assert len(first.JWT_SECRET) >= 32
    assert first.JWT_SECRET != second.JWT_SECRET


def test_jwt_secret__configured_value__is_kept(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "a-real-operator-chosen-secret-value-1234567890")
    assert Settings(_env_file=None).JWT_SECRET == "a-real-operator-chosen-secret-value-1234567890"


def _audited_app():
    app = FastAPI()
    app.add_middleware(AuditMiddleware)

    @app.post("/thing")
    def thing():
        return {"ok": True}

    return app


@pytest.mark.parametrize("failure_point", ["open", "commit"])
def test_audit_middleware__audit_write_fails__request_succeeds_and_failure_is_logged(caplog, failure_point):
    class _BrokenSession:
        def add(self, _):
            pass

        def commit(self):
            raise RuntimeError("disk full")

        def close(self):
            pass

    def _session():
        if failure_point == "open":
            raise RuntimeError("database locked")
        return _BrokenSession()

    with patch("backend.middleware.SessionLocal", side_effect=_session), caplog.at_level(logging.WARNING):
        resp = TestClient(_audited_app()).post("/thing", json={})
    assert resp.status_code == 200
    assert any("Audit log write failed" in r.getMessage() for r in caplog.records)


# --- JWT handling (python-jose replaced by PyJWT: jose's algorithm-confusion
# CVE-2026-85394 and its unmaintained ecdsa/rsa dependencies). Tokens are
# built by hand so these hold whatever library sits underneath. ---
import base64
import hashlib
import hmac
import json
import time

from backend.auth import create_access_token, decode_token
from backend.config import settings


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _token(header: dict, payload: dict, secret: str | None = None, alg: str = "sha256") -> str:
    signing_input = f"{_b64(json.dumps(header).encode())}.{_b64(json.dumps(payload).encode())}"
    if secret is None:
        return signing_input + "."
    sig = hmac.new(secret.encode(), signing_input.encode(), getattr(hashlib, alg)).digest()
    return f"{signing_input}.{_b64(sig)}"


def _claims(**extra):
    return {"sub": "1", "username": "u", "exp": int(time.time()) + 3600, **extra}


def test_jwt__a_token_we_issued__round_trips():
    assert decode_token(create_access_token(7, "alice"))["sub"] == "7"


@pytest.mark.parametrize("token", [
    pytest.param(lambda: _token({"alg": "none", "typ": "JWT"}, _claims()), id="alg_none_unsigned"),
    pytest.param(lambda: _token({"alg": "HS256", "typ": "JWT"}, _claims(), secret="someone-elses-secret"), id="wrong_secret"),
    pytest.param(lambda: _token({"alg": "HS512", "typ": "JWT"}, _claims(), secret=settings.JWT_SECRET, alg="sha512"),
                 id="unexpected_algorithm"),
    pytest.param(lambda: _token({"alg": "HS256", "typ": "JWT"}, _claims(exp=int(time.time()) - 10),
                                secret=settings.JWT_SECRET), id="expired"),
    pytest.param(lambda: "not.a.jwt", id="garbage"),
])
def test_jwt__forged_or_stale_tokens__decode_to_nothing(token):
    assert decode_token(token()) == {}
