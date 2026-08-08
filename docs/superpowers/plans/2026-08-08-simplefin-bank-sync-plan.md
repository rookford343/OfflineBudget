# SimpleFIN Bank Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically pull checking and credit card transactions from the bank via SimpleFIN Bridge, landing them in OfflineBudget's existing ledger tables so the already-shipping weekly digest email reflects live data without Dan touching the app.

**Architecture:** A new `BankConnection`/`BankConnectionAccountLink` data model holds an encrypted SimpleFIN access URL and maps external accounts to existing local `Account`/`CreditCard` rows. A daily APScheduler job (and a manual "sync now" endpoint) pulls transactions per linked account and feeds them through the *existing* CSV-import pipeline (`import_service.build_preview` + `run_import`) so dedup, auto-categorization, and rules apply identically regardless of source — new transactions are tagged `source=bank_sync` and auto-accepted, no new review queue.

**Tech Stack:** FastAPI + SQLAlchemy + SQLite (existing), `cryptography` (Fernet, already in `requirements.txt`), `httpx` (already in `requirements.txt`), APScheduler (already in `requirements.txt`), React + TypeScript + TanStack Query (existing frontend stack).

## Global Constraints

- SimpleFIN Bridge only — not Plaid, despite `plaid-python` sitting unused in `requirements.txt`; do not build against it.
- No new Python dependencies: `cryptography>=42.0` and `httpx>=0.27.0` are already in `backend/requirements.txt`.
- Bank access token must be encrypted at rest via a dedicated Fernet key (`BANK_TOKEN_ENCRYPTION_KEY`), kept separate from `JWT_SECRET`. Never store or log it in plaintext.
- Synced transactions auto-accept straight into the ledger through the existing `import_service` pipeline (dedup + auto-categorizer + rules engine) — no manual review queue.
- Backend runs always-on (Dan's explicit choice for this build); daily sync fires via the existing APScheduler instance in `backend/main.py`, alongside the existing daily-summary and weekly-digest jobs. Scheduled-wake/shutdown is explicitly deferred, not part of this plan.
- Each linked account syncs independently — one broken link must log an error and continue, never abort the whole job.
- The weekly digest email (`backend/main.py:_send_weekly_digest`, `backend/config.py:DIGEST_RECIPIENTS`) already ships and is **out of scope** — do not modify it. It picks up synced transactions automatically because it reads the same `Transaction`/`CreditCardTransaction` tables.
- Repo convention: commit directly to `main`. No feature branches, no worktrees — this is a private single-author repo.
- Every commit follows TDD: failing test → implementation → passing test → commit.

---

### Task 1: Encryption key config + crypto helper

**Files:**
- Create: `backend/services/crypto.py`
- Create: `backend/tests/test_crypto.py`
- Modify: `backend/config.py`

**Interfaces:**
- Consumes: `backend.config.settings` (existing `Settings` singleton)
- Produces: `backend.services.crypto.encrypt(plaintext: str) -> str`, `backend.services.crypto.decrypt(ciphertext: str) -> str`, `backend.services.crypto.EncryptionNotConfigured` (Exception subclass) — all consumed by Task 4 (service) and Task 5 (router)

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_crypto.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_crypto.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.services.crypto'`

- [ ] **Step 3: Add the config setting**

In `backend/config.py`, add immediately after the existing `DIGEST_RECIPIENTS: str = ""` line:

```python
    BANK_TOKEN_ENCRYPTION_KEY: str | None = None  # Fernet key for encrypting SimpleFIN access URLs at rest
```

- [ ] **Step 4: Write the implementation**

```python
# backend/services/crypto.py
"""Fernet-based encryption for the SimpleFIN access URL, so a stolen budget.db
does not itself leak live bank access. Uses a key separate from JWT_SECRET
so rotating one never affects the other."""
from __future__ import annotations
from cryptography.fernet import Fernet, InvalidToken
from backend.config import settings


class EncryptionNotConfigured(Exception):
    """Raised when BANK_TOKEN_ENCRYPTION_KEY is unset or wrong -- callers must
    never fall back to storing the token in plaintext."""


def _fernet() -> Fernet:
    if not settings.BANK_TOKEN_ENCRYPTION_KEY:
        raise EncryptionNotConfigured("BANK_TOKEN_ENCRYPTION_KEY is not set in .env")
    try:
        return Fernet(settings.BANK_TOKEN_ENCRYPTION_KEY.encode())
    except Exception as exc:
        raise EncryptionNotConfigured(f"BANK_TOKEN_ENCRYPTION_KEY is not a valid Fernet key: {exc}") from exc


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise EncryptionNotConfigured("Stored token could not be decrypted -- key may have changed") from exc
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_crypto.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add backend/services/crypto.py backend/tests/test_crypto.py backend/config.py
git commit -m "Add Fernet encryption helper for bank connection tokens"
```

---

### Task 2: Data model — BankConnection, BankConnectionAccountLink, new source enums

**Files:**
- Modify: `backend/models.py`
- Create: `backend/tests/test_bank_connection_model.py`

**Interfaces:**
- Consumes: nothing new (pure SQLAlchemy models, same patterns as existing `models.py`)
- Produces: `models.BankConnectionStatus` (enum: `active`/`error`/`disconnected`), `models.BankConnection` (fields: `id, user_id, access_url_encrypted, status, last_synced_at, last_error, created_at`, relationship `links`), `models.BankConnectionAccountLink` (fields: `id, connection_id, simplefin_account_id, simplefin_account_name, local_account_id, local_credit_card_id, last_synced_at, created_at`), `models.TransactionSource.bank_sync`, `models.CardTransactionSource.bank_sync` — consumed by Tasks 4, 5, 6

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_bank_connection_model.py
from datetime import date
from decimal import Decimal
from backend import models


def _make_user(db):
    user = models.User(username="dan", hashed_password="x", display_name="Dan")
    db.add(user)
    db.flush()
    return user


def test_bank_connection_round_trip(db_session):
    user = _make_user(db_session)
    connection = models.BankConnection(user_id=user.id, access_url_encrypted="ciphertext")
    db_session.add(connection)
    db_session.flush()

    link = models.BankConnectionAccountLink(
        connection_id=connection.id,
        simplefin_account_id="acc-1",
        simplefin_account_name="Chase Checking",
    )
    db_session.add(link)
    db_session.commit()
    db_session.refresh(connection)

    assert connection.status == models.BankConnectionStatus.active
    assert len(connection.links) == 1
    assert connection.links[0].simplefin_account_id == "acc-1"


def test_disconnect_cascades_links(db_session):
    user = _make_user(db_session)
    connection = models.BankConnection(user_id=user.id, access_url_encrypted="x")
    db_session.add(connection)
    db_session.flush()
    link = models.BankConnectionAccountLink(connection_id=connection.id, simplefin_account_id="a", simplefin_account_name="A")
    db_session.add(link)
    db_session.commit()

    db_session.delete(connection)
    db_session.commit()

    assert db_session.query(models.BankConnectionAccountLink).count() == 0


def test_bank_sync_transaction_source_persists(db_session):
    user = _make_user(db_session)
    account = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking)
    db_session.add(account)
    db_session.flush()

    txn = models.Transaction(
        user_id=user.id, account_id=account.id, date=date(2026, 8, 1),
        amount=Decimal("-10.00"), description="Test", source=models.TransactionSource.bank_sync,
    )
    db_session.add(txn)
    db_session.commit()

    assert txn.source == models.TransactionSource.bank_sync


def test_bank_sync_card_transaction_source_persists(db_session):
    user = _make_user(db_session)
    card = models.CreditCard(user_id=user.id, name="Visa", credit_limit=Decimal("5000"), statement_day=15, due_day=1)
    db_session.add(card)
    db_session.flush()

    ct = models.CreditCardTransaction(
        card_id=card.id, user_id=user.id, date=date(2026, 8, 1),
        amount=Decimal("25.00"), merchant="Test Merchant", source=models.CardTransactionSource.bank_sync,
    )
    db_session.add(ct)
    db_session.commit()

    assert ct.source == models.CardTransactionSource.bank_sync
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_bank_connection_model.py -v`
Expected: FAIL with `AttributeError: module 'backend.models' has no attribute 'BankConnectionStatus'`

- [ ] **Step 3: Extend the source enums**

In `backend/models.py`, modify the two existing enum classes:

```python
class TransactionSource(str, PyEnum):
    manual = "manual"
    csv_import = "csv_import"
    forecast_generated = "forecast_generated"
    bank_sync = "bank_sync"


class CardTransactionSource(str, PyEnum):
    manual = "manual"
    csv_import = "csv_import"
    bank_sync = "bank_sync"
```

- [ ] **Step 4: Add the new models**

Append to the end of `backend/models.py`:

```python
# ── Bank Sync (SimpleFIN) ───────────────────────────────────────────────────

class BankConnectionStatus(str, PyEnum):
    active = "active"
    error = "error"
    disconnected = "disconnected"


class BankConnection(Base):
    __tablename__ = "bank_connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    access_url_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[BankConnectionStatus] = mapped_column(Enum(BankConnectionStatus), default=BankConnectionStatus.active, nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship()
    links: Mapped[list["BankConnectionAccountLink"]] = relationship(back_populates="connection", cascade="all, delete-orphan")


class BankConnectionAccountLink(Base):
    __tablename__ = "bank_connection_account_links"
    __table_args__ = (UniqueConstraint("connection_id", "simplefin_account_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    connection_id: Mapped[int] = mapped_column(Integer, ForeignKey("bank_connections.id"), nullable=False)
    simplefin_account_id: Mapped[str] = mapped_column(String(128), nullable=False)
    simplefin_account_name: Mapped[str] = mapped_column(String(256), nullable=False)
    local_account_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("accounts.id"))
    local_credit_card_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("credit_cards.id"))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    connection: Mapped["BankConnection"] = relationship(back_populates="links")
    local_account: Mapped["Account | None"] = relationship()
    local_credit_card: Mapped["CreditCard | None"] = relationship()
```

Note: these are brand-new tables, so `database.create_tables()` (`Base.metadata.create_all`) picks them up automatically — no `upgrade_schema()` entry needed. The two new enum values don't need a migration either; SQLAlchemy's `Enum` type on SQLite doesn't enforce a `CHECK` constraint by default in this codebase (confirmed by the existing pattern — no `upgrade_schema()` entries exist for any prior enum value additions).

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_bank_connection_model.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add backend/models.py backend/tests/test_bank_connection_model.py
git commit -m "Add BankConnection/BankConnectionAccountLink models and bank_sync source enums"
```

---

### Task 3: SimpleFIN client

**Files:**
- Create: `backend/services/simplefin_client.py`
- Create: `backend/tests/test_simplefin_client.py`

**Interfaces:**
- Consumes: `httpx` (existing dependency)
- Produces: `simplefin_client.SimpleFinError` (Exception), `simplefin_client.SimpleFinAccount` (dataclass: `id, name, org_name, balance: Decimal, currency`), `simplefin_client.SimpleFinTransaction` (dataclass: `id, posted: datetime, amount: Decimal, description`), `simplefin_client.claim_setup_token(setup_token: str, timeout: float = 15.0) -> str`, `simplefin_client.fetch_accounts(access_url: str, timeout: float = 15.0) -> list[SimpleFinAccount]`, `simplefin_client.fetch_transactions(access_url: str, account_id: str, since: datetime, timeout: float = 15.0) -> tuple[list[SimpleFinTransaction], Decimal]` — consumed by Task 4 (service) and Task 5 (router)

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_simplefin_client.py
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
        txns, balance = fetch_transactions("https://access.url", "acc-1", datetime(2026, 8, 1))

    assert balance == Decimal("980.44")
    assert len(txns) == 2
    assert txns[0].amount == Decimal("-52.90")
    assert txns[0].description == "MEIJER #123"
    assert txns[1].description == "ACME CORP PAYROLL"  # falls back to payee when description missing


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_simplefin_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.services.simplefin_client'`

- [ ] **Step 3: Write the implementation**

```python
# backend/services/simplefin_client.py
"""Thin client for the SimpleFIN Bridge protocol (https://www.simplefin.org/protocol.html).

SimpleFIN's amount convention matches OfflineBudget's ParsedRow convention:
positive = credit/income, negative = debit/charge. No sign flip needed.
"""
from __future__ import annotations
import base64
import binascii
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
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
    return [
        SimpleFinAccount(
            id=a["id"],
            name=a.get("name", "Unknown"),
            org_name=(a.get("org") or {}).get("name", ""),
            balance=Decimal(str(a["balance"])),
            currency=a.get("currency", "USD"),
        )
        for a in data.get("accounts", [])
    ]


def fetch_transactions(
    access_url: str, account_id: str, since: datetime, timeout: float = 15.0,
) -> tuple[list[SimpleFinTransaction], Decimal]:
    """Fetch transactions for one account posted after `since`. Returns
    (transactions, current_balance) -- SimpleFIN returns the account's live
    balance alongside its transactions in the same response."""
    params = {"account": account_id, "start-date": int(since.timestamp())}
    data = _get(access_url, params=params, timeout=timeout)
    accounts = data.get("accounts", [])
    if not accounts:
        raise SimpleFinError(f"SimpleFIN returned no data for account {account_id}")
    account = accounts[0]
    balance = Decimal(str(account["balance"]))
    txns = [
        SimpleFinTransaction(
            id=t["id"],
            posted=datetime.fromtimestamp(t["posted"]),
            amount=Decimal(str(t["amount"])),
            description=t.get("description") or t.get("payee") or "Unknown",
        )
        for t in account.get("transactions", [])
    ]
    return txns, balance


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_simplefin_client.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add backend/services/simplefin_client.py backend/tests/test_simplefin_client.py
git commit -m "Add SimpleFIN Bridge protocol client"
```

---

### Task 4: Bank sync orchestration service

**Files:**
- Create: `backend/services/bank_sync_service.py`
- Create: `backend/tests/test_bank_sync_service.py`

**Interfaces:**
- Consumes: `crypto.decrypt` (Task 1), `models.BankConnection`, `models.BankConnectionAccountLink`, `models.BankConnectionStatus`, `models.Account`, `models.CreditCard`, `models.User` (Task 2), `simplefin_client.fetch_transactions`, `simplefin_client.SimpleFinError` (Task 3), `csv_parser.ParsedRow(date, description, amount, is_transfer=False)`, `import_service.build_preview(db, user, parsed_rows) -> list[schemas.ImportPreviewRow]`, `import_service.run_import(db, user, rows: list[schemas.ImportConfirmRow], account_id, card_id) -> schemas.ImportConfirmResponse`, `schemas.ImportConfirmRow(date, description, amount, category_id=None, notes=None, recurring_item_id=None, is_transfer=False)` (all existing)
- Produces: `bank_sync_service.sync_connection(db: Session, connection: models.BankConnection) -> None`, `bank_sync_service.sync_all(db: Session) -> None` — consumed by Task 5 (router) and Task 6 (scheduler)

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_bank_sync_service.py
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch
from backend import models
from backend.services.bank_sync_service import sync_connection, sync_all
from backend.services.simplefin_client import SimpleFinTransaction, SimpleFinError


def _make_connection(db):
    user = models.User(username="dan", hashed_password="x", display_name="Dan")
    db.add(user)
    db.flush()
    account = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking, current_balance=Decimal("100.00"))
    db.add(account)
    db.flush()
    connection = models.BankConnection(user_id=user.id, access_url_encrypted="ciphertext")
    db.add(connection)
    db.flush()
    link = models.BankConnectionAccountLink(
        connection_id=connection.id, simplefin_account_id="acc-1",
        simplefin_account_name="Checking", local_account_id=account.id,
    )
    db.add(link)
    db.commit()
    return user, account, connection, link


def test_sync_connection_imports_transactions_and_updates_balance(db_session):
    user, account, connection, link = _make_connection(db_session)
    txns = [SimpleFinTransaction(id="t1", posted=datetime(2026, 8, 5), amount=Decimal("-52.90"), description="Meijer")]

    with patch("backend.services.bank_sync_service.decrypt", return_value="https://access.url"), \
         patch("backend.services.bank_sync_service.fetch_transactions", return_value=(txns, Decimal("47.10"))):
        sync_connection(db_session, connection)

    db_session.refresh(account)
    db_session.refresh(link)
    db_session.refresh(connection)
    assert account.current_balance == Decimal("47.10")
    assert link.last_synced_at is not None
    assert connection.last_error is None
    imported = db_session.query(models.Transaction).filter_by(
        account_id=account.id, source=models.TransactionSource.bank_sync,
    ).all()
    assert len(imported) == 1
    assert imported[0].description == "Meijer"
    assert imported[0].amount == Decimal("-52.90")


def test_sync_connection_dedupes_on_rerun(db_session):
    user, account, connection, link = _make_connection(db_session)
    txns = [SimpleFinTransaction(id="t1", posted=datetime(2026, 8, 5), amount=Decimal("-52.90"), description="Meijer")]

    with patch("backend.services.bank_sync_service.decrypt", return_value="https://access.url"), \
         patch("backend.services.bank_sync_service.fetch_transactions", return_value=(txns, Decimal("47.10"))):
        sync_connection(db_session, connection)
        sync_connection(db_session, connection)  # re-run, overlapping window re-fetches the same txn

    imported = db_session.query(models.Transaction).filter_by(account_id=account.id).all()
    assert len(imported) == 1


def test_sync_connection_isolates_per_account_failure(db_session):
    user, account, connection, link = _make_connection(db_session)
    account2 = models.Account(user_id=user.id, name="Savings", type=models.AccountType.savings, current_balance=Decimal("0"))
    db_session.add(account2)
    db_session.flush()
    link2 = models.BankConnectionAccountLink(
        connection_id=connection.id, simplefin_account_id="acc-2",
        simplefin_account_name="Savings", local_account_id=account2.id,
    )
    db_session.add(link2)
    db_session.commit()

    def fake_fetch(access_url, account_id, since):
        if account_id == "acc-1":
            raise SimpleFinError("bank unreachable")
        return [SimpleFinTransaction(id="t2", posted=datetime(2026, 8, 5), amount=Decimal("500.00"), description="Transfer")], Decimal("500.00")

    with patch("backend.services.bank_sync_service.decrypt", return_value="https://access.url"), \
         patch("backend.services.bank_sync_service.fetch_transactions", side_effect=fake_fetch):
        sync_connection(db_session, connection)

    db_session.refresh(account2)
    db_session.refresh(connection)
    assert account2.current_balance == Decimal("500.00")  # second link still synced
    assert connection.last_error == "bank unreachable"


def test_sync_connection_marks_status_error_when_all_links_fail(db_session):
    user, account, connection, link = _make_connection(db_session)

    with patch("backend.services.bank_sync_service.decrypt", return_value="https://access.url"), \
         patch("backend.services.bank_sync_service.fetch_transactions", side_effect=SimpleFinError("bank unreachable")):
        sync_connection(db_session, connection)

    db_session.refresh(connection)
    assert connection.status == models.BankConnectionStatus.error
    assert connection.last_error == "bank unreachable"


def test_sync_all_skips_inactive_connections(db_session):
    user, account, connection, link = _make_connection(db_session)
    connection.status = models.BankConnectionStatus.disconnected
    db_session.commit()

    with patch("backend.services.bank_sync_service.decrypt", return_value="https://access.url"), \
         patch("backend.services.bank_sync_service.fetch_transactions") as mock_fetch:
        sync_all(db_session)

    mock_fetch.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_bank_sync_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.services.bank_sync_service'`

- [ ] **Step 3: Write the implementation**

```python
# backend/services/bank_sync_service.py
"""Orchestrates SimpleFIN sync: pulls transactions for every linked account
and feeds them through the existing CSV-import pipeline so dedup, auto-
categorization, and rules apply identically regardless of source."""
from __future__ import annotations
import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from backend import models, schemas
from backend.services.crypto import decrypt
from backend.services.csv_parser import ParsedRow
from backend.services.import_service import build_preview, run_import
from backend.services.simplefin_client import fetch_transactions, SimpleFinError

logger = logging.getLogger(__name__)

_INITIAL_LOOKBACK_DAYS = 30  # first sync for a newly-linked account
_OVERLAP_DAYS = 3  # re-fetch a few days of overlap each sync so late-posting
                    # transactions aren't missed; import_service's dedup skips
                    # anything already imported


def sync_connection(db: Session, connection: models.BankConnection) -> None:
    """Sync every linked account for one BankConnection. Isolates failures per
    account so one broken link doesn't block the others."""
    user = db.get(models.User, connection.user_id)
    if not user:
        return

    access_url = decrypt(connection.access_url_encrypted)
    links = db.query(models.BankConnectionAccountLink).filter(
        models.BankConnectionAccountLink.connection_id == connection.id,
    ).all()

    any_success = False
    connection.last_error = None
    for link in links:
        try:
            _sync_link(db, user, access_url, link)
            any_success = True
        except SimpleFinError as exc:
            logger.error(
                "Bank sync failed for connection %s account %s: %s",
                connection.id, link.simplefin_account_id, exc,
            )
            connection.last_error = str(exc)

    # Any link succeeding brings the connection back to active (last_error is
    # still preserved for visibility even on a partial failure). Only a
    # connection where every link failed flips to `error`.
    if any_success:
        connection.status = models.BankConnectionStatus.active
    elif connection.last_error:
        connection.status = models.BankConnectionStatus.error
    connection.last_synced_at = datetime.utcnow()
    db.commit()


def _sync_link(db: Session, user: models.User, access_url: str, link: models.BankConnectionAccountLink) -> None:
    since = (
        link.last_synced_at - timedelta(days=_OVERLAP_DAYS)
        if link.last_synced_at
        else datetime.utcnow() - timedelta(days=_INITIAL_LOOKBACK_DAYS)
    )
    txns, balance = fetch_transactions(access_url, link.simplefin_account_id, since)

    parsed_rows = [
        ParsedRow(date=t.posted.date(), description=t.description, amount=t.amount)
        for t in txns
    ]

    if parsed_rows:
        preview_rows = build_preview(db, user, parsed_rows)
        confirm_rows = [
            schemas.ImportConfirmRow(
                date=r.date, description=r.description, amount=r.amount,
                category_id=r.category_id, is_transfer=r.is_transfer,
                recurring_item_id=r.suggested_recurring_item_id,
            )
            for r in preview_rows
        ]
        run_import(
            db, user, confirm_rows,
            account_id=link.local_account_id,
            card_id=link.local_credit_card_id,
        )

    if link.local_account_id:
        account = db.get(models.Account, link.local_account_id)
        if account:
            account.current_balance = balance
    elif link.local_credit_card_id:
        card = db.get(models.CreditCard, link.local_credit_card_id)
        if card:
            card.current_balance = balance

    link.last_synced_at = datetime.utcnow()
    db.commit()


def sync_all(db: Session) -> None:
    """Entry point for the daily scheduled job -- syncs every active connection."""
    connections = db.query(models.BankConnection).filter(
        models.BankConnection.status == models.BankConnectionStatus.active,
    ).all()
    for connection in connections:
        sync_connection(db, connection)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_bank_sync_service.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/services/bank_sync_service.py backend/tests/test_bank_sync_service.py
git commit -m "Add bank sync orchestration service"
```

---

### Task 5: Bank sync schemas + router (API surface)

**Files:**
- Modify: `backend/schemas.py`
- Create: `backend/routers/bank_sync.py`
- Create: `backend/tests/test_bank_sync_router.py`

**Interfaces:**
- Consumes: `crypto.encrypt`, `crypto.EncryptionNotConfigured` (Task 1), `models.BankConnection`, `models.BankConnectionAccountLink`, `models.BankConnectionStatus` (Task 2), `simplefin_client.claim_setup_token`, `simplefin_client.fetch_accounts`, `simplefin_client.SimpleFinError` (Task 3), `bank_sync_service.sync_connection` (Task 4), `dependencies.get_db`, `dependencies.get_current_user` (existing)
- Produces: `schemas.BankConnectionAccountOut`, `schemas.BankConnectionConnectRequest`, `schemas.BankConnectionConnectResponse`, `schemas.BankConnectionLinkRequest`, `schemas.BankConnectionLinkOut`, `schemas.BankConnectionStatusOut`, `schemas.BankSyncNowResponse`; `bank_sync.router` (FastAPI `APIRouter`, `prefix="/bank-sync"`) with `POST /bank-sync/connect`, `POST /bank-sync/{connection_id}/link`, `GET /bank-sync/status`, `POST /bank-sync/sync-now`, `DELETE /bank-sync/{connection_id}` — consumed by Task 6 (app registration) and Task 7 (frontend)

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_bank_sync_router.py
import base64
from decimal import Decimal
from unittest.mock import patch
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from cryptography.fernet import Fernet
from backend import models
from backend.routers import bank_sync as bank_sync_router_module
from backend.dependencies import get_db, get_current_user
from backend.services import crypto
from backend.services.simplefin_client import SimpleFinAccount


@pytest.fixture()
def client(db_session, monkeypatch):
    monkeypatch.setattr(crypto.settings, "BANK_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    user = models.User(username="dan", hashed_password="x", display_name="Dan")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    app = FastAPI()
    app.include_router(bank_sync_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app), user


def test_connect_stores_encrypted_token_and_returns_accounts(client, db_session):
    test_client, user = client
    claim_url = "https://bridge.simplefin.org/simplefin/claim/abc"
    setup_token = base64.b64encode(claim_url.encode()).decode()

    with patch("backend.routers.bank_sync.claim_setup_token", return_value="https://u:p@bridge.simplefin.org/simplefin"), \
         patch("backend.routers.bank_sync.fetch_accounts", return_value=[
             SimpleFinAccount(id="acc-1", name="Checking", org_name="Chase", balance=Decimal("100.00"), currency="USD"),
         ]):
        resp = test_client.post("/bank-sync/connect", json={"setup_token": setup_token})

    assert resp.status_code == 201
    body = resp.json()
    assert body["accounts"][0]["simplefin_account_id"] == "acc-1"

    stored = db_session.get(models.BankConnection, body["connection_id"])
    assert stored.access_url_encrypted != "https://u:p@bridge.simplefin.org/simplefin"
    assert crypto.decrypt(stored.access_url_encrypted) == "https://u:p@bridge.simplefin.org/simplefin"


def test_connect_fails_without_encryption_key(db_session, monkeypatch):
    monkeypatch.setattr(crypto.settings, "BANK_TOKEN_ENCRYPTION_KEY", None)
    user = models.User(username="dan", hashed_password="x", display_name="Dan")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    app = FastAPI()
    app.include_router(bank_sync_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    test_client = TestClient(app)

    setup_token = base64.b64encode(b"https://bridge.simplefin.org/claim/x").decode()
    with patch("backend.routers.bank_sync.claim_setup_token", return_value="https://u:p@bridge.simplefin.org/simplefin"):
        resp = test_client.post("/bank-sync/connect", json={"setup_token": setup_token})

    assert resp.status_code == 400


def test_link_creates_account_link(client, db_session):
    test_client, user = client
    account = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking)
    db_session.add(account)
    db_session.commit()
    db_session.refresh(account)
    connection = models.BankConnection(user_id=user.id, access_url_encrypted=crypto.encrypt("https://access.url"))
    db_session.add(connection)
    db_session.commit()
    db_session.refresh(connection)

    resp = test_client.post(f"/bank-sync/{connection.id}/link", json={
        "simplefin_account_id": "acc-1", "simplefin_account_name": "Checking",
        "local_account_id": account.id,
    })

    assert resp.status_code == 201
    assert resp.json()["local_account_id"] == account.id


def test_link_requires_local_target(client, db_session):
    test_client, user = client
    connection = models.BankConnection(user_id=user.id, access_url_encrypted=crypto.encrypt("https://access.url"))
    db_session.add(connection)
    db_session.commit()
    db_session.refresh(connection)

    resp = test_client.post(f"/bank-sync/{connection.id}/link", json={
        "simplefin_account_id": "acc-1", "simplefin_account_name": "Checking",
    })

    assert resp.status_code == 400


def test_status_lists_connections_with_links(client, db_session):
    test_client, user = client
    connection = models.BankConnection(user_id=user.id, access_url_encrypted=crypto.encrypt("https://access.url"), last_error="boom")
    db_session.add(connection)
    db_session.commit()
    db_session.refresh(connection)
    link = models.BankConnectionAccountLink(connection_id=connection.id, simplefin_account_id="acc-1", simplefin_account_name="Checking")
    db_session.add(link)
    db_session.commit()

    resp = test_client.get("/bank-sync/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["last_error"] == "boom"
    assert body[0]["links"][0]["simplefin_account_id"] == "acc-1"


def test_sync_now_invokes_service_and_reports_errors(client, db_session):
    test_client, user = client
    connection = models.BankConnection(user_id=user.id, access_url_encrypted=crypto.encrypt("https://access.url"))
    db_session.add(connection)
    db_session.commit()
    db_session.refresh(connection)

    def fake_sync(db, conn):
        conn.last_error = "simulated failure"

    with patch("backend.routers.bank_sync.sync_connection", side_effect=fake_sync):
        resp = test_client.post("/bank-sync/sync-now")

    assert resp.status_code == 200
    body = resp.json()
    assert body["synced_connections"] == 1
    assert body["errors"] == ["simulated failure"]


def test_disconnect_removes_connection(client, db_session):
    test_client, user = client
    connection = models.BankConnection(user_id=user.id, access_url_encrypted=crypto.encrypt("https://access.url"))
    db_session.add(connection)
    db_session.commit()
    db_session.refresh(connection)

    resp = test_client.delete(f"/bank-sync/{connection.id}")

    assert resp.status_code == 204
    assert db_session.get(models.BankConnection, connection.id) is None


def test_disconnect_rejects_other_users_connection(db_session):
    owner = models.User(username="dan", hashed_password="x", display_name="Dan")
    other = models.User(username="mallory", hashed_password="x", display_name="Mallory")
    db_session.add_all([owner, other])
    db_session.commit()
    connection = models.BankConnection(user_id=owner.id, access_url_encrypted="x")
    db_session.add(connection)
    db_session.commit()
    db_session.refresh(connection)

    app = FastAPI()
    app.include_router(bank_sync_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: other
    test_client = TestClient(app)

    resp = test_client.delete(f"/bank-sync/{connection.id}")

    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_bank_sync_router.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.routers.bank_sync'`

- [ ] **Step 3: Add the schemas**

In `backend/schemas.py`, update the models import at the top of the file:

```python
from backend.models import AccountType, CategoryType, RecurringType, ImportFormat, UserRole, RecurringFrequency, RuleField, RulePatternType, RuleAction, BankConnectionStatus
```

Then append near `ImportConfirmResponse` (end of the import section):

```python
# ── Bank Sync (SimpleFIN) ────────────────────────────────────────────────────

class BankConnectionAccountOut(BaseModel):
    """One SimpleFIN account discovered on the connection, for the mapping UI."""
    simplefin_account_id: str
    name: str
    org_name: str
    balance: Decimal
    currency: str


class BankConnectionConnectRequest(BaseModel):
    setup_token: str


class BankConnectionConnectResponse(BaseModel):
    connection_id: int
    accounts: list[BankConnectionAccountOut]


class BankConnectionLinkRequest(BaseModel):
    simplefin_account_id: str
    simplefin_account_name: str
    local_account_id: Optional[int] = None
    local_credit_card_id: Optional[int] = None


class BankConnectionLinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    simplefin_account_id: str
    simplefin_account_name: str
    local_account_id: Optional[int]
    local_credit_card_id: Optional[int]
    last_synced_at: Optional[datetime]


class BankConnectionStatusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: BankConnectionStatus
    last_synced_at: Optional[datetime]
    last_error: Optional[str]
    links: list[BankConnectionLinkOut]


class BankSyncNowResponse(BaseModel):
    synced_connections: int
    errors: list[str]
```

- [ ] **Step 4: Write the router**

```python
# backend/routers/bank_sync.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from backend import models, schemas
from backend.dependencies import get_db, get_current_user
from backend.services.crypto import encrypt, EncryptionNotConfigured
from backend.services.simplefin_client import claim_setup_token, fetch_accounts, SimpleFinError
from backend.services.bank_sync_service import sync_connection

router = APIRouter(prefix="/bank-sync", tags=["bank-sync"])


def _get_owned_connection(db: Session, user: models.User, connection_id: int) -> models.BankConnection:
    connection = db.get(models.BankConnection, connection_id)
    if not connection or connection.user_id != user.id:
        raise HTTPException(status_code=404, detail="Connection not found")
    return connection


@router.post("/connect", response_model=schemas.BankConnectionConnectResponse, status_code=status.HTTP_201_CREATED)
def connect(
    body: schemas.BankConnectionConnectRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    try:
        access_url = claim_setup_token(body.setup_token)
    except SimpleFinError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    try:
        encrypted = encrypt(access_url)
    except EncryptionNotConfigured as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    connection = models.BankConnection(user_id=user.id, access_url_encrypted=encrypted)
    db.add(connection)
    db.commit()
    db.refresh(connection)

    try:
        accounts = fetch_accounts(access_url)
    except SimpleFinError as exc:
        raise HTTPException(status_code=422, detail=f"Connected, but failed to list accounts: {exc}")

    return schemas.BankConnectionConnectResponse(
        connection_id=connection.id,
        accounts=[
            schemas.BankConnectionAccountOut(
                simplefin_account_id=a.id, name=a.name, org_name=a.org_name,
                balance=a.balance, currency=a.currency,
            )
            for a in accounts
        ],
    )


@router.post("/{connection_id}/link", response_model=schemas.BankConnectionLinkOut, status_code=status.HTTP_201_CREATED)
def link_account(
    connection_id: int,
    body: schemas.BankConnectionLinkRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    connection = _get_owned_connection(db, user, connection_id)
    if not body.local_account_id and not body.local_credit_card_id:
        raise HTTPException(status_code=400, detail="Provide either local_account_id or local_credit_card_id")

    link = models.BankConnectionAccountLink(
        connection_id=connection.id,
        simplefin_account_id=body.simplefin_account_id,
        simplefin_account_name=body.simplefin_account_name,
        local_account_id=body.local_account_id,
        local_credit_card_id=body.local_credit_card_id,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


@router.get("/status", response_model=list[schemas.BankConnectionStatusOut])
def status_list(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    return db.query(models.BankConnection).filter(models.BankConnection.user_id == user.id).all()


@router.post("/sync-now", response_model=schemas.BankSyncNowResponse)
def sync_now(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    connections = db.query(models.BankConnection).filter(
        models.BankConnection.user_id == user.id,
        models.BankConnection.status == models.BankConnectionStatus.active,
    ).all()
    errors = []
    for connection in connections:
        sync_connection(db, connection)
        if connection.last_error:
            errors.append(connection.last_error)
    return schemas.BankSyncNowResponse(synced_connections=len(connections), errors=errors)


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def disconnect(
    connection_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    connection = _get_owned_connection(db, user, connection_id)
    db.delete(connection)
    db.commit()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_bank_sync_router.py -v`
Expected: 8 passed

- [ ] **Step 6: Run the full backend test suite to confirm no regressions**

Run: `cd backend && python -m pytest -v`
Expected: all tests pass (existing suite + all new bank-sync tests)

- [ ] **Step 7: Commit**

```bash
git add backend/schemas.py backend/routers/bank_sync.py backend/tests/test_bank_sync_router.py
git commit -m "Add bank sync REST API (connect, link, status, sync-now, disconnect)"
```

---

### Task 6: Scheduler + app wiring

**Files:**
- Modify: `backend/main.py`

**Interfaces:**
- Consumes: `bank_sync_service.sync_all` (Task 4), `bank_sync.router` (Task 5)
- Produces: `POST /bank-sync/*` reachable on the running app; a daily `cron` job (`hour=5`) that calls `sync_all`

- [ ] **Step 1: Register the router**

In `backend/main.py`, add to the router imports (alongside the existing `from backend.routers import data as data_router_module` line):

```python
from backend.routers import bank_sync as bank_sync_router_module
```

Add to the `include_router` block (after `app.include_router(data_router_module.router)`):

```python
app.include_router(bank_sync_router_module.router)
```

- [ ] **Step 2: Add the scheduled job function**

Add near `_send_weekly_digest` (same file, module level):

```python
def _run_bank_sync() -> None:
    from backend.database import SessionLocal
    from backend.services.bank_sync_service import sync_all
    db = SessionLocal()
    try:
        sync_all(db)
    except Exception as exc:
        logger.error("Bank sync job failed: %s", exc)
    finally:
        db.close()
```

- [ ] **Step 3: Register the cron job**

Add alongside the existing `_scheduler.add_job(...)` calls:

```python
_scheduler.add_job(_run_bank_sync, "cron", hour=5)
```

- [ ] **Step 4: Verify the app boots and the new routes are registered**

Run: `cd backend && python -c "from backend.main import app; paths = sorted(r.path for r in app.routes); assert '/bank-sync/status' in paths, paths; print('OK:', [p for p in paths if p.startswith('/bank-sync')])"`
Expected: prints `OK: ['/bank-sync/connect', '/bank-sync/status', '/bank-sync/sync-now', '/bank-sync/{connection_id}', '/bank-sync/{connection_id}/link']` with no import errors

- [ ] **Step 5: Run the full backend test suite**

Run: `cd backend && python -m pytest -v`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add backend/main.py
git commit -m "Wire bank sync router and daily 5am sync job into the app"
```

---

### Task 7: Frontend — Bank Connections settings panel

**Files:**
- Modify: `frontend/src/api/index.ts`
- Modify: `frontend/src/pages/Settings.tsx`

**Interfaces:**
- Consumes: `POST /bank-sync/connect`, `POST /bank-sync/{id}/link`, `GET /bank-sync/status`, `POST /bank-sync/sync-now`, `DELETE /bank-sync/{id}` (Task 5), existing `accountsApi`, existing `api` axios client
- Produces: `bankSyncApi` (exported from `frontend/src/api/index.ts`), a new collapsible "Bank Connections" section in the Settings page

- [ ] **Step 1: Add the API client**

In `frontend/src/api/index.ts`, add after the `accountsApi` block:

```typescript
// ── Bank Sync (SimpleFIN) ────────────────────────────────────────────────────
export const bankSyncApi = {
  connect: (setup_token: string) => api.post("/bank-sync/connect", { setup_token }).then((r) => r.data),
  link: (connectionId: number, data: object) => api.post(`/bank-sync/${connectionId}/link`, data).then((r) => r.data),
  status: () => api.get("/bank-sync/status").then((r) => r.data),
  syncNow: () => api.post("/bank-sync/sync-now").then((r) => r.data),
  disconnect: (connectionId: number) => api.delete(`/bank-sync/${connectionId}`),
};
```

- [ ] **Step 2: Add state, queries, and mutations to Settings.tsx**

In `frontend/src/pages/Settings.tsx`, add `bankSyncApi` to the import line at the top (alongside `accountsApi, categoriesApi, ...`):

```typescript
import { accountsApi, categoriesApi, budgetApi, adminApi, authApi, rulesApi, dataApi, bankSyncApi } from "../api";
```

Add, near the other query/state declarations (after the `accounts` query):

```typescript
  const { data: bankConnections = [] } = useQuery<any[]>({ queryKey: ["bank-connections"], queryFn: bankSyncApi.status });
  const [setupToken, setSetupToken] = useState("");
  const [pendingConnect, setPendingConnect] = useState<{ connection_id: number; accounts: any[] } | null>(null);
  const [linkTargets, setLinkTargets] = useState<Record<string, string>>({});

  const connectMut = useMutation({
    mutationFn: (token: string) => bankSyncApi.connect(token),
    onSuccess: (data) => { setPendingConnect(data); setSetupToken(""); },
  });
  const linkMut = useMutation({
    mutationFn: ({ connectionId, data }: any) => bankSyncApi.link(connectionId, data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["bank-connections"] }); },
  });
  const syncNowMut = useMutation({
    mutationFn: bankSyncApi.syncNow,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["bank-connections"] }); qc.invalidateQueries({ queryKey: ["accounts"] }); },
  });
  const disconnectMut = useMutation({
    mutationFn: bankSyncApi.disconnect,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["bank-connections"] }),
  });

  function submitLink(simplefinAccountId: string, simplefinAccountName: string, connectionId: number) {
    const target = linkTargets[simplefinAccountId];
    if (!target) return;
    const [kind, id] = target.split(":");
    linkMut.mutate({
      connectionId,
      data: {
        simplefin_account_id: simplefinAccountId,
        simplefin_account_name: simplefinAccountName,
        local_account_id: kind === "account" ? parseInt(id) : undefined,
        local_credit_card_id: kind === "card" ? parseInt(id) : undefined,
      },
    });
  }
```

- [ ] **Step 3: Add the section JSX**

In `frontend/src/pages/Settings.tsx`, insert immediately after the closing `</div>` of the Accounts section (after `{/* ── Accounts ── */}` block, before the `{/* ── Categories ── */}` comment):

```tsx
      {/* ── Bank Connections ── */}
      <div className="card">
        <div className="flex items-center justify-between">
          <button onClick={() => toggleSection("bank-sync")} className="flex items-center gap-2 flex-1 text-left">
            <h3 className="font-semibold text-gray-900 dark:text-gray-100 flex items-center gap-2"><Link size={16} className="text-indigo-500" /> Bank Connections</h3>
            <ChevronDown size={16} className={`ml-1 text-gray-400 transition-transform ${openSections.has("bank-sync") ? "" : "-rotate-90"}`} />
          </button>
          {openSections.has("bank-sync") && bankConnections.length > 0 && (
            <button onClick={() => syncNowMut.mutate()} disabled={syncNowMut.isPending} className="btn-primary btn-sm text-xs px-3 py-1.5">
              {syncNowMut.isPending ? "Syncing…" : "Sync Now"}
            </button>
          )}
        </div>
        {openSections.has("bank-sync") && <div className="mt-4 space-y-4">
          <p className="text-xs text-gray-500 dark:text-gray-400">
            Connects to your bank via SimpleFIN Bridge (~$15/yr, read-only) to pull transactions automatically. Syncs daily at 5am.
          </p>

          {bankConnections.map((conn: any) => (
            <div key={conn.id} className="border border-gray-100 dark:border-gray-700 rounded-lg p-3">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                    Connection #{conn.id} — {conn.status}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    {conn.last_synced_at ? `Last synced ${new Date(conn.last_synced_at).toLocaleString()}` : "Never synced"}
                  </p>
                  {conn.last_error && <p className="text-xs text-red-600 dark:text-red-400 flex items-center gap-1"><AlertTriangle size={12} /> {conn.last_error}</p>}
                </div>
                <button onClick={() => disconnectMut.mutate(conn.id)} className="btn-ghost p-1.5 text-red-400 hover:bg-red-50"><Trash2 size={14} /></button>
              </div>
              {conn.links.length > 0 && (
                <div className="mt-2 divide-y divide-gray-100 dark:divide-gray-700">
                  {conn.links.map((l: any) => (
                    <div key={l.id} className="py-1.5 text-xs text-gray-600 dark:text-gray-300">
                      {l.simplefin_account_name} → {l.local_account_id ? "linked account" : l.local_credit_card_id ? "linked card" : "unlinked"}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}

          {pendingConnect && (
            <div className="border border-indigo-200 dark:border-indigo-800 rounded-lg p-3 space-y-2">
              <p className="text-sm font-medium text-gray-900 dark:text-gray-100">Map discovered accounts</p>
              {pendingConnect.accounts.map((a: any) => (
                <div key={a.simplefin_account_id} className="flex items-center justify-between gap-2">
                  <span className="text-xs text-gray-600 dark:text-gray-300">{a.org_name} — {a.name} ({fmt(a.balance)})</span>
                  <select
                    className="input py-1 text-xs w-40"
                    value={linkTargets[a.simplefin_account_id] || ""}
                    onChange={(e) => setLinkTargets({ ...linkTargets, [a.simplefin_account_id]: e.target.value })}
                  >
                    <option value="">Select account…</option>
                    {accounts.map((acc: any) => <option key={`account:${acc.id}`} value={`account:${acc.id}`}>{acc.name}</option>)}
                  </select>
                  <button
                    onClick={() => submitLink(a.simplefin_account_id, a.name, pendingConnect.connection_id)}
                    disabled={!linkTargets[a.simplefin_account_id]}
                    className="btn-primary btn-sm text-xs px-2 py-1"
                  >
                    Link
                  </button>
                </div>
              ))}
              <button onClick={() => setPendingConnect(null)} className="text-xs text-gray-400 hover:text-gray-600">Done</button>
            </div>
          )}

          <div className="flex items-center gap-2">
            <input
              type="text"
              className="input flex-1 text-xs"
              placeholder="Paste SimpleFIN setup token"
              value={setupToken}
              onChange={(e) => setSetupToken(e.target.value)}
            />
            <button
              onClick={() => connectMut.mutate(setupToken)}
              disabled={!setupToken || connectMut.isPending}
              className="btn-primary btn-sm text-xs px-3 py-1.5"
            >
              {connectMut.isPending ? "Connecting…" : "Connect"}
            </button>
          </div>
          {connectMut.isError && <p className="text-xs text-red-600 dark:text-red-400">{(connectMut.error as any)?.response?.data?.detail || "Failed to connect"}</p>}
        </div>}
      </div>
```

Note: `Link`, `AlertTriangle`, `Trash2`, `ChevronDown` are already imported at the top of `Settings.tsx` — no new icon imports needed.

- [ ] **Step 4: Verify via Interceptor**

Start the app (`./scripts/start.sh`), open Settings in real Chrome via the Interceptor skill, expand "Bank Connections", confirm the section renders with no console errors and the "Connect" button is disabled until a token is typed. Do not attempt a real SimpleFIN connection during this check — that requires a live setup token from Dan's bank.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/index.ts frontend/src/pages/Settings.tsx
git commit -m "Add Bank Connections panel to Settings"
```

---

### Task 8: Docs — SECURITY.md, .env.example, README

**Files:**
- Modify: `SECURITY.md`
- Modify: `.env.example`
- Modify: `README.md`

**Interfaces:**
- Consumes: nothing (documentation only)
- Produces: nothing consumed by other tasks — terminal task

- [ ] **Step 1: Add the .env.example entries**

In `.env.example`, add after the `# Weekly Digest` block:

```bash
# Bank Sync (SimpleFIN Bridge — optional, leave unset to disable)
# Generate with: python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# BANK_TOKEN_ENCRYPTION_KEY=[FERNET_KEY_HERE]
```

- [ ] **Step 2: Add the SECURITY.md section**

In `SECURITY.md`, add a new section after "Password Reset Tokens and Recovery Codes" (before the `---` separator that precedes "What Is NOT Protected"):

```markdown
### Bank Connection Tokens (SimpleFIN)

- If bank sync is enabled, the SimpleFIN access URL (which grants read-only access to your linked bank accounts) is **encrypted at rest** with Fernet (AES-128-CBC + HMAC), using `BANK_TOKEN_ENCRYPTION_KEY` — a dedicated secret, separate from `JWT_SECRET`, generated the same way
- The key lives only in `.env` (gitignored) — never committed, never logged
- Without `BANK_TOKEN_ENCRYPTION_KEY` set, the `/bank-sync/connect` endpoint refuses to store a token at all rather than falling back to plaintext
- The sync job runs daily (5am local) and makes outbound HTTPS calls to SimpleFIN's bridge — this is the one deliberate exception to OfflineBudget's "no outbound connections" default, and only applies if you opt in by pasting a SimpleFIN setup token
- Disconnecting (Settings → Bank Connections → trash icon) deletes the stored token and its account links immediately; it does not touch transactions already imported
```

- [ ] **Step 3: Add the README feature row**

In `README.md`, update the `Features at a Glance` table row for Transaction Import:

```markdown
| [Transaction Import](#transaction-import) | CSV and OFX/QFX upload; auto-categorization; custom rules engine; optional automated bank sync via SimpleFIN |
```

- [ ] **Step 4: Commit**

```bash
git add SECURITY.md .env.example README.md
git commit -m "Document bank sync security model and setup"
```

---

## Post-Plan Note

`DIGEST_RECIPIENTS` in `.env` still needs Dan's and his wife's email addresses, and `SMTP_*` still needs configuring, for the already-built weekly digest to actually send — that's a config step for Dan to do himself, not part of this plan (see spec's Prerequisite section).
