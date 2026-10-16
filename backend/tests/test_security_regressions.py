"""Security regression tests: one per fixed Bandit (ruff S-rule) finding or
security defect. Each feeds the previously-unsafe input and asserts the code
now refuses or neutralizes it.

  - S105 JWT_SECRET: a missing secret, or the one published in this public
    repo, must never sign tokens; the app generates a random one instead.
  - S110 audit middleware: a failing audit write is logged, never silently
    swallowed, and never breaks the request it was auditing.
  - bonus plans: another user's plan or item is 404, never readable or editable.
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


# --- CodeQL alerts (2026-10-12) ---
# py/full-ssrf: a pasted SimpleFIN setup token decodes to the URL the server
# POSTs to, so a crafted token could aim the server at the home network.
# py/stack-trace-exposure: raw exception text reached the Wish List response.
# py/regex-injection: a user-supplied regex ran unbounded (catastrophic
# backtracking hangs a worker); rules now use escaped wildcards.
from datetime import date
from unittest.mock import MagicMock

from backend.services import simplefin_client
from backend.services.rules_engine import test_rule as rule_matches
from backend.services.simplefin_client import SimpleFinError, claim_setup_token


def _setup_token(url: str) -> str:
    return base64.b64encode(url.encode()).decode()


@pytest.mark.parametrize("claim_url", [
    "http://192.168.1.1/admin",
    "https://192.168.1.1/simplefin/claim/x",
    "https://evil.example/simplefin/claim/x",
    "https://beta-bridge.simplefin.org.evil.example/claim",
    "http://beta-bridge.simplefin.org/simplefin/claim/x",
    "file:///etc/passwd",
])
def test_claim_setup_token__url_off_simplefin__refused_before_any_request(claim_url):
    with patch.object(simplefin_client.httpx, "post") as post:
        with pytest.raises(SimpleFinError):
            claim_setup_token(_setup_token(claim_url))
    post.assert_not_called()


def test_claim_setup_token__simplefin_url__posts_there_and_checks_the_access_url():
    resp = MagicMock(text="https://user:pw@beta-bridge.simplefin.org/simplefin", raise_for_status=lambda: None)
    with patch.object(simplefin_client.httpx, "post", return_value=resp) as post:
        assert claim_setup_token(_setup_token("https://beta-bridge.simplefin.org/simplefin/claim/abc")) \
            == "https://user:pw@beta-bridge.simplefin.org/simplefin"
    assert post.call_args.args[0] == "https://beta-bridge.simplefin.org/simplefin/claim/abc"


def test_claim_setup_token__returned_access_url_off_simplefin__refused():
    resp = MagicMock(text="https://user:pw@10.0.0.5/simplefin", raise_for_status=lambda: None)
    with patch.object(simplefin_client.httpx, "post", return_value=resp):
        with pytest.raises(SimpleFinError):
            claim_setup_token(_setup_token("https://beta-bridge.simplefin.org/simplefin/claim/abc"))


def test_fetch__stored_access_url_off_simplefin__refused_before_any_request():
    with patch.object(simplefin_client.httpx, "get") as get:
        with pytest.raises(SimpleFinError):
            simplefin_client.fetch_accounts("https://user:pw@127.0.0.1:8000/simplefin")
    get.assert_not_called()


def test_wish_plan__unexpected_error__reaches_the_client_as_a_generic_message(db_session):
    from tests.test_wish_plan import _seed, _wish
    from backend.services import wish_plan
    from backend.services.wish_plan import build_plan
    u, acct = _seed(db_session)
    _wish(db_session, u, "Laptop", 0, "1000.00")
    db_session.commit()
    with patch.object(wish_plan, "monthly_payment", side_effect=ValueError("/srv/app/secret internals")):
        plan = build_plan(db_session, u, acct.id, date.today())
    error = plan["items"][0]["options"][0]["error"]
    assert error and "secret internals" not in error and "/srv" not in error


@pytest.mark.parametrize("pattern,description,expected", [
    pytest.param("SPOT*FY", "SPOTIFY USA 1234", True, id="star_matches_anything"),
    pytest.param("spotify", "SPOTIFY USA", True, id="case_insensitive"),
    pytest.param("SPOTIFY|NETFLIX", "NETFLIX.COM", False, id="pipe_is_literal_not_alternation"),
    pytest.param("A.B", "AXB", False, id="dot_is_literal"),
])
def test_rule_wildcard__matches_literally_except_star(pattern, description, expected):
    assert rule_matches(pattern, "regex", description) is expected


def test_rule_wildcard__catastrophic_regex__is_literal_and_fast():
    started = time.monotonic()
    assert rule_matches("(a+)+$", "regex", "a" * 40 + "!") is False
    assert time.monotonic() - started < 1


def test_bonus_plans_are_user_scoped(db_session):
    from datetime import date
    from decimal import Decimal
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend import models
    from backend.dependencies import get_current_user
    from backend.routers import bonus_plans as bonus_router

    def client(user):
        app = FastAPI()
        app.include_router(bonus_router.router)
        app.dependency_overrides[bonus_router.get_db] = lambda: db_session
        app.dependency_overrides[get_current_user] = lambda: user
        return TestClient(app)

    owner = models.User(username="bp-owner", hashed_password="x", display_name="O")
    other = models.User(username="bp-other", hashed_password="x", display_name="X")
    db_session.add_all([owner, other])
    db_session.flush()
    acct = models.Account(user_id=owner.id, name="C", type=models.AccountType.checking, current_balance=Decimal("1"))
    db_session.add(acct)
    db_session.flush()
    item = models.RecurringItem(user_id=owner.id, account_id=acct.id, name="Bonus", amount=Decimal("1"),
                                type=models.RecurringType.income, frequency=models.RecurringFrequency.yearly,
                                month_of_year=4, day_of_month=15, start_date=date(2026, 1, 1))
    db_session.add(item)
    db_session.commit()
    body = {"recurring_item_id": item.id, "target_pct": "20", "salary_lag_years": 1, "withholding_pct": "30", "years": []}
    assert client(other).post("/bonus-plans", json=body).status_code == 404
    plan_id = client(owner).post("/bonus-plans", json=body).json()["id"]
    assert client(other).put(f"/bonus-plans/{plan_id}", json=body).status_code == 404
    assert client(other).delete(f"/bonus-plans/{plan_id}").status_code == 404
    assert client(other).get("/bonus-plans").json() == []
