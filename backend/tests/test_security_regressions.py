"""Security regression tests: one per fixed Bandit (ruff S-rule) finding or
security defect. Each feeds the previously-unsafe input and asserts the code
now refuses or neutralizes it.

  - S105 JWT_SECRET: a missing secret, or the one published in this public
    repo, must never sign tokens; the app generates a random one instead.
  - S110 audit middleware: a failing audit write is logged, never silently
    swallowed, and never breaks the request it was auditing.
  - bonus plans: another user's plan or item is 404, never readable or editable.
  - bonus allocation: another user's account in the allocation steps is 404, and nothing is saved.
  - checking level: another user's account (read, topped up, topped up from,
    or swept to) is 404, and no rule is saved.
  - plaid token in responses: the Plaid access token never appears in any
    /bank-sync response body across a link/sync/disconnect flow.
  - plaid token logging: the access token and PLAID_SECRET never appear in a
    log line across the exchange, sync and error paths.
  - plaid auth: /plaid/link-token, /plaid/exchange and /plaid/first-import
    are 401 anonymous and 403 for a View Only member.
  - plaid error detail: a failed /plaid/exchange's error detail never echoes
    the request body (the public token).
  - plaid link-token ownership: an update-mode link token for another user's
    connection is 404, never revealing that the connection exists.
  - bank-sync credential audit: /bank-sync/connect and /bank-sync/plaid/exchange
    request bodies (SimpleFIN setup_token, Plaid public_token) are never
    captured into audit_logs.body_summary, even when body capture works.
  - daily email since-lines: a pending merchant named like markup is HTML-escaped
    in the email body, never emitted as a tag.
  - delete account with change history: DELETE /auth/me for a user who has
    stored snapshots and readings succeeds and leaves none of them behind.
"""
import logging
from decimal import Decimal
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
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


def test_bonus_allocation_is_user_scoped(db_session):
    """Another user's account named in a bonus allocation step (or as the
    shortfall account) is 404, never silently saved against the caller's
    own allocation."""
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

    owner = models.User(username="ba-owner", hashed_password="x", display_name="O")
    other = models.User(username="ba-other", hashed_password="x", display_name="X")
    db_session.add_all([owner, other])
    db_session.flush()
    other_acct = models.Account(user_id=other.id, name="Other's Savings", type=models.AccountType.savings,
                                current_balance=Decimal("1"))
    db_session.add(other_acct)
    db_session.commit()

    body = {
        "steps": [{"account_id": other_acct.id, "kind": "fixed", "value": "1000"}],
        "shortfall_account_id": None, "shortfall_round_to": None,
    }
    assert client(owner).put("/bonus-plans/allocation", json=body).status_code == 404
    assert client(owner).get("/bonus-plans/allocation").json()["steps"] == []

    shortfall_body = {
        "steps": [], "shortfall_account_id": other_acct.id, "shortfall_round_to": None,
    }
    assert client(owner).put("/bonus-plans/allocation", json=shortfall_body).status_code == 404
    assert client(owner).get("/bonus-plans/allocation").json()["shortfall_account_id"] is None


def test_checking_level_is_user_scoped(db_session):
    """Another user's account named anywhere in /forecast/checking-level is
    404 -- never readable, and never saved into the caller's rule."""
    from decimal import Decimal
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend import models
    from backend.dependencies import get_current_user, get_db
    from backend.routers import forecast as forecast_router

    def client(user):
        app = FastAPI()
        app.include_router(forecast_router.router)
        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_current_user] = lambda: user
        return TestClient(app)

    owner = models.User(username="cl-owner", hashed_password="x", display_name="O")
    other = models.User(username="cl-other", hashed_password="x", display_name="X")
    db_session.add_all([owner, other])
    db_session.flush()
    mine = models.Account(user_id=owner.id, name="C", type=models.AccountType.checking, current_balance=Decimal("1"))
    my_savings = models.Account(user_id=owner.id, name="S", type=models.AccountType.savings, current_balance=Decimal("1"))
    theirs = models.Account(user_id=other.id, name="Other's Savings", type=models.AccountType.savings,
                            current_balance=Decimal("1"))
    db_session.add_all([mine, my_savings, theirs])
    db_session.commit()

    def body(**over):
        b = {"from_account_id": my_savings.id, "to_account_id": mine.id, "action_threshold": "500",
             "target_floor": "1000", "increment": "1000", "check_day": 1, "is_active": True,
             "sweep_ceiling": None, "sweep_to_account_id": None}
        b.update(over)
        return b

    assert client(owner).get(f"/forecast/checking-level?account_id={theirs.id}").status_code == 404
    assert client(owner).put("/forecast/checking-level", json=body(from_account_id=theirs.id)).status_code == 404
    assert client(owner).put("/forecast/checking-level", json=body(to_account_id=theirs.id)).status_code == 404
    assert client(owner).put("/forecast/checking-level",
                             json=body(sweep_ceiling="3000", sweep_to_account_id=theirs.id)).status_code == 404
    assert db_session.query(models.BufferTransferRule).count() == 0


# --- Plaid (2026-10-25): link, exchange, first import -----------------------
from backend import models
from backend.dependencies import get_current_user, get_db
from backend.routers import bank_sync as bank_sync_router_module
from backend.services import crypto
from backend.services.plaid_client import PlaidAccount, PlaidError
from backend.services.plaid_sync_service import PlaidSyncReport, sync_plaid_connection


def _plaid_app(db_session, user=None):
    app = FastAPI()
    app.include_router(bank_sync_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _plaid_user(db_session, username="dan-plaid"):
    user = models.User(username=username, hashed_password="x", display_name="D")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_plaid_token_never_in_responses(db_session, monkeypatch):
    """The Plaid access token is absent from every /bank-sync response body
    across a full exchange -> link-token -> accounts -> status -> first-import
    -> disconnect flow."""
    monkeypatch.setattr(crypto.settings, "BANK_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    user = _plaid_user(db_session)
    test_client = _plaid_app(db_session, user)

    secret_token = "secret-plaid-access-token-should-never-appear-in-any-response"
    plaid_accounts = [
        PlaidAccount(id="acc-1", name="Checking", mask="1111", type="depository", subtype="checking",
                     current=Decimal("10.00"), available=Decimal("10.00"), limit=None),
    ]
    responses = []

    with patch("backend.routers.bank_sync.exchange_public_token", return_value=(secret_token, "item-flow")), \
         patch("backend.routers.bank_sync.get_plaid_accounts", return_value=plaid_accounts):
        resp = test_client.post("/bank-sync/plaid/exchange", json={"public_token": "pub-flow"})
    responses.append(resp)
    connection_id = resp.json()["connection_id"]

    with patch("backend.routers.bank_sync.create_link_token", return_value="link-tok"):
        responses.append(test_client.post("/bank-sync/plaid/link-token", json={"connection_id": connection_id}))

    with patch("backend.routers.bank_sync.get_plaid_accounts", return_value=plaid_accounts):
        responses.append(test_client.get(f"/bank-sync/{connection_id}/accounts"))

    responses.append(test_client.get("/bank-sync/status"))

    report = PlaidSyncReport(imported=0, matched=0, ignored=0, rows=[])
    with patch("backend.routers.bank_sync.sync_plaid_connection", return_value=report):
        responses.append(test_client.post(f"/bank-sync/{connection_id}/plaid/first-import?confirm=false"))

    with patch("backend.routers.bank_sync.remove_item"):
        responses.append(test_client.delete(f"/bank-sync/{connection_id}"))

    for resp in responses:
        assert secret_token not in resp.text


def test_plaid_token_never_logged(caplog, db_session, monkeypatch):
    """Neither the Plaid access token nor PLAID_SECRET appears in a log line
    across the exchange (router), a real sync (plaid_sync_service, with only
    the network edge mocked), and an error path (a failing sync)."""
    monkeypatch.setattr(crypto.settings, "BANK_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "PLAID_SECRET", "plaid-secret-should-never-leak-9f8e7d")
    user = _plaid_user(db_session)
    test_client = _plaid_app(db_session, user)

    secret_token = "secret-plaid-access-token-should-never-be-logged-a1b2c3"

    with caplog.at_level(logging.DEBUG):
        with patch("backend.routers.bank_sync.exchange_public_token", return_value=(secret_token, "item-log")), \
             patch("backend.routers.bank_sync.get_plaid_accounts", return_value=[]):
            resp = test_client.post("/bank-sync/plaid/exchange", json={"public_token": "pub-log"})
        connection = db_session.get(models.BankConnection, resp.json()["connection_id"])

        import backend.services.plaid_client as plaid_client_module

        with patch.object(plaid_client_module, "sync_page",
                          return_value=plaid_client_module.PlaidSyncPage(
                              added=[], modified=[], removed=[], next_cursor="cursor-1", has_more=False,
                              transactions_update_status="HISTORICAL_UPDATE_COMPLETE")), \
             patch.object(plaid_client_module, "get_accounts", return_value=[]), \
             patch.object(plaid_client_module, "get_last_successful_update", return_value=None), \
             patch.object(plaid_client_module, "get_card_statements", return_value=[]), \
             patch.object(plaid_client_module, "refresh_transactions", return_value=None):
            sync_plaid_connection(db_session, connection, first_import=True)

        with patch.object(plaid_client_module, "sync_page",
                          side_effect=PlaidError("ITEM_LOGIN_REQUIRED", "reconnect needed")):
            with pytest.raises(PlaidError):
                sync_plaid_connection(db_session, connection)

    log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert secret_token not in log_text
    assert "plaid-secret-should-never-leak-9f8e7d" not in log_text


def test_plaid_endpoints_refuse_viewer_and_anonymous(db_session, monkeypatch):
    """/plaid/link-token, /plaid/exchange and /plaid/first-import are 401 with
    no token and 403 for a View Only member -- the same gate every other
    /bank-sync write already enforces via get_current_user."""
    monkeypatch.setattr(crypto.settings, "BANK_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    owner = _plaid_user(db_session, "owner-plaid-auth")
    viewer = models.User(username="viewer-plaid-auth", hashed_password="x", display_name="V",
                         role=models.UserRole.viewer, linked_to_user_id=owner.id)
    db_session.add(viewer)
    db_session.commit()
    db_session.refresh(viewer)

    connection = models.BankConnection(
        user_id=owner.id, provider="plaid", access_url_encrypted=crypto.encrypt("plaid-token"),
    )
    db_session.add(connection)
    db_session.commit()
    db_session.refresh(connection)

    test_client = _plaid_app(db_session)  # no get_current_user override: real auth runs

    def auth(user):
        return {"Authorization": f"Bearer {create_access_token(user.id, user.username)}"}

    calls = [
        ("post", "/bank-sync/plaid/link-token", {"connection_id": None}),
        ("post", "/bank-sync/plaid/exchange", {"public_token": "pub-1"}),
        ("post", f"/bank-sync/{connection.id}/plaid/first-import?confirm=false", None),
    ]
    for method, path, body in calls:
        kwargs = {"json": body} if body is not None else {}
        anon_resp = getattr(test_client, method)(path, **kwargs)
        assert anon_resp.status_code == 401, f"{path} should 401 anonymous, got {anon_resp.status_code}"

        viewer_resp = getattr(test_client, method)(path, headers=auth(viewer), **kwargs)
        assert viewer_resp.status_code == 403, f"{path} should 403 a viewer, got {viewer_resp.status_code}"


def test_plaid_error_detail_has_no_request_body(db_session, monkeypatch):
    """A mocked /plaid/exchange failure's error detail never echoes the
    request body (the public token) -- PlaidError's text comes only from
    Plaid's own error_code/error_message, never the request."""
    monkeypatch.setattr(crypto.settings, "BANK_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    user = _plaid_user(db_session, "dan-plaid-detail")
    test_client = _plaid_app(db_session, user)

    secret_public_token = "public-token-should-not-leak-into-the-error-abc123"
    with patch("backend.routers.bank_sync.exchange_public_token",
               side_effect=PlaidError("INVALID_PUBLIC_TOKEN", "the public token provided was invalid")):
        resp = test_client.post("/bank-sync/plaid/exchange", json={"public_token": secret_public_token})

    assert resp.status_code == 422
    assert secret_public_token not in resp.json()["detail"]


def test_plaid_link_token_other_users_connection_404(db_session, monkeypatch):
    """Requesting an update-mode link token for another user's connection is
    404 -- the ownership check never reveals that the connection exists."""
    monkeypatch.setattr(crypto.settings, "BANK_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    owner = _plaid_user(db_session, "owner-plaid-lt")
    other = _plaid_user(db_session, "other-plaid-lt")
    connection = models.BankConnection(
        user_id=owner.id, provider="plaid", access_url_encrypted=crypto.encrypt("plaid-token"),
    )
    db_session.add(connection)
    db_session.commit()
    db_session.refresh(connection)

    test_client = _plaid_app(db_session, other)

    with patch("backend.routers.bank_sync.create_link_token") as mock_create:
        resp = test_client.post("/bank-sync/plaid/link-token", json={"connection_id": connection.id})

    assert resp.status_code == 404
    mock_create.assert_not_called()


# --- Bank-sync credential bodies kept out of the audit log (2026-10-25) -----
import asyncio

from starlette.requests import Request as _StarletteRequest
from starlette.responses import Response as _StarletteResponse


def _unread_body_request(path: str, body: bytes) -> _StarletteRequest:
    """A Starlette Request whose ASGI body is still sitting unread in the
    receive channel -- i.e. what AuditMiddleware.dispatch sees whenever the
    downstream handler (unlike the stub below) hasn't consumed it first."""
    consumed = False

    async def receive():
        nonlocal consumed
        if consumed:
            return {"type": "http.disconnect"}
        consumed = True
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": [],
        "query_string": b"",
    }
    return _StarletteRequest(scope, receive=receive)


async def _call_next_leaves_body_unread(request: _StarletteRequest) -> _StarletteResponse:
    """Stands in for the real downstream app, except it never reads the
    request body -- isolating this test from the real consumed-stream bug
    so body capture succeeds and the skip list can be proven on its own
    terms, independent of whether that bug is ever fixed."""
    return _StarletteResponse(status_code=200)


@pytest.mark.parametrize("path,field,token", [
    pytest.param("/bank-sync/connect", "setup_token",
                 "simplefin-setup-token-should-never-be-logged-a1b2c3", id="simplefin_connect"),
    pytest.param("/bank-sync/plaid/exchange", "public_token",
                 "plaid-public-token-should-never-be-logged-d4e5f6", id="plaid_exchange"),
])
def test_audit_middleware__bank_sync_credential_body__never_captured(db_session, path, field, token):
    """Even when body capture works (the stub call_next above leaves the
    body unread, unlike the real app), /bank-sync/connect and
    /bank-sync/plaid/exchange are in _SKIP_BODY_PATHS so their credential
    body never reaches audit_logs.body_summary. A non-skipped control path
    exercised in the same setup DOES get a body_summary, proving capture
    works in this harness -- so the None asserted below is the skip list at
    work, not a harness artifact that would pass regardless."""
    middleware = AuditMiddleware(app=None)

    with patch("backend.middleware.SessionLocal", return_value=db_session):
        asyncio.run(middleware.dispatch(
            _unread_body_request(path, json.dumps({field: token}).encode()),
            _call_next_leaves_body_unread,
        ))

        control_path = "/some/other/mutating-endpoint"
        asyncio.run(middleware.dispatch(
            _unread_body_request(control_path, b'{"note": "ordinary body"}'),
            _call_next_leaves_body_unread,
        ))

    skipped_row = db_session.query(models.AuditLog).filter_by(path=path).one()
    assert skipped_row.body_summary is None

    control_row = db_session.query(models.AuditLog).filter_by(path=control_path).one()
    assert control_row.body_summary == '{"note": "ordinary body"}'

    for row in db_session.query(models.AuditLog).all():
        assert token not in (row.body_summary or "")
        assert token not in (row.username or "")


# ── Change history: per-user scoping ─────────────────────────────────────────

def _history_user(db, name):
    user = models.User(username=name, hashed_password="x", display_name=name)
    db.add(user)
    db.commit()
    return user


def _history_snapshot(db, user, key, value, sources, hour):
    import json as _json
    from datetime import datetime
    from backend import schemas
    row = schemas.ExplainRow(op="start", label="Base", amount=Decimal(value), children=[], informational_children=[])
    explain = schemas.Explanation(title="T", result=Decimal(value), rows=[row]).model_dump_json()
    snap = models.MetricSnapshot(
        user_id=user.id, taken_at=datetime(2026, 11, 2, hour, 0), trigger="sync", calc_version=12,
        as_of=date(2026, 11, 2), sources_json=_json.dumps(sources, sort_keys=True),
    )
    snap.readings = [models.MetricReading(metric_key=key, label=key, value=Decimal(value), explain_json=explain)]
    db.add(snap)
    db.commit()
    return snap


def test_history_is_scoped_to_the_caller(db_session):
    """Another user's card key is 404 (never revealing it exists), and their
    DELETE /history removes only their own snapshots."""
    from backend.dependencies import get_current_user, get_db
    from backend.routers import history as history_router

    def client(user):
        app = FastAPI()
        app.include_router(history_router.router)
        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_current_user] = lambda: user
        return TestClient(app)

    owner, other = _history_user(db_session, "hist-owner"), _history_user(db_session, "hist-other")
    card = models.CreditCard(user_id=owner.id, name="Visa", credit_limit=Decimal("5000"), statement_day=20,
                             due_day=10, is_active=True, current_balance=Decimal("0"), balance_due=Decimal("0"))
    db_session.add(card)
    db_session.commit()
    key = f"card_payment:{card.id}"
    src = {"card_pending": [], "checking_pending": [], "max_txn_id": 0, "max_card_txn_id": 0}
    _history_snapshot(db_session, owner, key, "100.00", src, 12)
    _history_snapshot(db_session, owner, key, "130.00", src, 18)
    assert client(owner).get(f"/history/{key}").status_code == 200
    assert client(other).get(f"/history/{key}").status_code == 404
    assert client(other).delete("/history").json() == {"deleted": 0}
    assert db_session.query(models.MetricSnapshot).filter_by(user_id=owner.id).count() == 2
    assert client(owner).get(f"/history/{key}").status_code == 200


def test_history_causes_never_name_another_users_rows(db_session):
    """A second user's card transactions, checking transactions and pending rows
    (created between the first user's two snapshots) never appear in the first
    user's causes."""
    from datetime import datetime
    from backend.services.metric_diff import changes_for

    owner, other = _history_user(db_session, "cause-owner"), _history_user(db_session, "cause-other")
    owner_checking = models.Account(user_id=owner.id, name="Owner Checking", type=models.AccountType.checking,
                                    current_balance=Decimal("1000"))
    other_checking = models.Account(user_id=other.id, name="Other Checking", type=models.AccountType.checking,
                                    current_balance=Decimal("1000"))
    db_session.add_all([owner_checking, other_checking])
    other_card = models.CreditCard(user_id=other.id, name="Other Card", credit_limit=Decimal("5000"),
                                   statement_day=20, due_day=10, is_active=True,
                                   current_balance=Decimal("0"), balance_due=Decimal("0"))
    db_session.add(other_card)
    db_session.commit()
    secret = "OtherUserSecretMerchant"
    db_session.add_all([
        models.CreditCardTransaction(card_id=other_card.id, user_id=other.id, date=date(2026, 11, 2),
                                     amount=Decimal("77.00"), merchant=secret, created_at=datetime(2026, 11, 2, 15, 0)),
        models.Transaction(user_id=other.id, account_id=other_checking.id, date=date(2026, 11, 2),
                           amount=Decimal("-88.00"), description=secret, is_actual=True,
                           created_at=datetime(2026, 11, 2, 15, 0)),
        # Even a row of theirs pointing at the owner's account must stay out.
        models.Transaction(user_id=other.id, account_id=owner_checking.id, date=date(2026, 11, 2),
                           amount=Decimal("-99.00"), description=secret, is_actual=True,
                           created_at=datetime(2026, 11, 2, 15, 0)),
        models.CardPendingTransaction(user_id=other.id, card_id=other_card.id, external_id="x1", date=date(2026, 11, 2),
                                      synced_at=datetime(2026, 11, 2, 12, 0),
                                      merchant=secret, amount=Decimal("55.00")),
    ])
    db_session.commit()
    base = {"card_pending": [], "checking_pending": [], "max_txn_id": 0, "max_card_txn_id": 0}
    later = {
        "card_pending": [], "checking_pending": [],
        "max_txn_id": db_session.query(models.Transaction).count() + 100,
        "max_card_txn_id": db_session.query(models.CreditCardTransaction).count() + 100,
    }
    _history_snapshot(db_session, owner, "available_to_spend", "1000.00", base, 12)
    _history_snapshot(db_session, owner, "available_to_spend", "900.00", later, 18)
    changes = changes_for(db_session, owner.id, "available_to_spend", 30)
    assert len(changes) == 1
    assert secret not in changes[0].summary
    assert all(secret not in c.text for c in changes[0].causes)
    assert [c.text for c in changes[0].causes] == ["Base −$100.00"]  # the receipt line only


def test_since_line_carries_no_merchant_name(db_session, monkeypatch):
    """A bank-supplied merchant name must not reach the email through the
    since line: it is the signed amount only, so markup in a name cannot land."""
    from datetime import datetime
    from backend import models
    from backend.services.metric_diff import since_last_email
    from backend.services.metric_history import collect_headline_metrics
    from backend.services.summary_generator import generate_daily_summary
    from backend.tests.test_email_since_lines import _set_previous, _world, TODAY

    user, _ = _world(db_session, monkeypatch)
    visa = db_session.query(models.CreditCard).filter_by(name="Test Visa").one()
    db_session.add(models.CardPendingTransaction(
        user_id=user.id, card_id=visa.id, external_id="x-1", date=TODAY, amount=Decimal("10.00"),
        merchant="<b>&Co", synced_at=datetime(2026, 11, 2, 8, 0),
    ))
    db_session.commit()
    _set_previous(db_session, user, "safety_margin_week", Decimal("-400.00"))
    since = since_last_email(db_session, user, collect_headline_metrics(db_session, user, TODAY))
    assert since["safety_margin_week"] == "−$400.00 since last email"
    html, text = generate_daily_summary(db_session, user, since_lines=since)
    assert "<b>&Co" not in html and "&Co" not in html and "&Co" not in text


def test_delete_account_removes_the_users_change_history(db_session):
    """DELETE /auth/me must not trip the metric_snapshots foreign key: the
    user's snapshots and readings go with the account."""
    from backend.auth import hash_password
    from backend.dependencies import get_db, get_requester
    from backend.routers import auth as auth_router

    user = _history_user(db_session, "doomed")
    user.hashed_password = hash_password("correct-password")
    db_session.commit()
    src = {"card_pending": [], "checking_pending": [], "max_txn_id": 0, "max_card_txn_id": 0}
    _history_snapshot(db_session, user, "leftover", "100.00", src, 12)
    _history_snapshot(db_session, user, "leftover", "130.00", src, 18)
    keeper = _history_user(db_session, "keeper")
    _history_snapshot(db_session, keeper, "leftover", "5.00", src, 12)
    assert db_session.query(models.MetricReading).count() == 3

    app = FastAPI()
    app.include_router(auth_router.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_requester] = lambda: user
    resp = TestClient(app).request("DELETE", "/auth/me", json={"password": "correct-password"})

    assert 200 <= resp.status_code < 300
    assert db_session.query(models.MetricSnapshot).filter_by(user_id=user.id).count() == 0
    assert db_session.query(models.MetricSnapshot).count() == 1  # the other user's is untouched
    assert db_session.query(models.MetricReading).count() == 1
