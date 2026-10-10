import base64
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch, MagicMock
import httpx
import pytest
from backend.services.simplefin_client import (
    claim_setup_token, fetch_accounts, fetch_transactions, SimpleFinError,
)


def test_claim_setup_token_returns_access_url():
    claim_url = "https://bridge.simplefin.org/simplefin/claim/abc123"
    setup_token = base64.b64encode(claim_url.encode()).decode()
    mock_resp = MagicMock()
    mock_resp.text = "https://user:pass@bridge.simplefin.org/simplefin"
    mock_resp.raise_for_status = lambda: None

    with patch("backend.services.simplefin_client.httpx.post", return_value=mock_resp) as mock_post:
        access_url = claim_setup_token(setup_token)

    assert access_url == "https://user:pass@bridge.simplefin.org/simplefin"
    mock_post.assert_called_once_with(claim_url, timeout=15.0)


def test_claim_setup_token_rejects_invalid_base64():
    with pytest.raises(SimpleFinError):
        claim_setup_token("!!!not-valid-base64!!!")


def test_claim_setup_token_raises_on_http_error():
    setup_token = base64.b64encode(b"https://bridge.simplefin.org/claim/x").decode()
    with patch("backend.services.simplefin_client.httpx.post", side_effect=httpx.HTTPError("boom")):
        with pytest.raises(SimpleFinError):
            claim_setup_token(setup_token)


def test_fetch_accounts_parses_balances():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = lambda: None
    mock_resp.json.return_value = {
        "accounts": [
            {"id": "acc-1", "name": "Checking", "org": {"name": "Chase"}, "balance": "1074.64", "currency": "USD"},
            {"id": "acc-2", "name": "Sapphire", "org": {"name": "Chase"}, "balance": "-500.00", "currency": "USD"},
        ]
    }
    with patch("backend.services.simplefin_client.httpx.get", return_value=mock_resp):
        accounts = fetch_accounts("https://user:pass@bridge.simplefin.org/simplefin")

    assert len(accounts) == 2
    assert accounts[0].id == "acc-1"
    assert accounts[0].balance == Decimal("1074.64")
    assert accounts[1].org_name == "Chase"


def test_fetch_transactions_returns_txns_and_balance():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = lambda: None
    mock_resp.json.return_value = {
        "accounts": [{
            "id": "acc-1", "balance": "980.44",
            "transactions": [
                {"id": "t1", "posted": 1723276800, "amount": "-46.45", "description": "MEIJER #123"},
                {"id": "t2", "posted": 1723190400, "amount": "2500.00", "payee": "ACME CORP PAYROLL"},
            ],
        }]
    }
    with patch("backend.services.simplefin_client.httpx.get", return_value=mock_resp):
        txns, balance, balance_date = fetch_transactions("https://access.url", "acc-1", datetime(2026, 8, 1))

    assert balance == Decimal("980.44")
    assert balance_date is None  # no balance-date in the response
    assert len(txns) == 2
    assert txns[0].amount == Decimal("-46.45")
    assert txns[0].description == "MEIJER #123"
    assert txns[1].description == "ACME CORP PAYROLL"  # falls back to payee when description missing


def test_fetch_transactions_parses_balance_date():
    """SimpleFIN's balance-date tells us when the returned balance was
    actually true at the institution -- can lag real-world posting by days,
    which is the root cause of stale credit-card balances after a payment.
    See backend/tests/test_bank_sync_service.py for how this is used."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = lambda: None
    mock_resp.json.return_value = {
        "accounts": [{
            "id": "acc-1", "balance": "980.44", "balance-date": 1723276800,
            "transactions": [],
        }]
    }
    with patch("backend.services.simplefin_client.httpx.get", return_value=mock_resp):
        txns, balance, balance_date = fetch_transactions("https://access.url", "acc-1", datetime(2026, 8, 1))

    assert balance_date == datetime.fromtimestamp(1723276800)


def test_fetch_transactions_tolerates_malformed_balance_date():
    """A garbage balance-date must not fail the whole sync -- it just falls
    back to None, same as when the field is absent entirely."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = lambda: None
    mock_resp.json.return_value = {
        "accounts": [{
            "id": "acc-1", "balance": "980.44", "balance-date": "not-a-timestamp",
            "transactions": [],
        }]
    }
    with patch("backend.services.simplefin_client.httpx.get", return_value=mock_resp):
        txns, balance, balance_date = fetch_transactions("https://access.url", "acc-1", datetime(2026, 8, 1))

    assert balance_date is None


def test_fetch_transactions_raises_when_account_missing():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = lambda: None
    mock_resp.json.return_value = {"accounts": []}
    with patch("backend.services.simplefin_client.httpx.get", return_value=mock_resp):
        with pytest.raises(SimpleFinError):
            fetch_transactions("https://access.url", "acc-missing", datetime(2026, 8, 1))


def test_fetch_accounts_raises_simplefinerror_on_http_error():
    with patch("backend.services.simplefin_client.httpx.get", side_effect=httpx.HTTPError("boom")):
        with pytest.raises(SimpleFinError):
            fetch_accounts("https://access.url")


def _mock_json(payload):
    mock_resp = MagicMock()
    mock_resp.raise_for_status = lambda: None
    mock_resp.json.return_value = payload
    return patch("backend.services.simplefin_client.httpx.get", return_value=mock_resp)


@pytest.mark.parametrize("extra", [
    pytest.param({}, id="missing_balance"),
    pytest.param({"balance": "not-a-number"}, id="non_numeric_balance"),
])
def test_fetch_accounts_raises_on_bad_balance(extra):
    account = {"id": "acc-1", "name": "Checking", "org": {"name": "Chase"}, "currency": "USD", **extra}
    with _mock_json({"accounts": [account]}):
        with pytest.raises(SimpleFinError):
            fetch_accounts("https://access.url")


_GOOD_TXN = {"id": "t1", "posted": 1723276800, "amount": "-46.45", "description": "MEIJER #123"}


@pytest.mark.parametrize("account_fields,txn_fields", [
    pytest.param({"balance": "980.44"}, {"posted": None}, id="missing_posted"),
    pytest.param({"balance": "980.44"}, {"posted": "not-a-timestamp"}, id="invalid_timestamp"),
    pytest.param({"balance": "980.44"}, {"amount": "not-a-number"}, id="non_numeric_amount"),
    pytest.param({}, {}, id="missing_account_balance"),
])
def test_fetch_transactions_raises_on_malformed_data(account_fields, txn_fields):
    txn = {k: v for k, v in {**_GOOD_TXN, **txn_fields}.items() if v is not None}
    with _mock_json({"accounts": [{"id": "acc-1", **account_fields, "transactions": [txn]}]}):
        with pytest.raises(SimpleFinError):
            fetch_transactions("https://access.url", "acc-1", datetime(2026, 8, 1))



def test_fetch_transactions_flags_pending_and_asks_for_them():
    """pending=1 is only sent when asked for; a pending record may arrive with
    no posted timestamp and must still parse, flagged pending."""
    payload = {"accounts": [{"id": "acc-1", "balance": "-300.00", "transactions": [
        dict(_GOOD_TXN),
        {"id": "p1", "pending": True, "transacted_at": 1723276800, "amount": "-40.00", "description": "PENDING SHOP"},
    ]}]}
    with _mock_json(payload) as get:
        txns, _, _ = fetch_transactions("https://access.url", "acc-1", datetime(2026, 8, 1), include_pending=True)
    assert get.call_args.kwargs["params"]["pending"] == 1
    assert [t.pending for t in txns] == [False, True]
    with _mock_json(payload) as get:
        fetch_transactions("https://access.url", "acc-1", datetime(2026, 8, 1))
    assert "pending" not in get.call_args.kwargs["params"]
