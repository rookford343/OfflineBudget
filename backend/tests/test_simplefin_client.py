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
            {"id": "acc-1", "name": "Checking", "org": {"name": "Chase"}, "balance": "1234.56", "currency": "USD"},
            {"id": "acc-2", "name": "Sapphire", "org": {"name": "Chase"}, "balance": "-500.00", "currency": "USD"},
        ]
    }
    with patch("backend.services.simplefin_client.httpx.get", return_value=mock_resp):
        accounts = fetch_accounts("https://user:pass@bridge.simplefin.org/simplefin")

    assert len(accounts) == 2
    assert accounts[0].id == "acc-1"
    assert accounts[0].balance == Decimal("1234.56")
    assert accounts[1].org_name == "Chase"


def test_fetch_transactions_returns_txns_and_balance():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = lambda: None
    mock_resp.json.return_value = {
        "accounts": [{
            "id": "acc-1", "balance": "980.44",
            "transactions": [
                {"id": "t1", "posted": 1723276800, "amount": "-52.90", "description": "MEIJER #123"},
                {"id": "t2", "posted": 1723190400, "amount": "2500.00", "payee": "ACME CORP PAYROLL"},
            ],
        }]
    }
    with patch("backend.services.simplefin_client.httpx.get", return_value=mock_resp):
        txns, balance, balance_date = fetch_transactions("https://access.url", "acc-1", datetime(2026, 8, 1))

    assert balance == Decimal("980.44")
    assert balance_date is None  # no balance-date in the response
    assert len(txns) == 2
    assert txns[0].amount == Decimal("-52.90")
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


def test_fetch_accounts_raises_on_missing_balance():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = lambda: None
    mock_resp.json.return_value = {
        "accounts": [
            {"id": "acc-1", "name": "Checking", "org": {"name": "Chase"}, "currency": "USD"},
        ]
    }
    with patch("backend.services.simplefin_client.httpx.get", return_value=mock_resp):
        with pytest.raises(SimpleFinError):
            fetch_accounts("https://access.url")


def test_fetch_accounts_raises_on_non_numeric_balance():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = lambda: None
    mock_resp.json.return_value = {
        "accounts": [
            {"id": "acc-1", "name": "Checking", "org": {"name": "Chase"}, "balance": "not-a-number", "currency": "USD"},
        ]
    }
    with patch("backend.services.simplefin_client.httpx.get", return_value=mock_resp):
        with pytest.raises(SimpleFinError):
            fetch_accounts("https://access.url")


def test_fetch_transactions_raises_on_missing_posted():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = lambda: None
    mock_resp.json.return_value = {
        "accounts": [{
            "id": "acc-1", "balance": "980.44",
            "transactions": [
                {"id": "t1", "amount": "-52.90", "description": "MEIJER #123"},
            ],
        }]
    }
    with patch("backend.services.simplefin_client.httpx.get", return_value=mock_resp):
        with pytest.raises(SimpleFinError):
            fetch_transactions("https://access.url", "acc-1", datetime(2026, 8, 1))


def test_fetch_transactions_raises_on_invalid_timestamp():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = lambda: None
    mock_resp.json.return_value = {
        "accounts": [{
            "id": "acc-1", "balance": "980.44",
            "transactions": [
                {"id": "t1", "posted": "not-a-timestamp", "amount": "-52.90", "description": "MEIJER #123"},
            ],
        }]
    }
    with patch("backend.services.simplefin_client.httpx.get", return_value=mock_resp):
        with pytest.raises(SimpleFinError):
            fetch_transactions("https://access.url", "acc-1", datetime(2026, 8, 1))


def test_fetch_transactions_raises_on_non_numeric_amount():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = lambda: None
    mock_resp.json.return_value = {
        "accounts": [{
            "id": "acc-1", "balance": "980.44",
            "transactions": [
                {"id": "t1", "posted": 1723276800, "amount": "not-a-number", "description": "MEIJER #123"},
            ],
        }]
    }
    with patch("backend.services.simplefin_client.httpx.get", return_value=mock_resp):
        with pytest.raises(SimpleFinError):
            fetch_transactions("https://access.url", "acc-1", datetime(2026, 8, 1))


def test_fetch_transactions_raises_on_missing_account_balance():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = lambda: None
    mock_resp.json.return_value = {
        "accounts": [{
            "id": "acc-1",
            "transactions": [
                {"id": "t1", "posted": 1723276800, "amount": "-52.90", "description": "MEIJER #123"},
            ],
        }]
    }
    with patch("backend.services.simplefin_client.httpx.get", return_value=mock_resp):
        with pytest.raises(SimpleFinError):
            fetch_transactions("https://access.url", "acc-1", datetime(2026, 8, 1))
