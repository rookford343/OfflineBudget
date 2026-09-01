"""Thin client for the SimpleFIN Bridge protocol (https://www.simplefin.org/protocol.html).

SimpleFIN's amount convention matches OfflineBudget's ParsedRow convention:
positive = credit/income, negative = debit/charge. No sign flip needed.
"""
from __future__ import annotations
import base64
import binascii
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
import httpx


class SimpleFinError(Exception):
    """Raised on any SimpleFIN claim/fetch failure -- callers catch per-connection/per-account."""


@dataclass
class SimpleFinAccount:
    id: str
    name: str
    org_name: str
    balance: Decimal
    currency: str


@dataclass
class SimpleFinTransaction:
    id: str
    posted: datetime
    amount: Decimal
    description: str
    # The full, unmapped record SimpleFIN sent for this transaction --
    # everything above is a deliberately narrow projection of it. Always
    # populated by fetch_transactions (free, it's the dict already in hand);
    # whether it gets PERSISTED is a separate decision made by the caller
    # based on User.debug_capture_raw_bank_data. Defaulted to {} rather than
    # required so existing hand-built test fixtures that don't care about raw
    # capture keep constructing this the same way they always have.
    raw: dict = field(default_factory=dict)


def claim_setup_token(setup_token: str, timeout: float = 15.0) -> str:
    """Exchange a one-time SimpleFIN setup token for a permanent access URL.

    The setup token is base64 of a claim URL. POSTing to that URL (empty body)
    returns the access URL as the response body -- this exchange only works once.
    """
    try:
        claim_url = base64.b64decode(setup_token, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise SimpleFinError(f"Invalid setup token: {exc}") from exc

    try:
        resp = httpx.post(claim_url, timeout=timeout)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise SimpleFinError(f"Failed to claim setup token: {exc}") from exc

    access_url = resp.text.strip()
    if not access_url.startswith("http"):
        raise SimpleFinError("Claim response did not return a valid access URL")
    return access_url


def fetch_accounts(access_url: str, timeout: float = 15.0) -> list[SimpleFinAccount]:
    """Fetch account metadata + balances only (no transactions) -- used for the
    initial link-mapping step in Settings."""
    data = _get(access_url, params={"balances-only": "1"}, timeout=timeout)
    accounts = []
    for a in data.get("accounts", []):
        try:
            accounts.append(SimpleFinAccount(
                id=a["id"],
                name=a.get("name", "Unknown"),
                org_name=(a.get("org") or {}).get("name", ""),
                balance=Decimal(str(a["balance"])),
                currency=a.get("currency", "USD"),
            ))
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise SimpleFinError(f"SimpleFIN returned a malformed account record: {exc}") from exc
    return accounts


def fetch_transactions(
    access_url: str, account_id: str, since: datetime, timeout: float = 15.0,
) -> tuple[list[SimpleFinTransaction], Decimal, datetime | None]:
    """Fetch transactions for one account posted after `since`. Returns
    (transactions, current_balance, balance_date) -- SimpleFIN returns the
    account's live balance alongside its transactions in the same response.

    balance_date is SimpleFIN's own "balance-date" field: when the returned
    balance was actually true at the institution, which can lag real-world
    posting by days (a payment leaves checking immediately but a card
    issuer's own balance can take days to reflect it). None when the
    aggregator/institution doesn't supply it -- callers fall back to
    trusting the balance unconditionally, the pre-existing behavior."""
    params = {"account": account_id, "start-date": int(since.timestamp())}
    data = _get(access_url, params=params, timeout=timeout)
    accounts = data.get("accounts", [])
    if not accounts:
        raise SimpleFinError(f"SimpleFIN returned no data for account {account_id}")
    account = accounts[0]
    try:
        balance = Decimal(str(account["balance"]))
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise SimpleFinError(f"SimpleFIN returned a malformed account record: {exc}") from exc

    balance_date: datetime | None = None
    raw_balance_date = account.get("balance-date")
    if raw_balance_date is not None:
        try:
            balance_date = datetime.fromtimestamp(raw_balance_date)
        except (TypeError, ValueError, OSError):
            balance_date = None  # malformed balance-date shouldn't fail the whole sync

    txns = []
    for t in account.get("transactions", []):
        try:
            txns.append(SimpleFinTransaction(
                id=t["id"],
                posted=datetime.fromtimestamp(t["posted"]),
                amount=Decimal(str(t["amount"])),
                description=t.get("description") or t.get("payee") or "Unknown",
                raw=t,
            ))
        except (KeyError, TypeError, ValueError, InvalidOperation, OSError) as exc:
            raise SimpleFinError(f"SimpleFIN returned a malformed transaction record: {exc}") from exc
    return txns, balance, balance_date


def _get(access_url: str, params: dict, timeout: float) -> dict:
    try:
        resp = httpx.get(f"{access_url}/accounts", params=params, timeout=timeout)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise SimpleFinError(f"SimpleFIN request failed: {exc}") from exc
    try:
        return resp.json()
    except ValueError as exc:
        raise SimpleFinError(f"SimpleFIN returned invalid JSON: {exc}") from exc
