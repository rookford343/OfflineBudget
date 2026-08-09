# Suggested & Tracked Manual Transfers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the forecast detects a future negative-balance risk, automatically suggest a one-time savings→checking transfer (rounded to a clean, user-configurable increment) that resolves it; let Dan accept/edit/delete it; show it in the day-by-day forecast once accepted; and keep a persistent, never-auto-dismissing reminder on Dashboard and Forecast until he confirms he's actually scheduled it in his real bank — then auto-verify once the real transaction lands via sync.

**Architecture:** A new `PlannedTransfer` model (status: pending → scheduled → verified) plus a per-user `transfer_increment` setting. The forecast engine gains a new injection block (mirroring the existing `BufferTransferRule` pattern) and a new pure suggestion function. A new router gives full CRUD + a "mark scheduled" action. Verification piggybacks on the existing daily bank-sync job. Frontend extends the existing `RiskBanner` component and adds one new reminder component shared by Dashboard and Forecast.

**Tech Stack:** FastAPI + SQLAlchemy + SQLite (existing), React + TypeScript + TanStack Query (existing).

## Global Constraints

- Suggestions are single lump-sum transfers only — never spread across months.
- The app never has bank-write access — this is planning/tracking only, never an automated transfer.
- `BufferTransferRule` is untouched — a separate, already-shipped, fully-automatic mechanism. `PlannedTransfer` is new and distinct.
- Suggested amounts round UP to `User.transfer_increment` (`Numeric(14,2)`, default `1000.00`, per-user configurable in Settings).
- Status model: `pending` → `scheduled` → `verified`. The forecast injects `pending` and `scheduled` transfers only — never `verified` (its real transaction is already in the actuals feed; injecting it too would double-count).
- The reminder banner shows `pending` and `scheduled` rows and never auto-dismisses or snoozes on its own.
- Verification runs on the same cadence as the existing daily bank-sync job (`_run_bank_sync` in `backend/main.py`).
- Repo convention: commit directly to `main`. No feature branches, no worktrees.
- TDD throughout: failing test → implementation → passing test → commit.

---

### Task 1: Data model — PlannedTransfer, PlannedTransferStatus, User.transfer_increment

**Files:**
- Modify: `backend/models.py`
- Modify: `backend/database.py`
- Test: `backend/tests/test_planned_transfer_model.py`

**Interfaces:**
- Consumes: nothing new (pure SQLAlchemy models, following existing patterns in `models.py`)
- Produces: `models.PlannedTransferStatus` (enum: `pending`/`scheduled`/`verified`), `models.PlannedTransfer` (fields: `id, user_id, from_account_id, to_account_id, amount, target_date, status, suggested, notes, verified_transaction_id, created_at, updated_at`), `models.User.transfer_increment` (`Decimal`, default `1000.00`) — consumed by Tasks 2–8

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_planned_transfer_model.py
from datetime import date
from decimal import Decimal
from backend import models


def _make_user_and_accounts(db):
    user = models.User(username="t", hashed_password="x", display_name="T")
    db.add(user)
    db.flush()
    checking = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking)
    savings = models.Account(user_id=user.id, name="Savings", type=models.AccountType.savings)
    db.add_all([checking, savings])
    db.flush()
    return user, checking, savings


def test_planned_transfer_round_trip_defaults(db_session):
    user, checking, savings = _make_user_and_accounts(db_session)
    transfer = models.PlannedTransfer(
        user_id=user.id, from_account_id=savings.id, to_account_id=checking.id,
        amount=Decimal("22000.00"), target_date=date(2026, 9, 12),
    )
    db_session.add(transfer)
    db_session.commit()
    db_session.refresh(transfer)

    assert transfer.status == models.PlannedTransferStatus.pending
    assert transfer.suggested is False
    assert transfer.verified_transaction_id is None


def test_planned_transfer_from_account_is_nullable(db_session):
    """No savings account, or an ambiguous choice -- from_account_id stays
    unset rather than guessing wrong (per spec's error-handling section)."""
    user, checking, savings = _make_user_and_accounts(db_session)
    transfer = models.PlannedTransfer(
        user_id=user.id, to_account_id=checking.id,
        amount=Decimal("5000.00"), target_date=date(2026, 9, 12),
    )
    db_session.add(transfer)
    db_session.commit()
    db_session.refresh(transfer)

    assert transfer.from_account_id is None


def test_user_transfer_increment_defaults_to_1000(db_session):
    user = models.User(username="t2", hashed_password="x", display_name="T2")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    assert user.transfer_increment == Decimal("1000.00")


def test_user_transfer_increment_is_settable(db_session):
    user = models.User(username="t3", hashed_password="x", display_name="T3", transfer_increment=Decimal("500.00"))
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    assert user.transfer_increment == Decimal("500.00")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_planned_transfer_model.py -v`
Expected: FAIL with `AttributeError: module 'backend.models' has no attribute 'PlannedTransferStatus'`

- [ ] **Step 3: Add User.transfer_increment**

In `backend/models.py`, find the `User` class and add near the other per-user settings columns (e.g. right after `ss_bonus_ytd`):

```python
    transfer_increment: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("1000.00"))
```

- [ ] **Step 4: Add PlannedTransferStatus and PlannedTransfer**

Append to the end of `backend/models.py`:

```python
# ── Planned Transfers ────────────────────────────────────────────────────────

class PlannedTransferStatus(str, PyEnum):
    pending = "pending"
    scheduled = "scheduled"
    verified = "verified"


class PlannedTransfer(Base):
    """A one-time, Dan-confirmed transfer plan -- NOT automatic like
    BufferTransferRule. The app never moves money; this tracks a plan Dan
    executes himself in his real bank, and never assumes it happened."""
    __tablename__ = "planned_transfers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    from_account_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("accounts.id"))
    to_account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[PlannedTransferStatus] = mapped_column(Enum(PlannedTransferStatus), default=PlannedTransferStatus.pending, nullable=False)
    suggested: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)
    verified_transaction_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("transactions.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship()
    from_account: Mapped["Account | None"] = relationship(foreign_keys=[from_account_id])
    to_account: Mapped["Account"] = relationship(foreign_keys=[to_account_id])
    verified_transaction: Mapped["Transaction | None"] = relationship()
```

This is a brand-new table, so `database.create_tables()` (`Base.metadata.create_all`) picks it up automatically for fresh databases — but Dan's live database already exists, so it still needs an explicit migration (Step 5) the same way every other table added to an existing database has in this codebase.

- [ ] **Step 5: Add the migration entries**

In `backend/database.py`, add to the end of the `stmts` list in `upgrade_schema()`:

```python
        "ALTER TABLE users ADD COLUMN transfer_increment NUMERIC(14,2) DEFAULT 1000.00",
        """CREATE TABLE IF NOT EXISTS planned_transfers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            from_account_id INTEGER REFERENCES accounts(id),
            to_account_id INTEGER NOT NULL REFERENCES accounts(id),
            amount NUMERIC(14,2) NOT NULL,
            target_date DATE NOT NULL,
            status VARCHAR(10) NOT NULL DEFAULT 'pending',
            suggested BOOLEAN DEFAULT 0,
            notes TEXT,
            verified_transaction_id INTEGER REFERENCES transactions(id),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )""",
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_planned_transfer_model.py -v`
Expected: 4 passed

- [ ] **Step 7: Commit**

```bash
git add backend/models.py backend/database.py backend/tests/test_planned_transfer_model.py
git commit -m "Add PlannedTransfer model and User.transfer_increment"
```

---

### Task 2: Schemas

**Files:**
- Modify: `backend/schemas.py`

**Interfaces:**
- Consumes: `models.PlannedTransferStatus`, `models.PlannedTransfer` (Task 1)
- Produces: `schemas.PlannedTransferCreate`, `schemas.PlannedTransferUpdate`, `schemas.PlannedTransferOut`; extends `schemas.ForecastRisk` with `suggested_transfer_amount`, `suggested_transfer_date`, `suggested_transfer_from_account_id`, `suggested_transfer_already_planned`; extends `schemas.UserUpdate`/`schemas.UserOut` with `transfer_increment` — consumed by Tasks 5, 7, 9

No tests for this task — it's pure data-shape declarations, exercised end-to-end by Tasks 5 and 7's own tests. This matches the plan's own precedent (Task 5 of the bank-sync plan folded schema additions into the router task with no dedicated schema test file).

- [ ] **Step 1: Add the models import**

In `backend/schemas.py`, find the models import line at the top (`from backend.models import AccountType, CategoryType, RecurringType, ImportFormat, UserRole, RecurringFrequency, RuleField, RulePatternType, RuleAction, BankConnectionStatus`) and add `PlannedTransferStatus`:

```python
from backend.models import AccountType, CategoryType, RecurringType, ImportFormat, UserRole, RecurringFrequency, RuleField, RulePatternType, RuleAction, BankConnectionStatus, PlannedTransferStatus
```

- [ ] **Step 2: Add transfer_increment to UserUpdate and UserOut**

In `backend/schemas.py`, in `class UserUpdate`, add after `itemized_other`:

```python
    transfer_increment: Optional[Decimal] = None
```

In `class UserOut`, add after `itemized_other` (matching the same position for readability):

```python
    transfer_increment: Optional[Decimal] = None
```

- [ ] **Step 3: Extend ForecastRisk**

In `backend/schemas.py`, find `class ForecastRisk` and add after `action_threshold`:

```python
    suggested_transfer_amount: Optional[Decimal] = None
    suggested_transfer_date: Optional[date] = None
    suggested_transfer_from_account_id: Optional[int] = None
    suggested_transfer_already_planned: bool = False
```

- [ ] **Step 4: Add the PlannedTransfer schemas**

Append near `PlannedExpenseOut` (same section of the file):

```python
# ── Planned Transfers ────────────────────────────────────────────────────────

class PlannedTransferCreate(BaseModel):
    from_account_id: Optional[int] = None
    to_account_id: int
    amount: Decimal
    target_date: date
    notes: Optional[str] = None


class PlannedTransferUpdate(BaseModel):
    from_account_id: Optional[int] = None
    to_account_id: Optional[int] = None
    amount: Optional[Decimal] = None
    target_date: Optional[date] = None
    status: Optional[PlannedTransferStatus] = None
    notes: Optional[str] = None


class PlannedTransferOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    from_account_id: Optional[int]
    to_account_id: int
    amount: Decimal
    target_date: date
    status: PlannedTransferStatus
    suggested: bool
    notes: Optional[str]
    verified_transaction_id: Optional[int]
    created_at: datetime
```

- [ ] **Step 5: Run the full backend suite to confirm nothing broke**

Run: `cd backend && python -m pytest -v`
Expected: all existing tests still pass (this task adds no new behavior, only type declarations)

- [ ] **Step 6: Commit**

```bash
git add backend/schemas.py
git commit -m "Add PlannedTransfer schemas, extend ForecastRisk and User schemas"
```

---

### Task 3: Suggestion computation

**Files:**
- Modify: `backend/services/forecast_engine.py`
- Test: `backend/tests/test_suggest_transfer.py`

**Interfaces:**
- Consumes: `models.PlannedTransfer`, `models.PlannedTransferStatus`, `models.Account`, `models.AccountType`, `models.User` (Task 1); `find_balance_risk`'s return shape (`{"at_risk": bool, "date": date|None, "amount": Decimal|None, "threshold": Decimal}`, pre-existing)
- Produces: `forecast_engine.suggest_transfer(db: Session, user: models.User, account_id: int, risk: dict) -> dict` returning `{"amount": Decimal|None, "date": date|None, "from_account_id": int|None, "already_planned": bool}` — consumed by Task 7

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_suggest_transfer.py
from datetime import date, timedelta
from decimal import Decimal
from backend import models
from backend.services.forecast_engine import suggest_transfer


def _make_user(db, transfer_increment=None):
    kwargs = {"username": "t", "hashed_password": "x", "display_name": "T"}
    if transfer_increment is not None:
        kwargs["transfer_increment"] = transfer_increment
    user = models.User(**kwargs)
    db.add(user)
    db.flush()
    return user


def _make_accounts(db, user, num_savings=1):
    checking = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking)
    db.add(checking)
    savings_accounts = []
    for i in range(num_savings):
        s = models.Account(user_id=user.id, name=f"Savings {i}", type=models.AccountType.savings)
        db.add(s)
        savings_accounts.append(s)
    db.flush()
    return checking, savings_accounts


def _risk(at_risk=True, d=None, amount="-500.00", threshold="0"):
    return {
        "at_risk": at_risk,
        "date": d or date(2026, 9, 15),
        "amount": Decimal(amount) if at_risk else None,
        "threshold": Decimal(threshold),
    }


def test_no_suggestion_when_not_at_risk(db_session):
    user = _make_user(db_session)
    checking, _ = _make_accounts(db_session, user)
    db_session.commit()

    result = suggest_transfer(db_session, user, checking.id, _risk(at_risk=False))

    assert result == {"amount": None, "date": None, "from_account_id": None, "already_planned": False}


def test_suggestion_rounds_up_to_default_increment(db_session):
    user = _make_user(db_session)
    checking, savings = _make_accounts(db_session, user, num_savings=1)
    db_session.commit()

    # shortfall = threshold(0) - amount(-500) = 500 -> rounds up to 1000 (default increment)
    result = suggest_transfer(db_session, user, checking.id, _risk(amount="-500.00", threshold="0"))

    assert result["amount"] == Decimal("1000.00")
    assert result["from_account_id"] == savings[0].id
    assert result["already_planned"] is False
    assert result["date"] == date(2026, 9, 15) - timedelta(days=3)


def test_suggestion_rounds_up_to_custom_increment(db_session):
    user = _make_user(db_session, transfer_increment=Decimal("500.00"))
    checking, _ = _make_accounts(db_session, user, num_savings=1)
    db_session.commit()

    # shortfall = 500 -> exactly one 500 increment, no rounding needed
    result = suggest_transfer(db_session, user, checking.id, _risk(amount="-500.00", threshold="0"))

    assert result["amount"] == Decimal("500.00")


def test_suggestion_leaves_from_account_unset_when_ambiguous(db_session):
    user = _make_user(db_session)
    checking, savings = _make_accounts(db_session, user, num_savings=2)
    db_session.commit()

    result = suggest_transfer(db_session, user, checking.id, _risk())

    assert result["from_account_id"] is None


def test_suggestion_leaves_from_account_unset_when_no_savings(db_session):
    user = _make_user(db_session)
    checking, _ = _make_accounts(db_session, user, num_savings=0)
    db_session.commit()

    result = suggest_transfer(db_session, user, checking.id, _risk())

    assert result["from_account_id"] is None


def test_already_planned_suppresses_a_new_suggestion(db_session):
    user = _make_user(db_session)
    checking, savings = _make_accounts(db_session, user, num_savings=1)
    db_session.flush()
    db_session.add(models.PlannedTransfer(
        user_id=user.id, from_account_id=savings[0].id, to_account_id=checking.id,
        amount=Decimal("1000.00"), target_date=date(2026, 9, 13),
        status=models.PlannedTransferStatus.pending,
    ))
    db_session.commit()

    result = suggest_transfer(db_session, user, checking.id, _risk(d=date(2026, 9, 15)))

    assert result["already_planned"] is True
    assert result["amount"] is None


def test_verified_transfer_does_not_suppress_a_new_suggestion(db_session):
    """A verified transfer means the real transaction already happened and
    is reflected in actuals -- a NEW risk near the same date needs its own
    new suggestion, not silent suppression by old, already-resolved history."""
    user = _make_user(db_session)
    checking, savings = _make_accounts(db_session, user, num_savings=1)
    db_session.flush()
    db_session.add(models.PlannedTransfer(
        user_id=user.id, from_account_id=savings[0].id, to_account_id=checking.id,
        amount=Decimal("1000.00"), target_date=date(2026, 9, 13),
        status=models.PlannedTransferStatus.verified,
    ))
    db_session.commit()

    result = suggest_transfer(db_session, user, checking.id, _risk(d=date(2026, 9, 15)))

    assert result["already_planned"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_suggest_transfer.py -v`
Expected: FAIL with `ImportError: cannot import name 'suggest_transfer'`

- [ ] **Step 3: Write the implementation**

In `backend/services/forecast_engine.py`, add near `find_transfer_signal` (same section of the file):

```python
def suggest_transfer(db: Session, user: models.User, account_id: int, risk: dict) -> dict:
    """Given a risk dict from find_balance_risk (at_risk=True), compute a
    suggested one-time transfer that would clear it, rounded UP to the
    user's transfer_increment (default $1000). Returns
    already_planned=True (no new suggestion) if an active (pending or
    scheduled) PlannedTransfer already targets this account within a few
    days of the risk date -- a verified one does NOT suppress a new
    suggestion, since its real transaction is already resolved history,
    not an open plan covering a new risk.
    """
    empty = {"amount": None, "date": None, "from_account_id": None, "already_planned": False}
    if not risk.get("at_risk"):
        return empty

    risk_date = risk["date"]
    window_start = risk_date - timedelta(days=5)
    window_end = risk_date + timedelta(days=5)
    existing = db.query(models.PlannedTransfer).filter(
        models.PlannedTransfer.user_id == user.id,
        models.PlannedTransfer.to_account_id == account_id,
        models.PlannedTransfer.status.in_([models.PlannedTransferStatus.pending, models.PlannedTransferStatus.scheduled]),
        models.PlannedTransfer.target_date >= window_start,
        models.PlannedTransfer.target_date <= window_end,
    ).first()
    if existing:
        return {**empty, "already_planned": True}

    shortfall = risk["threshold"] - risk["amount"]
    increment = user.transfer_increment or Decimal("1000.00")
    amount = (shortfall / increment).to_integral_value(rounding=ROUND_CEILING) * increment

    savings_accounts = db.query(models.Account).filter(
        models.Account.user_id == user.id,
        models.Account.type == models.AccountType.savings,
        models.Account.is_active == True,
    ).all()
    from_account_id = savings_accounts[0].id if len(savings_accounts) == 1 else None

    return {
        "amount": amount,
        "date": risk_date - timedelta(days=3),
        "from_account_id": from_account_id,
        "already_planned": False,
    }
```

`ROUND_CEILING` is already imported at the top of this file (`from decimal import Decimal, ROUND_CEILING`) — no new import needed.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_suggest_transfer.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add backend/services/forecast_engine.py backend/tests/test_suggest_transfer.py
git commit -m "Add suggest_transfer: compute a clean-increment transfer suggestion for a forecast risk"
```

---

### Task 4: Forecast engine injection

**Files:**
- Modify: `backend/services/forecast_engine.py`
- Test: `backend/tests/test_planned_transfer_forecast_injection.py`

**Interfaces:**
- Consumes: `models.PlannedTransfer`, `models.PlannedTransferStatus` (Task 1); existing `build_forecast(db, user_id, account_id, start_date, end_date, ...)` structure
- Produces: `build_forecast` now injects `pending`/`scheduled` `PlannedTransfer`s as `ForecastTransaction(is_transfer=True)` entries on `target_date` for both `to_account_id` and `from_account_id` — consumed by Tasks 6 (risk detection sees the resolved balance) and the Forecast page (existing, unmodified chart code already renders whatever `build_forecast` returns)

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_planned_transfer_forecast_injection.py
from datetime import date
from decimal import Decimal
from backend import models
from backend.services.forecast_engine import build_forecast


def _make_user_and_accounts(db):
    user = models.User(username="t", hashed_password="x", display_name="T")
    db.add(user)
    db.flush()
    checking = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking, current_balance=Decimal("1000.00"))
    savings = models.Account(user_id=user.id, name="Savings", type=models.AccountType.savings, current_balance=Decimal("30000.00"))
    db.add_all([checking, savings])
    db.flush()
    return user, checking, savings


def test_pending_transfer_injects_on_target_date_both_accounts(db_session):
    user, checking, savings = _make_user_and_accounts(db_session)
    db_session.add(models.PlannedTransfer(
        user_id=user.id, from_account_id=savings.id, to_account_id=checking.id,
        amount=Decimal("5000.00"), target_date=date(2026, 9, 15),
        status=models.PlannedTransferStatus.pending,
    ))
    db_session.commit()

    checking_entries = build_forecast(db_session, user.id, checking.id, date(2026, 9, 1), date(2026, 9, 30))
    sep15_checking = next(e for e in checking_entries if e.date == date(2026, 9, 15))
    transfer_txns = [t for t in sep15_checking.transactions if t.is_transfer]
    assert len(transfer_txns) == 1
    assert transfer_txns[0].amount == Decimal("5000.00")

    savings_entries = build_forecast(db_session, user.id, savings.id, date(2026, 9, 1), date(2026, 9, 30))
    sep15_savings = next(e for e in savings_entries if e.date == date(2026, 9, 15))
    savings_transfer_txns = [t for t in sep15_savings.transactions if t.is_transfer]
    assert len(savings_transfer_txns) == 1
    assert savings_transfer_txns[0].amount == Decimal("-5000.00")


def test_scheduled_transfer_also_injects(db_session):
    user, checking, savings = _make_user_and_accounts(db_session)
    db_session.add(models.PlannedTransfer(
        user_id=user.id, from_account_id=savings.id, to_account_id=checking.id,
        amount=Decimal("2000.00"), target_date=date(2026, 9, 15),
        status=models.PlannedTransferStatus.scheduled,
    ))
    db_session.commit()

    entries = build_forecast(db_session, user.id, checking.id, date(2026, 9, 1), date(2026, 9, 30))
    sep15 = next(e for e in entries if e.date == date(2026, 9, 15))
    assert any(t.is_transfer for t in sep15.transactions)


def test_verified_transfer_does_not_inject(db_session):
    """A verified transfer's real transaction is already in the actuals
    feed -- injecting it too would double-count."""
    user, checking, savings = _make_user_and_accounts(db_session)
    db_session.add(models.PlannedTransfer(
        user_id=user.id, from_account_id=savings.id, to_account_id=checking.id,
        amount=Decimal("2000.00"), target_date=date(2026, 9, 15),
        status=models.PlannedTransferStatus.verified,
    ))
    db_session.commit()

    entries = build_forecast(db_session, user.id, checking.id, date(2026, 9, 1), date(2026, 9, 30))
    sep15 = next(e for e in entries if e.date == date(2026, 9, 15))
    assert not any(t.is_transfer for t in sep15.transactions)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_planned_transfer_forecast_injection.py -v`
Expected: FAIL — no transfer transactions found on 2026-09-15 (assertion errors, `len(transfer_txns) == 0` not `1`)

- [ ] **Step 3: Write the implementation**

In `backend/services/forecast_engine.py`, inside `build_forecast`, find where `incoming_transfer_schedules`/`outgoing_transfer_schedules` are built (the `if apply_buffer_transfers:` block) and add a new query right after that block, unconditional (planned transfers always apply, unlike buffer transfers which are gated by `apply_buffer_transfers`):

```python
    planned_transfers = db.query(models.PlannedTransfer).options(
        joinedload(models.PlannedTransfer.from_account),
        joinedload(models.PlannedTransfer.to_account),
    ).filter(
        models.PlannedTransfer.user_id == user_id,
        models.PlannedTransfer.status.in_([models.PlannedTransferStatus.pending, models.PlannedTransferStatus.scheduled]),
    ).filter(
        or_(
            models.PlannedTransfer.to_account_id == account_id,
            models.PlannedTransfer.from_account_id == account_id,
        )
    ).all()
```

(`joinedload` and `or_` are already imported at the top of this file.)

Then, in the day-by-day walk loop, find the two `for rule, schedule in incoming_transfer_schedules:` / `for rule, schedule in outgoing_transfer_schedules:` blocks and add a third block right after them:

```python
        for pt in planned_transfers:
            if pt.target_date != current:
                continue
            if pt.to_account_id == account_id:
                balance += pt.amount
                day_transactions.append(ForecastTransaction(
                    name=f"Planned Transfer from {pt.from_account.name if pt.from_account else 'Savings'}",
                    amount=pt.amount,
                    type="income",
                    category_name=None,
                    is_actual=False,
                    is_transfer=True,
                ))
            if pt.from_account_id == account_id:
                balance -= pt.amount
                day_transactions.append(ForecastTransaction(
                    name=f"Planned Transfer to {pt.to_account.name}",
                    amount=-pt.amount,
                    type="expense",
                    category_name=None,
                    is_actual=False,
                    is_transfer=True,
                ))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_planned_transfer_forecast_injection.py -v`
Expected: 3 passed

- [ ] **Step 5: Run the full backend suite to confirm no regressions**

Run: `cd backend && python -m pytest -v`
Expected: all tests pass (existing suite + all new planned-transfer tests)

- [ ] **Step 6: Commit**

```bash
git add backend/services/forecast_engine.py backend/tests/test_planned_transfer_forecast_injection.py
git commit -m "Inject pending/scheduled PlannedTransfers into the day-by-day forecast"
```

---

### Task 5: PlannedTransfer router (CRUD + mark-scheduled)

**Files:**
- Create: `backend/routers/planned_transfers.py`
- Test: `backend/tests/test_planned_transfers_router.py`

**Interfaces:**
- Consumes: `models.PlannedTransfer`, `models.PlannedTransferStatus`, `models.Account` (Task 1); `schemas.PlannedTransferCreate/Update/Out` (Task 2); `dependencies.get_db`, `dependencies.get_current_user` (existing)
- Produces: `planned_transfers.router` (FastAPI `APIRouter`, `prefix="/planned-transfers"`) with `GET /planned-transfers`, `POST /planned-transfers`, `PATCH /planned-transfers/{id}`, `POST /planned-transfers/{id}/mark-scheduled`, `DELETE /planned-transfers/{id}` — consumed by Task 8 (frontend) and Task 6 (app registration, folded into this task since it's a one-line addition)

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_planned_transfers_router.py
from datetime import date
from decimal import Decimal
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.routers import planned_transfers as planned_transfers_router_module
from backend.dependencies import get_db, get_current_user


@pytest.fixture()
def client(db_session):
    user = models.User(username="dan", hashed_password="x", display_name="Dan")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    checking = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking)
    savings = models.Account(user_id=user.id, name="Savings", type=models.AccountType.savings)
    db_session.add_all([checking, savings])
    db_session.commit()
    db_session.refresh(checking)
    db_session.refresh(savings)

    app = FastAPI()
    app.include_router(planned_transfers_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app), user, checking, savings


def test_create_and_list_planned_transfer(client):
    test_client, user, checking, savings = client

    resp = test_client.post("/planned-transfers", json={
        "from_account_id": savings.id, "to_account_id": checking.id,
        "amount": "22000.00", "target_date": "2026-09-12",
    })
    assert resp.status_code == 201
    assert resp.json()["status"] == "pending"

    resp = test_client.get("/planned-transfers")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_create_rejects_account_owned_by_another_user(db_session, client):
    test_client, user, checking, savings = client
    other = models.User(username="mallory", hashed_password="x", display_name="Mallory")
    db_session.add(other)
    db_session.commit()
    other_account = models.Account(user_id=other.id, name="Mallory Checking", type=models.AccountType.checking)
    db_session.add(other_account)
    db_session.commit()
    db_session.refresh(other_account)

    resp = test_client.post("/planned-transfers", json={
        "to_account_id": other_account.id, "amount": "1000.00", "target_date": "2026-09-12",
    })
    assert resp.status_code == 404


def test_update_planned_transfer(client):
    test_client, user, checking, savings = client
    created = test_client.post("/planned-transfers", json={
        "to_account_id": checking.id, "amount": "1000.00", "target_date": "2026-09-12",
    }).json()

    resp = test_client.patch(f"/planned-transfers/{created['id']}", json={"amount": "1500.00"})
    assert resp.status_code == 200
    assert resp.json()["amount"] == "1500.00"


def test_mark_scheduled_transitions_pending_to_scheduled(client):
    test_client, user, checking, savings = client
    created = test_client.post("/planned-transfers", json={
        "to_account_id": checking.id, "amount": "1000.00", "target_date": "2026-09-12",
    }).json()

    resp = test_client.post(f"/planned-transfers/{created['id']}/mark-scheduled")
    assert resp.status_code == 200
    assert resp.json()["status"] == "scheduled"


def test_mark_scheduled_rejects_already_scheduled(client):
    test_client, user, checking, savings = client
    created = test_client.post("/planned-transfers", json={
        "to_account_id": checking.id, "amount": "1000.00", "target_date": "2026-09-12",
    }).json()
    test_client.post(f"/planned-transfers/{created['id']}/mark-scheduled")

    resp = test_client.post(f"/planned-transfers/{created['id']}/mark-scheduled")
    assert resp.status_code == 400


def test_delete_planned_transfer(client):
    test_client, user, checking, savings = client
    created = test_client.post("/planned-transfers", json={
        "to_account_id": checking.id, "amount": "1000.00", "target_date": "2026-09-12",
    }).json()

    resp = test_client.delete(f"/planned-transfers/{created['id']}")
    assert resp.status_code == 204
    assert test_client.get("/planned-transfers").json() == []


def test_cross_user_delete_is_rejected(db_session, client):
    test_client, user, checking, savings = client
    created = test_client.post("/planned-transfers", json={
        "to_account_id": checking.id, "amount": "1000.00", "target_date": "2026-09-12",
    }).json()

    other = models.User(username="mallory2", hashed_password="x", display_name="Mallory2")
    db_session.add(other)
    db_session.commit()
    app = FastAPI()
    app.include_router(planned_transfers_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: other
    other_client = TestClient(app)

    resp = other_client.delete(f"/planned-transfers/{created['id']}")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_planned_transfers_router.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.routers.planned_transfers'`

- [ ] **Step 3: Write the router**

```python
# backend/routers/planned_transfers.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from backend import models, schemas
from backend.dependencies import get_db, get_current_user

router = APIRouter(prefix="/planned-transfers", tags=["planned-transfers"])


def _get_owned(db: Session, user: models.User, transfer_id: int) -> models.PlannedTransfer:
    transfer = db.query(models.PlannedTransfer).filter(
        models.PlannedTransfer.id == transfer_id,
        models.PlannedTransfer.user_id == user.id,
    ).first()
    if not transfer:
        raise HTTPException(status_code=404, detail="Planned transfer not found")
    return transfer


def _assert_account_owned(db: Session, user_id: int, account_id: int) -> None:
    if not db.query(models.Account).filter(
        models.Account.id == account_id, models.Account.user_id == user_id,
    ).first():
        raise HTTPException(status_code=404, detail="Account not found")


@router.get("", response_model=list[schemas.PlannedTransferOut])
def list_planned_transfers(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    return (
        db.query(models.PlannedTransfer)
        .filter(models.PlannedTransfer.user_id == user.id)
        .order_by(models.PlannedTransfer.target_date)
        .all()
    )


@router.post("", response_model=schemas.PlannedTransferOut, status_code=status.HTTP_201_CREATED)
def create_planned_transfer(
    body: schemas.PlannedTransferCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    _assert_account_owned(db, user.id, body.to_account_id)
    if body.from_account_id:
        _assert_account_owned(db, user.id, body.from_account_id)
    transfer = models.PlannedTransfer(
        user_id=user.id,
        from_account_id=body.from_account_id,
        to_account_id=body.to_account_id,
        amount=body.amount,
        target_date=body.target_date,
        notes=body.notes,
    )
    db.add(transfer)
    db.commit()
    db.refresh(transfer)
    return transfer


@router.patch("/{transfer_id}", response_model=schemas.PlannedTransferOut)
def update_planned_transfer(
    transfer_id: int,
    body: schemas.PlannedTransferUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    transfer = _get_owned(db, user, transfer_id)
    data = body.model_dump(exclude_unset=True)
    if "to_account_id" in data and data["to_account_id"] is not None:
        _assert_account_owned(db, user.id, data["to_account_id"])
    if "from_account_id" in data and data["from_account_id"] is not None:
        _assert_account_owned(db, user.id, data["from_account_id"])
    for field, value in data.items():
        setattr(transfer, field, value)
    db.commit()
    db.refresh(transfer)
    return transfer


@router.post("/{transfer_id}/mark-scheduled", response_model=schemas.PlannedTransferOut)
def mark_scheduled(
    transfer_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    transfer = _get_owned(db, user, transfer_id)
    if transfer.status != models.PlannedTransferStatus.pending:
        raise HTTPException(status_code=400, detail="Only a pending transfer can be marked scheduled")
    transfer.status = models.PlannedTransferStatus.scheduled
    db.commit()
    db.refresh(transfer)
    return transfer


@router.delete("/{transfer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_planned_transfer(
    transfer_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    transfer = _get_owned(db, user, transfer_id)
    db.delete(transfer)
    db.commit()
```

- [ ] **Step 4: Register the router in main.py**

In `backend/main.py`, add to the router imports (alongside `from backend.routers import bank_sync as bank_sync_router_module`):

```python
from backend.routers import planned_transfers as planned_transfers_router_module
```

Add to the `include_router` block (after `app.include_router(bank_sync_router_module.router)`):

```python
app.include_router(planned_transfers_router_module.router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_planned_transfers_router.py -v`
Expected: 7 passed

- [ ] **Step 6: Run the full backend suite to confirm no regressions**

Run: `cd backend && python -m pytest -v`
Expected: all tests pass

- [ ] **Step 7: Commit**

```bash
git add backend/routers/planned_transfers.py backend/main.py backend/tests/test_planned_transfers_router.py
git commit -m "Add PlannedTransfer REST API (CRUD + mark-scheduled)"
```

---

### Task 6: Verification service

**Files:**
- Create: `backend/services/transfer_verification.py`
- Modify: `backend/main.py`
- Test: `backend/tests/test_transfer_verification.py`

**Interfaces:**
- Consumes: `models.PlannedTransfer`, `models.PlannedTransferStatus`, `models.Transaction` (Task 1, existing)
- Produces: `transfer_verification.verify_scheduled_transfers(db: Session, user_id: int) -> int` (returns count verified) — wired into `main.py`'s daily job

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_transfer_verification.py
from datetime import date
from decimal import Decimal
from backend import models
from backend.services.transfer_verification import verify_scheduled_transfers


def _make_user_and_accounts(db):
    user = models.User(username="t", hashed_password="x", display_name="T")
    db.add(user)
    db.flush()
    checking = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking)
    savings = models.Account(user_id=user.id, name="Savings", type=models.AccountType.savings)
    db.add_all([checking, savings])
    db.flush()
    return user, checking, savings


def test_matching_real_transaction_verifies_the_transfer(db_session):
    user, checking, savings = _make_user_and_accounts(db_session)
    transfer = models.PlannedTransfer(
        user_id=user.id, from_account_id=savings.id, to_account_id=checking.id,
        amount=Decimal("22000.00"), target_date=date(2026, 9, 15),
        status=models.PlannedTransferStatus.scheduled,
    )
    db_session.add(transfer)
    db_session.flush()
    real_txn = models.Transaction(
        user_id=user.id, account_id=checking.id, date=date(2026, 9, 16),
        amount=Decimal("22000.00"), description="Online Transfer from SAV",
        is_actual=True, source=models.TransactionSource.bank_sync,
    )
    db_session.add(real_txn)
    db_session.commit()
    db_session.refresh(real_txn)

    verified_count = verify_scheduled_transfers(db_session, user.id)

    db_session.refresh(transfer)
    assert verified_count == 1
    assert transfer.status == models.PlannedTransferStatus.verified
    assert transfer.verified_transaction_id == real_txn.id


def test_no_match_outside_date_window_stays_scheduled(db_session):
    user, checking, savings = _make_user_and_accounts(db_session)
    transfer = models.PlannedTransfer(
        user_id=user.id, from_account_id=savings.id, to_account_id=checking.id,
        amount=Decimal("22000.00"), target_date=date(2026, 9, 15),
        status=models.PlannedTransferStatus.scheduled,
    )
    db_session.add(transfer)
    db_session.flush()
    db_session.add(models.Transaction(
        user_id=user.id, account_id=checking.id, date=date(2026, 10, 1),  # 16 days late
        amount=Decimal("22000.00"), description="Unrelated deposit",
        is_actual=True, source=models.TransactionSource.bank_sync,
    ))
    db_session.commit()

    verified_count = verify_scheduled_transfers(db_session, user.id)

    db_session.refresh(transfer)
    assert verified_count == 0
    assert transfer.status == models.PlannedTransferStatus.scheduled


def test_no_match_outside_amount_tolerance_stays_scheduled(db_session):
    user, checking, savings = _make_user_and_accounts(db_session)
    transfer = models.PlannedTransfer(
        user_id=user.id, from_account_id=savings.id, to_account_id=checking.id,
        amount=Decimal("22000.00"), target_date=date(2026, 9, 15),
        status=models.PlannedTransferStatus.scheduled,
    )
    db_session.add(transfer)
    db_session.flush()
    db_session.add(models.Transaction(
        user_id=user.id, account_id=checking.id, date=date(2026, 9, 15),
        amount=Decimal("5000.00"),  # far outside 5% tolerance
        description="Small deposit", is_actual=True, source=models.TransactionSource.bank_sync,
    ))
    db_session.commit()

    verified_count = verify_scheduled_transfers(db_session, user.id)

    db_session.refresh(transfer)
    assert verified_count == 0
    assert transfer.status == models.PlannedTransferStatus.scheduled


def test_pending_transfers_are_not_checked(db_session):
    """Only scheduled transfers get auto-verified -- a pending one hasn't
    even been confirmed as executed yet, so there's nothing to verify."""
    user, checking, savings = _make_user_and_accounts(db_session)
    transfer = models.PlannedTransfer(
        user_id=user.id, from_account_id=savings.id, to_account_id=checking.id,
        amount=Decimal("22000.00"), target_date=date(2026, 9, 15),
        status=models.PlannedTransferStatus.pending,
    )
    db_session.add(transfer)
    db_session.flush()
    db_session.add(models.Transaction(
        user_id=user.id, account_id=checking.id, date=date(2026, 9, 15),
        amount=Decimal("22000.00"), description="Online Transfer from SAV",
        is_actual=True, source=models.TransactionSource.bank_sync,
    ))
    db_session.commit()

    verified_count = verify_scheduled_transfers(db_session, user.id)

    db_session.refresh(transfer)
    assert verified_count == 0
    assert transfer.status == models.PlannedTransferStatus.pending
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_transfer_verification.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.services.transfer_verification'`

- [ ] **Step 3: Write the implementation**

```python
# backend/services/transfer_verification.py
"""Matches scheduled PlannedTransfers against real synced/imported
transactions, closing the loop without a second manual confirmation click.
Reuses the same fuzzy amount + date window matching idea already used
elsewhere in this codebase (e.g. import_service.py's recurring-item
auto-match), rather than a new algorithm."""
from __future__ import annotations
from datetime import timedelta
from decimal import Decimal
from sqlalchemy.orm import Session
from backend import models

_DATE_WINDOW_DAYS = 5
_AMOUNT_TOLERANCE_PCT = Decimal("0.05")  # 5%


def verify_scheduled_transfers(db: Session, user_id: int) -> int:
    """Scans this user's `scheduled` PlannedTransfers for a matching real
    transaction on the destination account, within a 5-day window of
    target_date and 5% of the planned amount. On match, flips status to
    `verified` and records the link. Returns the count verified."""
    scheduled = db.query(models.PlannedTransfer).filter(
        models.PlannedTransfer.user_id == user_id,
        models.PlannedTransfer.status == models.PlannedTransferStatus.scheduled,
    ).all()

    verified_count = 0
    for transfer in scheduled:
        window_start = transfer.target_date - timedelta(days=_DATE_WINDOW_DAYS)
        window_end = transfer.target_date + timedelta(days=_DATE_WINDOW_DAYS)
        low = transfer.amount * (1 - _AMOUNT_TOLERANCE_PCT)
        high = transfer.amount * (1 + _AMOUNT_TOLERANCE_PCT)

        match = db.query(models.Transaction).filter(
            models.Transaction.user_id == user_id,
            models.Transaction.account_id == transfer.to_account_id,
            models.Transaction.date >= window_start,
            models.Transaction.date <= window_end,
            models.Transaction.amount >= low,
            models.Transaction.amount <= high,
        ).first()

        if match:
            transfer.status = models.PlannedTransferStatus.verified
            transfer.verified_transaction_id = match.id
            verified_count += 1

    if verified_count:
        db.commit()
    return verified_count
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_transfer_verification.py -v`
Expected: 4 passed

- [ ] **Step 5: Wire into the daily bank-sync job**

In `backend/main.py`, find `_run_bank_sync`:

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

Replace with:

```python
def _run_bank_sync() -> None:
    from backend.database import SessionLocal
    from backend import models
    from backend.services.bank_sync_service import sync_all
    from backend.services.transfer_verification import verify_scheduled_transfers
    db = SessionLocal()
    try:
        sync_all(db)
        for user in db.query(models.User).filter(models.User.is_active == True).all():
            try:
                verify_scheduled_transfers(db, user.id)
            except Exception as exc:
                logger.error("Transfer verification failed for %s: %s", user.username, exc)
    except Exception as exc:
        logger.error("Bank sync job failed: %s", exc)
    finally:
        db.close()
```

- [ ] **Step 6: Verify the app boots with no import errors**

Run: `cd backend && python -c "from backend.main import app; print('OK')"`
Expected: prints `OK` with no exceptions

- [ ] **Step 7: Run the full backend suite**

Run: `cd backend && python -m pytest -v`
Expected: all tests pass

- [ ] **Step 8: Commit**

```bash
git add backend/services/transfer_verification.py backend/main.py backend/tests/test_transfer_verification.py
git commit -m "Auto-verify scheduled transfers against real synced transactions, piggybacked on the daily sync job"
```

---

### Task 7: /forecast/risk integration

**Files:**
- Modify: `backend/routers/forecast.py`
- Test: `backend/tests/test_forecast_risk_suggestion.py`

**Interfaces:**
- Consumes: `forecast_engine.suggest_transfer` (Task 3); existing `find_balance_risk`, `find_transfer_signal`, `build_forecast`
- Produces: `GET /forecast/risk` response now includes `suggested_transfer_amount`, `suggested_transfer_date`, `suggested_transfer_from_account_id`, `suggested_transfer_already_planned` — consumed by Task 8 (frontend)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_forecast_risk_suggestion.py
from datetime import date, timedelta
from decimal import Decimal
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.routers import forecast as forecast_router_module
from backend.dependencies import get_db, get_current_user


@pytest.fixture()
def client(db_session):
    user = models.User(username="dan", hashed_password="x", display_name="Dan")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    checking = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking, current_balance=Decimal("1000.00"))
    savings = models.Account(user_id=user.id, name="Savings", type=models.AccountType.savings, current_balance=Decimal("30000.00"))
    db_session.add_all([checking, savings])
    db_session.commit()
    db_session.refresh(checking)

    app = FastAPI()
    app.include_router(forecast_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app), user, checking


def test_risk_response_includes_suggestion_when_at_risk(client):
    test_client, user, checking = client
    db = test_client.app.dependency_overrides[get_db]()
    db.add(models.PlannedExpense(
        user_id=user.id, name="Big Expense", amount=Decimal("5000.00"),
        expected_date=date.today() + timedelta(days=10),
    ))
    db.commit()

    resp = test_client.get("/forecast/risk", params={"account_id": checking.id, "days": 90})

    assert resp.status_code == 200
    body = resp.json()
    assert body["at_risk"] is True
    assert body["suggested_transfer_amount"] is not None
    assert body["suggested_transfer_already_planned"] is False


def test_risk_response_has_no_suggestion_when_not_at_risk(client):
    test_client, user, checking = client

    resp = test_client.get("/forecast/risk", params={"account_id": checking.id, "days": 90})

    assert resp.status_code == 200
    body = resp.json()
    assert body["at_risk"] is False
    assert body["suggested_transfer_amount"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_forecast_risk_suggestion.py -v`
Expected: FAIL — `suggested_transfer_amount` missing from the response body (KeyError or assertion failure), since the endpoint doesn't populate it yet

- [ ] **Step 3: Write the implementation**

In `backend/routers/forecast.py`, add to the import line:

```python
from backend.services.forecast_engine import build_forecast, build_quarters, find_balance_risk, find_transfer_signal, suggest_transfer
```

In `get_forecast_risk`, after `transfer = find_transfer_signal(entries)`, add:

```python
    suggestion = suggest_transfer(db, user, account_id, risk)
```

Then update the `return schemas.ForecastRisk(...)` call to add the four new fields:

```python
    return schemas.ForecastRisk(
        at_risk=risk["at_risk"],
        date=risk["date"],
        amount=risk["amount"],
        threshold=risk["threshold"],
        transfer_triggered=transfer["triggered"],
        transfer_date=transfer["date"],
        transfer_amount=transfer["amount"],
        transfer_from=transfer["from_name"],
        action_threshold=active_rule.action_threshold if active_rule else None,
        suggested_transfer_amount=suggestion["amount"],
        suggested_transfer_date=suggestion["date"],
        suggested_transfer_from_account_id=suggestion["from_account_id"],
        suggested_transfer_already_planned=suggestion["already_planned"],
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_forecast_risk_suggestion.py -v`
Expected: 2 passed

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && python -m pytest -v`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add backend/routers/forecast.py backend/tests/test_forecast_risk_suggestion.py
git commit -m "Surface suggested transfer on GET /forecast/risk"
```

---

### Task 8: Frontend — accept/dismiss suggestion + persistent reminder banner

**Files:**
- Modify: `frontend/src/api/index.ts`
- Modify: `frontend/src/components/RiskBanner.tsx`
- Create: `frontend/src/components/PlannedTransferReminder.tsx`
- Modify: `frontend/src/pages/Dashboard.tsx`
- Modify: `frontend/src/pages/Forecast.tsx`

**Interfaces:**
- Consumes: `GET/POST/PATCH/DELETE /planned-transfers`, `POST /planned-transfers/{id}/mark-scheduled` (Task 5); `GET /forecast/risk`'s new `suggested_transfer_*` fields (Task 7)
- Produces: `plannedTransfersApi` (exported from `frontend/src/api/index.ts`); extended `RiskBanner` with an Accept/Dismiss action; new `PlannedTransferReminder` component rendered on Dashboard and Forecast

This app has no frontend automated test framework (existing, confirmed convention from the bank-sync build) — verify via `tsc -b` before/after comparison (no new errors) and, once Interceptor's test-profile is configured, a real-Chrome pass. Both steps included below.

- [ ] **Step 1: Add the API client**

In `frontend/src/api/index.ts`, add after `plannedExpensesApi` (or the nearest existing `Api` block — match this file's existing section-comment style):

```typescript
// ── Planned Transfers ────────────────────────────────────────────────────────
export const plannedTransfersApi = {
  list: () => api.get("/planned-transfers").then((r) => r.data),
  create: (data: object) => api.post("/planned-transfers", data).then((r) => r.data),
  update: (id: number, data: object) => api.patch(`/planned-transfers/${id}`, data).then((r) => r.data),
  markScheduled: (id: number) => api.post(`/planned-transfers/${id}/mark-scheduled`).then((r) => r.data),
  remove: (id: number) => api.delete(`/planned-transfers/${id}`),
};
```

- [ ] **Step 2: Extend RiskBanner with the suggestion**

In `frontend/src/components/RiskBanner.tsx`, update the `Risk` interface to add the new fields, and accept an `onAccept` callback prop:

```typescript
interface Risk {
  at_risk: boolean;
  date: string | null;
  amount: string | null;
  threshold: string;
  transfer_triggered?: boolean;
  transfer_date?: string | null;
  transfer_amount?: string | null;
  transfer_from?: string | null;
  suggested_transfer_amount?: string | null;
  suggested_transfer_date?: string | null;
  suggested_transfer_from_account_id?: number | null;
  suggested_transfer_already_planned?: boolean;
}
```

Update the component signature and add a new banner block, right after the existing `showTransfer` block:

```tsx
export function RiskBanner({ risk, onAcceptSuggestion }: { risk: Risk | undefined; onAcceptSuggestion?: (amount: string, date: string, fromAccountId: number | null) => void }) {
  if (!risk) return null;

  const showAlert = risk.at_risk && risk.date && risk.amount != null;
  const showTransfer = risk.transfer_triggered && risk.transfer_date && risk.transfer_amount != null;
  const showSuggestion = risk.at_risk && !risk.suggested_transfer_already_planned && risk.suggested_transfer_amount != null && risk.suggested_transfer_date != null;

  if (!showAlert && !showTransfer && !showSuggestion) return null;

  return (
    <div className="flex flex-col gap-2">
      {showTransfer && (
        /* ...unchanged existing block... */
      )}
      {showSuggestion && onAcceptSuggestion && (
        <div className="card border-blue-200 dark:border-blue-700 bg-blue-50/60 dark:bg-blue-900/20">
          <div className="flex items-start gap-3">
            <ArrowRightLeft size={18} className="text-blue-500 mt-0.5 shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="font-semibold text-blue-900 dark:text-blue-200 text-sm">
                {`Suggested: move ${fmt(parseFloat(risk.suggested_transfer_amount!))} to cover this by ${formatDate(risk.suggested_transfer_date!)}`}
              </p>
              <p className="text-xs text-blue-700 dark:text-blue-400 mt-0.5">
                You'll need to make this transfer yourself in your bank — accepting just plans it here.
              </p>
              <button
                onClick={() => onAcceptSuggestion(risk.suggested_transfer_amount!, risk.suggested_transfer_date!, risk.suggested_transfer_from_account_id ?? null)}
                className="btn-primary btn-sm text-xs px-3 py-1.5 mt-2"
              >
                Accept
              </button>
            </div>
          </div>
        </div>
      )}
      {showAlert && (
        /* ...unchanged existing block... */
      )}
    </div>
  );
}
```

(The full unchanged `showTransfer`/`showAlert` JSX blocks are exactly what's already in the file today — only the new `showSuggestion` block and the function signature are new. Do not touch the two existing blocks' content.)

- [ ] **Step 3: Write the reminder component**

```tsx
// frontend/src/components/PlannedTransferReminder.tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { plannedTransfersApi, accountsApi } from "../api";
import { fmt } from "../lib/utils";
import { Landmark, Check, Trash2, Pencil, X } from "lucide-react";

function formatDate(iso: string): string {
  return new Date(iso + "T00:00:00").toLocaleDateString("en-US", { month: "long", day: "numeric" });
}

export function PlannedTransferReminder() {
  const qc = useQueryClient();
  const { data: transfers = [] } = useQuery<any[]>({ queryKey: ["planned-transfers"], queryFn: plannedTransfersApi.list });
  const { data: accounts = [] } = useQuery<any[]>({ queryKey: ["accounts"], queryFn: accountsApi.list });
  const accountName = (id: number | null) => accounts.find((a: any) => a.id === id)?.name ?? "Savings";

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editAmount, setEditAmount] = useState("");
  const [editDate, setEditDate] = useState("");

  const markScheduledMut = useMutation({
    mutationFn: plannedTransfersApi.markScheduled,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["planned-transfers"] }),
  });
  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: number; data: object }) => plannedTransfersApi.update(id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["planned-transfers"] });
      qc.invalidateQueries({ queryKey: ["forecast-risk"] });
      setEditingId(null);
    },
  });
  const removeMut = useMutation({
    mutationFn: plannedTransfersApi.remove,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["planned-transfers"] });
      qc.invalidateQueries({ queryKey: ["forecast-risk"] });
    },
  });

  function startEdit(t: any) {
    setEditingId(t.id);
    setEditAmount(t.amount);
    setEditDate(t.target_date);
  }
  function saveEdit(id: number) {
    updateMut.mutate({ id, data: { amount: parseFloat(editAmount), target_date: editDate } });
  }

  const active = transfers.filter((t: any) => t.status === "pending" || t.status === "scheduled");
  if (active.length === 0) return null;

  return (
    <div className="card border-amber-200 dark:border-amber-700 bg-amber-50/60 dark:bg-amber-900/20 space-y-2">
      {active.map((t: any) => (
        <div key={t.id} className="flex items-center justify-between gap-3">
          {editingId === t.id ? (
            <div className="flex items-center gap-2 flex-1">
              <input type="number" step="1" className="input w-28 text-sm" value={editAmount} onChange={(e) => setEditAmount(e.target.value)} autoFocus />
              <input type="date" className="input text-sm" value={editDate} onChange={(e) => setEditDate(e.target.value)} />
              <button onClick={() => saveEdit(t.id)} disabled={updateMut.isPending} className="text-green-600"><Check size={16} /></button>
              <button onClick={() => setEditingId(null)} className="text-gray-400"><X size={16} /></button>
            </div>
          ) : (
            <div className="flex items-center gap-2 min-w-0">
              <Landmark size={16} className="text-amber-500 shrink-0" />
              <p className="text-sm text-amber-900 dark:text-amber-200 truncate">
                {t.status === "scheduled" ? "Scheduled — waiting to verify: " : "Move "}
                <strong>{fmt(parseFloat(t.amount))}</strong> {accountName(t.from_account_id)} → {accountName(t.to_account_id)} by {formatDate(t.target_date)}
              </p>
            </div>
          )}
          {editingId !== t.id && (
            <div className="flex items-center gap-1 shrink-0">
              {t.status === "pending" && (
                <button
                  onClick={() => markScheduledMut.mutate(t.id)}
                  disabled={markScheduledMut.isPending}
                  className="btn-secondary text-xs px-2 py-1 flex items-center gap-1"
                >
                  <Check size={12} /> Mark Scheduled
                </button>
              )}
              <button onClick={() => startEdit(t)} className="btn-ghost p-1.5"><Pencil size={14} /></button>
              <button onClick={() => removeMut.mutate(t.id)} className="btn-ghost p-1.5 text-red-400 hover:bg-red-50">
                <Trash2 size={14} />
              </button>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
```

Editing (amount and/or date) is available on both `pending` and `scheduled` rows via the pencil icon, reusing the same `PATCH /planned-transfers/{id}` endpoint Task 5 already built — satisfies "move, change, or delete" from the spec without a separate management page.

- [ ] **Step 4: Wire the Accept action + reminder into Forecast.tsx**

In `frontend/src/pages/Forecast.tsx`, add to the imports:

```typescript
import { plannedTransfersApi } from "../api";
import { PlannedTransferReminder } from "../components/PlannedTransferReminder";
```

Near the existing `risk` query, add a mutation (place alongside other `useMutation` calls in this file). This file already declares `const qc = useQueryClient();` at the top (line 30) — reuse it, do not declare a second one:

```typescript
  const acceptSuggestionMut = useMutation({
    mutationFn: (data: { to_account_id: number; from_account_id: number | null; amount: string; target_date: string }) =>
      plannedTransfersApi.create(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["planned-transfers"] });
      qc.invalidateQueries({ queryKey: ["forecast-risk"] });
    },
  });
```

Update the existing `{activeAccountId && <RiskBanner risk={risk} />}` line to:

```tsx
      {activeAccountId && (
        <RiskBanner
          risk={risk}
          onAcceptSuggestion={(amount, targetDate, fromAccountId) =>
            acceptSuggestionMut.mutate({ to_account_id: activeAccountId, from_account_id: fromAccountId, amount, target_date: targetDate })
          }
        />
      )}
      <PlannedTransferReminder />
```

- [ ] **Step 5: Wire the reminder into Dashboard.tsx**

In `frontend/src/pages/Dashboard.tsx`, add to the imports:

```typescript
import { PlannedTransferReminder } from "../components/PlannedTransferReminder";
```

Add `<PlannedTransferReminder />` immediately before the existing `{weeklyDigest?.risk && <RiskBanner risk={weeklyDigest.risk} />}` line.

- [ ] **Step 6: Verify no new TypeScript errors**

Run: `cd frontend && npx tsc -b 2>&1 | grep -c "error TS"` before and after this task's changes (stash/restore or compare against the known pre-existing count, same methodology as the bank-sync build's Task 7). There are pre-existing unrelated errors in this codebase — the requirement is zero *new* ones, not zero total.

- [ ] **Step 7: Manual visual verification**

Use the Interceptor skill (real Chrome) if the test profile is configured on this machine: start the app, open Forecast with an account known to be at risk, confirm the suggestion banner renders and Accept creates a row in the reminder banner; confirm Mark Scheduled and Delete both work; confirm the reminder also appears on Dashboard. If Interceptor's test profile isn't configured, note this explicitly in the task report — do not skip silently.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/api/index.ts frontend/src/components/RiskBanner.tsx frontend/src/components/PlannedTransferReminder.tsx frontend/src/pages/Dashboard.tsx frontend/src/pages/Forecast.tsx
git commit -m "Add transfer suggestion accept/dismiss and persistent scheduling reminder"
```

---

### Task 9: Frontend — transfer_increment Settings field

**Files:**
- Modify: `frontend/src/pages/Settings.tsx`

**Interfaces:**
- Consumes: `authApi.updateMe` (existing, already used by the Tax Profile section in this same file), `me.transfer_increment` (from `GET /auth/me`, now included per Task 2's `UserOut` extension)
- Produces: nothing consumed by other tasks — terminal task

- [ ] **Step 1: Add state and load it from `me`**

In `frontend/src/pages/Settings.tsx`, find the `React.useEffect` block that seeds state from `me` (the one setting `setSsGross`, `setTaxFilingStatus`, etc.) and add a new state declaration near the other `useState` calls for that section, plus its seed line inside the effect:

```typescript
  const [transferIncrement, setTransferIncrement] = useState("");
```

Inside the `React.useEffect(() => { if (me) { ... } }, [me])` block, add:

```typescript
      setTransferIncrement(me.transfer_increment ?? "1000");
```

- [ ] **Step 2: Add the input to the Preferences section**

In the `{/* ── Preferences ── */}` card, add a new row after the existing "Navigation Order" block (before the closing `</div>` of that section):

```tsx
        <div className="pt-3 border-t border-gray-100 dark:border-gray-700">
          <div className="flex items-center justify-between gap-3">
            <div>
              <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Suggested Transfer Increment</span>
              <p className="text-xs text-gray-400">Suggested transfers round up to this amount (e.g. $1,000 steps)</p>
            </div>
            <div className="flex items-center gap-2">
              <input
                type="number"
                step="1"
                className="input w-28 text-sm text-right"
                value={transferIncrement}
                onChange={(e) => setTransferIncrement(e.target.value)}
              />
              <button
                onClick={() => taxMut.mutate({ transfer_increment: transferIncrement ? parseFloat(transferIncrement) : null })}
                disabled={taxMut.isPending}
                className="btn-secondary text-xs px-3 py-1.5"
              >
                {taxMut.isPending ? "Saving…" : "Save"}
              </button>
            </div>
          </div>
        </div>
```

This reuses the existing `taxMut` mutation (`authApi.updateMe`, already bound in this file) since it's the same "PATCH my user profile" endpoint — no new mutation needed.

- [ ] **Step 3: Verify no new TypeScript errors**

Run: `cd frontend && npx tsc -b 2>&1 | grep -c "error TS"` — compare against the pre-task count, confirm no increase.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Settings.tsx
git commit -m "Add Suggested Transfer Increment setting to Preferences"
```

---

## Post-Plan Note

Adding the actual Rivian R2 down payment as a `PlannedExpense` (~$21,000, target date within Q3 2026 per Dan's stated Sept/Oct-leaning window) is a data-entry step, not a code task — done via the existing Planned Expenses UI (or the existing `POST /planned-expenses` endpoint directly) once this plan ships, so the new suggestion logic has something real to act on immediately.
