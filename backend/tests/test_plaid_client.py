"""Task 2 (Plaid sync): the Plaid HTTP client -- sign flip, description
fallback, sync pagination body, error mapping, rate limiting, env-driven
base URL, missing-config guard and the liabilities not-supported case. All
figures below are invented; the repo is public."""
import json
from decimal import Decimal

import httpx
import pytest

from backend.services.plaid_client import (
    PlaidError,
    PlaidNotConfigured,
    PlaidRateLimited,
    create_link_token,
    exchange_public_token,
    get_accounts,
    get_card_statements,
    get_last_successful_update,
    sync_page,
)

_FAKE_SECRET = "test-invented-secret-9f3c"  # noqa: S105 -- invented test fixture, not a real credential
_FAKE_ACCESS_TOKEN = "access-sandbox-invented-123abc"  # noqa: S105 -- invented test fixture


@pytest.fixture(autouse=True)
def _plaid_configured(monkeypatch):
    """Every test gets a configured client by default; the
    test_missing_keys_raise_not_configured tests override this."""
    monkeypatch.setattr("backend.services.plaid_client.settings.PLAID_CLIENT_ID", "test-client-id")
    monkeypatch.setattr("backend.services.plaid_client.settings.PLAID_SECRET", _FAKE_SECRET)
    monkeypatch.setattr("backend.services.plaid_client.settings.PLAID_ENV", "production")


def _json_transport(body: dict, *, status_code: int = 200, capture: dict | None = None):
    """A MockTransport that always returns `body` as JSON, optionally
    recording the outgoing request (url + decoded JSON) into `capture`."""
    def handler(request: httpx.Request) -> httpx.Response:
        if capture is not None:
            capture["url"] = str(request.url)
            capture["body"] = json.loads(request.content)
        return httpx.Response(status_code, json=body)
    return httpx.MockTransport(handler)


def test_amount_sign_flipped():
    """Plaid reports money out as positive; the app's checking convention is
    positive = credit, so the client flips the sign exactly once."""
    body = {
        "added": [
            {
                "transaction_id": "t1", "account_id": "a1", "date": "2026-10-01",
                "authorized_date": None, "amount": 12.5, "name": "Coffee Shop",
                "original_description": None, "merchant_name": None, "pending": False,
            },
            {
                "transaction_id": "t2", "account_id": "a1", "date": "2026-10-02",
                "authorized_date": None, "amount": -3.0, "name": "Refund",
                "original_description": None, "merchant_name": None, "pending": False,
            },
        ],
        "modified": [], "removed": [], "next_cursor": "cursor-1", "has_more": False,
    }
    page = sync_page(_FAKE_ACCESS_TOKEN, None, transport=_json_transport(body))
    assert page.added[0].amount == Decimal("-12.50")
    assert page.added[1].amount == Decimal("3.00")


@pytest.mark.parametrize("bad_date", ["", "not-a-date"])
def test_malformed_date_raises_malformed_response(bad_date):
    """A transaction's `date` is required. A bad value must raise, not land
    silently as `date=None` on the dataclass."""
    body = {
        "added": [
            {
                "transaction_id": "t1", "account_id": "a1", "date": bad_date,
                "authorized_date": None, "amount": 5.0, "name": "Bad Date Row",
                "original_description": None, "merchant_name": None, "pending": False,
            },
        ],
        "modified": [], "removed": [], "next_cursor": "cursor-1", "has_more": False,
    }
    with pytest.raises(PlaidError) as exc_info:
        sync_page(_FAKE_ACCESS_TOKEN, None, transport=_json_transport(body))
    assert exc_info.value.code == "MALFORMED_RESPONSE"


def test_description_prefers_original():
    """original_description wins when present; name is only the fallback."""
    body = {
        "added": [
            {
                "transaction_id": "t1", "account_id": "a1", "date": "2026-10-01",
                "authorized_date": None, "amount": 5.0,
                "name": "Clean Name", "original_description": "RAW POS DEBIT 1234 CLEAN NAME",
                "merchant_name": None, "pending": False,
            },
            {
                "transaction_id": "t2", "account_id": "a1", "date": "2026-10-02",
                "authorized_date": None, "amount": 5.0,
                "name": "Fallback Name", "original_description": None,
                "merchant_name": None, "pending": False,
            },
        ],
        "modified": [], "removed": [], "next_cursor": "cursor-1", "has_more": False,
    }
    page = sync_page(_FAKE_ACCESS_TOKEN, None, transport=_json_transport(body))
    assert page.added[0].description == "RAW POS DEBIT 1234 CLEAN NAME"
    assert page.added[1].description == "Fallback Name"


def test_sync_page_sends_cursor_and_options():
    capture: dict = {}
    body = {"added": [], "modified": [], "removed": [], "next_cursor": "cursor-2", "has_more": False}
    sync_page(_FAKE_ACCESS_TOKEN, "cursor-1", transport=_json_transport(body, capture=capture))
    assert capture["body"]["cursor"] == "cursor-1"
    assert capture["body"]["count"] == 500
    assert capture["body"]["options"]["include_original_description"] is True


def test_error_body_mapped():
    """A 400 with an ITEM_LOGIN_REQUIRED body raises PlaidError carrying that
    code, and str() never contains the secret or the access token."""
    body = {"error_code": "ITEM_LOGIN_REQUIRED", "error_message": "the login details are no longer valid"}
    with pytest.raises(PlaidError) as exc_info:
        get_accounts(_FAKE_ACCESS_TOKEN, transport=_json_transport(body, status_code=400))
    assert exc_info.value.code == "ITEM_LOGIN_REQUIRED"
    rendered = str(exc_info.value)
    assert _FAKE_SECRET not in rendered
    assert _FAKE_ACCESS_TOKEN not in rendered


def test_429_raises_rate_limited():
    body = {"error_code": "RATE_LIMIT_EXCEEDED", "error_message": "too many requests"}
    with pytest.raises(PlaidRateLimited):
        get_accounts(_FAKE_ACCESS_TOKEN, transport=_json_transport(body, status_code=429))


def test_base_url_from_env(monkeypatch):
    monkeypatch.setattr("backend.services.plaid_client.settings.PLAID_ENV", "sandbox")
    capture: dict = {}
    body = {"accounts": []}
    get_accounts(_FAKE_ACCESS_TOKEN, transport=_json_transport(body, capture=capture))
    assert capture["url"].startswith("https://sandbox.plaid.com/")


def test_missing_keys_raise_not_configured(monkeypatch):
    monkeypatch.setattr("backend.services.plaid_client.settings.PLAID_CLIENT_ID", None)

    def _never_called(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not make a network call when Plaid isn't configured")

    with pytest.raises(PlaidNotConfigured) as exc_info:
        get_accounts(_FAKE_ACCESS_TOKEN, transport=httpx.MockTransport(_never_called))
    assert str(exc_info.value) == (
        "NOT_CONFIGURED: Plaid isn't set up: add PLAID_CLIENT_ID and PLAID_SECRET to the backend .env"
    )


def test_liabilities_not_supported_returns_empty():
    body = {"error_code": "PRODUCTS_NOT_SUPPORTED", "error_message": "liabilities is not supported for this item"}
    statements = get_card_statements(_FAKE_ACCESS_TOKEN, transport=_json_transport(body, status_code=400))
    assert statements == []


def test_update_mode_link_token_has_no_products():
    capture: dict = {}
    body = {"link_token": "link-sandbox-invented-456", "expiration": "2026-10-26T00:00:00Z"}
    token = create_link_token(
        "user-1", access_token=_FAKE_ACCESS_TOKEN, transport=_json_transport(body, capture=capture),
    )
    assert token == "link-sandbox-invented-456"
    assert "products" not in capture["body"]
    assert "optional_products" not in capture["body"]
    assert capture["body"]["access_token"] == _FAKE_ACCESS_TOKEN


def test_new_link_token_requests_products_and_history():
    capture: dict = {}
    body = {"link_token": "link-sandbox-invented-789", "expiration": "2026-10-26T00:00:00Z"}
    create_link_token("user-1", transport=_json_transport(body, capture=capture))
    assert capture["body"]["products"] == ["transactions"]
    assert capture["body"]["optional_products"] == ["liabilities"]
    assert capture["body"]["transactions"]["days_requested"] == 90
    assert "access_token" not in capture["body"]


def test_exchange_public_token_returns_access_token_and_item_id():
    body = {"access_token": _FAKE_ACCESS_TOKEN, "item_id": "item-invented-1"}
    access_token, item_id = exchange_public_token("public-token-invented", transport=_json_transport(body))
    assert access_token == _FAKE_ACCESS_TOKEN
    assert item_id == "item-invented-1"


def test_get_last_successful_update_parses_timestamp():
    body = {"item": {}, "status": {"transactions": {"last_successful_update": "2026-10-24T11:00:00Z"}}}
    updated = get_last_successful_update(_FAKE_ACCESS_TOKEN, transport=_json_transport(body))
    assert updated is not None
    assert updated.year == 2026 and updated.month == 10 and updated.day == 24


def test_get_last_successful_update_none_when_missing():
    body = {"item": {}, "status": {"transactions": {"last_successful_update": None}}}
    assert get_last_successful_update(_FAKE_ACCESS_TOKEN, transport=_json_transport(body)) is None


def test_get_accounts_parses_balances():
    body = {
        "accounts": [
            {
                "account_id": "a1", "name": "Sapphire Card", "mask": "4321",
                "type": "credit", "subtype": "credit card",
                "balances": {"current": 420.5, "available": None, "limit": 5000},
            },
        ],
    }
    accounts = get_accounts(_FAKE_ACCESS_TOKEN, transport=_json_transport(body))
    assert len(accounts) == 1
    acct = accounts[0]
    assert acct.id == "a1"
    assert acct.current == Decimal("420.50")
    assert acct.available is None
    assert acct.limit == Decimal("5000.00")


def test_get_card_statements_parses_liabilities():
    body = {
        "liabilities": {
            "credit": [
                {
                    "account_id": "a1",
                    "last_statement_balance": 312.45,
                    "last_statement_issue_date": "2026-09-20",
                    "next_payment_due_date": "2026-10-15",
                    "minimum_payment_amount": 35.0,
                },
            ],
        },
    }
    statements = get_card_statements(_FAKE_ACCESS_TOKEN, transport=_json_transport(body))
    assert len(statements) == 1
    statement = statements[0]
    assert statement.account_id == "a1"
    assert statement.last_statement_balance == Decimal("312.45")
    assert statement.minimum_payment_amount == Decimal("35.00")
