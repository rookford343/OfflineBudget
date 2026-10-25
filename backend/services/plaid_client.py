"""Thin client for the Plaid API (https://plaid.com/docs/api/), built on httpx
-- no plaid-python SDK (see docs/superpowers/specs/2026-10-25-plaid-sync-design.md
for why).

Plaid's amount convention is the opposite of OfflineBudget's: Plaid reports a
positive amount for money leaving an account, OfflineBudget's checking rows
use positive = credit. The sign is flipped exactly once, here, in
`_parse_transaction`. Card balances are NOT flipped -- Plaid already reports
credit owed as positive, matching CreditCardTransaction's convention.

Every function takes an optional `transport` (an `httpx.BaseTransport`) so
tests can swap in `httpx.MockTransport` instead of hitting the network.
`PLAID_CLIENT_ID`/`PLAID_SECRET`/`PLAID_ENV` are read off `settings` inside
each call, never cached at import time, so tests can monkeypatch them."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import httpx

from backend.config import settings

_BASE_URLS = {
    "sandbox": "https://sandbox.plaid.com",
    "production": "https://production.plaid.com",
}

_TIMEOUT = 20.0


class PlaidError(Exception):
    """Raised on any Plaid API failure. `.code` and `.message` come only from
    Plaid's own `error_code`/`error_message` (or a short fixed string this
    client writes) -- never from the request body, so neither this nor any
    subclass can leak a secret or an access token."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class PlaidRateLimited(PlaidError):
    """Raised on HTTP 429, or Plaid's RATE_LIMIT_EXCEEDED error code."""


class PlaidNotConfigured(PlaidError):
    """Raised before any network call when PLAID_CLIENT_ID or PLAID_SECRET is
    unset."""


@dataclass
class PlaidTransaction:
    id: str
    account_id: str
    date: date
    authorized_date: date | None
    amount: Decimal
    description: str
    merchant_name: str | None
    pending: bool


@dataclass
class PlaidAccount:
    id: str
    name: str
    mask: str | None
    type: str
    subtype: str | None
    current: Decimal | None
    available: Decimal | None
    limit: Decimal | None


@dataclass
class PlaidCardStatement:
    account_id: str
    last_statement_balance: Decimal | None
    last_statement_issue_date: date | None
    next_payment_due_date: date | None
    minimum_payment_amount: Decimal | None


@dataclass
class PlaidSyncPage:
    added: list[PlaidTransaction]
    modified: list[PlaidTransaction]
    removed: list[str]
    next_cursor: str
    has_more: bool


def _money(value) -> Decimal | None:
    """A missing or null amount is None, never a crash -- callers decide
    whether that's acceptable for the field in question."""
    if value is None:
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def _parse_date(value) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _parse_transaction(raw: dict) -> PlaidTransaction:
    """`description` prefers `original_description`, falling back to `name`
    -- this keeps descriptions close to the bank's own text, matching
    SimpleFIN and CSV imports. `amount` is negated: Plaid's positive means
    money out, OfflineBudget's checking convention is positive = credit."""
    try:
        return PlaidTransaction(
            id=raw["transaction_id"],
            account_id=raw["account_id"],
            date=_parse_date(raw["date"]),
            authorized_date=_parse_date(raw.get("authorized_date")),
            amount=-_money(raw["amount"]),
            description=raw.get("original_description") or raw.get("name") or "",
            merchant_name=raw.get("merchant_name"),
            pending=bool(raw.get("pending", False)),
        )
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise PlaidError("MALFORMED_RESPONSE", "Plaid returned a malformed transaction record") from exc


def _post(path: str, body: dict, transport: httpx.BaseTransport | None) -> dict:
    """POST JSON to `{base_url}{path}` with `client_id`/`secret` merged into
    the body, as Plaid requires. Raises PlaidNotConfigured before building
    any client when the keys are missing, PlaidRateLimited on 429 or
    RATE_LIMIT_EXCEEDED, and PlaidError on any other failure -- network,
    non-JSON, or an `error_code` in the response body."""
    client_id = settings.PLAID_CLIENT_ID
    secret = settings.PLAID_SECRET
    if not client_id or not secret:
        raise PlaidNotConfigured(
            "NOT_CONFIGURED",
            "Plaid isn't set up: add PLAID_CLIENT_ID and PLAID_SECRET to the backend .env",
        )

    base_url = _BASE_URLS[settings.PLAID_ENV]
    payload = {"client_id": client_id, "secret": secret, **body}
    try:
        with httpx.Client(transport=transport, timeout=_TIMEOUT) as client:
            resp = client.post(f"{base_url}{path}", json=payload)
    except httpx.HTTPError as exc:
        raise PlaidError("NETWORK_ERROR", f"Plaid request failed: {type(exc).__name__}") from exc

    try:
        data = resp.json()
    except ValueError as exc:
        raise PlaidError("NETWORK_ERROR", "Plaid returned a response that was not valid JSON") from exc

    error_code = data.get("error_code") if isinstance(data, dict) else None
    error_message = (data.get("error_message") if isinstance(data, dict) else None) or "Plaid request failed"

    if resp.status_code == 429 or error_code == "RATE_LIMIT_EXCEEDED":
        raise PlaidRateLimited(error_code or "RATE_LIMIT_EXCEEDED", error_message)
    if error_code or resp.status_code >= 400:
        raise PlaidError(error_code or f"HTTP_{resp.status_code}", error_message)
    return data


def create_link_token(
    client_user_id: str, *, access_token: str | None = None, transport: httpx.BaseTransport | None = None,
) -> str:
    """New link: asks for transactions (required) plus liabilities
    (optional), and 90 days of history. Update mode (reconnect an existing
    item) sends the access token instead and no products at all -- Plaid
    already knows what the item is subscribed to."""
    body: dict = {
        "client_name": "OfflineBudget",
        "language": "en",
        "country_codes": ["US"],
        "user": {"client_user_id": client_user_id},
    }
    if access_token is not None:
        body["access_token"] = access_token
    else:
        body["products"] = ["transactions"]
        body["optional_products"] = ["liabilities"]
        body["transactions"] = {"days_requested": 90}

    data = _post("/link/token/create", body, transport)
    return data["link_token"]


def exchange_public_token(
    public_token: str, *, transport: httpx.BaseTransport | None = None,
) -> tuple[str, str]:
    data = _post("/item/public_token/exchange", {"public_token": public_token}, transport)
    return data["access_token"], data["item_id"]


def sync_page(
    access_token: str, cursor: str | None, *, transport: httpx.BaseTransport | None = None,
) -> PlaidSyncPage:
    """One page of `/transactions/sync`. The caller loops on `has_more` and
    decides when `next_cursor` is safe to persist -- this function never
    saves anything itself."""
    body = {
        "access_token": access_token,
        "cursor": cursor or "",
        "count": 500,
        "options": {"include_original_description": True},
    }
    data = _post("/transactions/sync", body, transport)
    try:
        removed = [r["transaction_id"] for r in data.get("removed", [])]
    except (KeyError, TypeError) as exc:
        raise PlaidError("MALFORMED_RESPONSE", "Plaid returned a malformed removed-transaction record") from exc

    return PlaidSyncPage(
        added=[_parse_transaction(t) for t in data.get("added", [])],
        modified=[_parse_transaction(t) for t in data.get("modified", [])],
        removed=removed,
        next_cursor=data.get("next_cursor", ""),
        has_more=bool(data.get("has_more", False)),
    )


def get_accounts(access_token: str, *, transport: httpx.BaseTransport | None = None) -> list[PlaidAccount]:
    data = _post("/accounts/get", {"access_token": access_token}, transport)
    accounts = []
    try:
        for a in data.get("accounts", []):
            balances = a.get("balances") or {}
            accounts.append(PlaidAccount(
                id=a["account_id"],
                name=a.get("name") or a.get("official_name") or "Account",
                mask=a.get("mask"),
                type=a.get("type") or "",
                subtype=a.get("subtype"),
                current=_money(balances.get("current")),
                available=_money(balances.get("available")),
                limit=_money(balances.get("limit")),
            ))
    except (KeyError, TypeError) as exc:
        raise PlaidError("MALFORMED_RESPONSE", "Plaid returned a malformed account record") from exc
    return accounts


def get_last_successful_update(
    access_token: str, *, transport: httpx.BaseTransport | None = None,
) -> datetime | None:
    data = _post("/item/get", {"access_token": access_token}, transport)
    raw = ((data.get("status") or {}).get("transactions") or {}).get("last_successful_update")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def get_card_statements(
    access_token: str, *, transport: httpx.BaseTransport | None = None,
) -> list[PlaidCardStatement]:
    """`/liabilities/get`. A link with no liability-eligible account (a
    checking-only item, or a product the current plan doesn't support) isn't
    an error from the caller's point of view -- it just has no statements."""
    try:
        data = _post("/liabilities/get", {"access_token": access_token}, transport)
    except PlaidError as exc:
        if not isinstance(exc, PlaidRateLimited) and exc.code in ("PRODUCTS_NOT_SUPPORTED", "NO_LIABILITY_ACCOUNTS"):
            return []
        raise

    credit = (data.get("liabilities") or {}).get("credit") or []
    statements = []
    try:
        for c in credit:
            statements.append(PlaidCardStatement(
                account_id=c["account_id"],
                last_statement_balance=_money(c.get("last_statement_balance")),
                last_statement_issue_date=_parse_date(c.get("last_statement_issue_date")),
                next_payment_due_date=_parse_date(c.get("next_payment_due_date")),
                minimum_payment_amount=_money(c.get("minimum_payment_amount")),
            ))
    except (KeyError, TypeError) as exc:
        raise PlaidError("MALFORMED_RESPONSE", "Plaid returned a malformed liability record") from exc
    return statements


def refresh_transactions(access_token: str, *, transport: httpx.BaseTransport | None = None) -> None:
    """Asks Plaid to fetch from the bank in the background. No webhook, no
    waiting here -- the next scheduled `/transactions/sync` call picks up
    whatever this produced."""
    _post("/transactions/refresh", {"access_token": access_token}, transport)


def remove_item(access_token: str, *, transport: httpx.BaseTransport | None = None) -> None:
    _post("/item/remove", {"access_token": access_token}, transport)
