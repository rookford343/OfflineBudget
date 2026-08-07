# Checking Buffer Transfer + Two-Tier Low-Balance Alert Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Model Dan's real "top up Checking from Savings when it gets low" habit inside the forecast engine, so the app's projection stops diverging from his spreadsheet, and surface a second, harder low-balance tier that reflects when that top-up actually fires.

**Architecture:** A new `BufferTransferRule` table (Savings → Checking, thresholds, increment, check day) drives a dry-run-then-inject pass inside `forecast_engine.build_forecast()`: first project the destination account with no transfers applied, decide month-by-month whether a transfer is needed, then inject it (and a mirrored outflow on the source account) into the real walk. A new `find_transfer_signal()` helper surfaces the first scheduled transfer to the `/forecast/risk` API and the Forecast page's risk banner.

**Tech Stack:** FastAPI + SQLAlchemy (Python 3.11) backend, pytest for tests, React + TypeScript frontend, Typer CLI.

## Global Constraints

- Dan's chosen rule values (seed these as the CLI defaults, not hardcoded elsewhere): action threshold **$100**, target floor **$200**, increment **$1,000**, check day **1st of month**, source account **Savings**, destination account **Main Checking**.
- The existing `low_balance_threshold` field ($500 today) is untouched and keeps meaning "soft alert" — do not repurpose it.
- No new `RecurringType` enum value — transfers are conditional, not a fixed recurring amount (see spec's "New model" rationale).
- Accounts/users/recurring items without any `BufferTransferRule` must see **zero behavior change** in `build_forecast()` output — this is a regression guard, verify it explicitly.
- Follow existing code conventions exactly: SQLAlchemy `Mapped[...]`/`mapped_column(...)` style in `backend/models.py`, Pydantic `BaseModel` style in `backend/schemas.py`, Typer command-group style in `cli/budget.py` (see `accounts_app`/`recurring_app`).

---

## File Structure

- **Modify** `backend/models.py` — add `BufferTransferRule` model + relationships on `User`/`Account`.
- **Modify** `backend/schemas.py` — add `BufferTransferRuleCreate`/`BufferTransferRuleOut`, extend `ForecastTransaction` with `is_transfer`, extend `ForecastRisk` with transfer fields.
- **Modify** `backend/services/forecast_engine.py` — add `apply_buffer_transfers` param, `_compute_transfer_schedule()` helper, injection in the day loop, `find_transfer_signal()`.
- **Modify** `backend/routers/forecast.py` — wire `find_transfer_signal()` into `GET /forecast/risk`.
- **Modify** `cli/budget.py` — new `transfers_app` command group (`add`, `list`).
- **Modify** `frontend/src/components/RiskBanner.tsx` — render the second, transfer-triggered banner.
- **Create** `backend/tests/test_buffer_transfer_schedule.py` — unit tests for `_compute_transfer_schedule()`.
- **Create** `backend/tests/test_buffer_transfer_injection.py` — integration tests for `build_forecast()` with a `BufferTransferRule` in play (DB-backed, via `db_session` fixture).
- **Modify** `backend/tests/test_forecast_risk.py` — add `find_transfer_signal()` tests alongside the existing `find_balance_risk()` tests.

---

### Task 1: `BufferTransferRule` model + schemas

**Files:**
- Modify: `backend/models.py:118` (insert relationship on `User`), `backend/models.py:151` (insert relationships on `Account`), and add the new class after the `RecurringItem` class (after line 206, before the `# ── Transactions ──` comment).
- Modify: `backend/schemas.py` (add new schemas near the other Forecast schemas, after `ForecastRisk` at line 317; extend `ForecastTransaction` at line 295-304 and `ForecastRisk` at line 313-317).
- Test: `backend/tests/test_buffer_transfer_schedule.py` (new file — model smoke test only in this task; schedule-computation tests come in Task 2).

**Interfaces:**
- Produces: `models.BufferTransferRule` with columns `id, user_id, from_account_id, to_account_id, action_threshold, target_floor, increment, check_day, is_active, created_at, updated_at`, relationships `user`, `from_account`, `to_account`.
- Produces: `schemas.ForecastTransaction.is_transfer: bool = False` (new field, default preserves existing callers).
- Produces: `schemas.ForecastRisk.transfer_triggered: bool`, `.transfer_date: Optional[date]`, `.transfer_amount: Optional[Decimal]`, `.transfer_from: Optional[str]` (all with defaults — existing callers unaffected).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_buffer_transfer_schedule.py`:

```python
from decimal import Decimal
from backend import models


def test_buffer_transfer_rule_persists_with_expected_defaults(db_session):
    user = models.User(username="t", hashed_password="x", display_name="T")
    db_session.add(user)
    db_session.flush()
    savings = models.Account(user_id=user.id, name="Savings", type=models.AccountType.savings, current_balance=Decimal("0"))
    checking = models.Account(user_id=user.id, name="Main Checking", type=models.AccountType.checking, current_balance=Decimal("0"))
    db_session.add_all([savings, checking])
    db_session.flush()

    rule = models.BufferTransferRule(
        user_id=user.id,
        from_account_id=savings.id,
        to_account_id=checking.id,
        action_threshold=Decimal("100.00"),
        target_floor=Decimal("200.00"),
        increment=Decimal("1000.00"),
        check_day=1,
    )
    db_session.add(rule)
    db_session.commit()
    db_session.refresh(rule)

    assert rule.id is not None
    assert rule.is_active is True
    assert rule.from_account.name == "Savings"
    assert rule.to_account.name == "Main Checking"
    assert savings.outgoing_buffer_rules == [rule]
    assert checking.incoming_buffer_rules == [rule]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_buffer_transfer_schedule.py -v`
Expected: FAIL with `AttributeError: module 'backend.models' has no attribute 'BufferTransferRule'`

- [ ] **Step 3: Add the model**

In `backend/models.py`, insert this class immediately after the `RecurringItem` class (after line 206, before the `# ── Transactions ──` section comment):

```python
class BufferTransferRule(Base):
    """Conditional monthly transfer: if `to_account` would dip below
    `action_threshold` before the next check_day, transfer `increment`-sized
    steps from `from_account` until it clears `target_floor`."""
    __tablename__ = "buffer_transfer_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    from_account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False)
    to_account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False)
    action_threshold: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    target_floor: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    increment: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    check_day: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship(back_populates="buffer_transfer_rules")
    from_account: Mapped[Account] = relationship(foreign_keys=[from_account_id], back_populates="outgoing_buffer_rules")
    to_account: Mapped[Account] = relationship(foreign_keys=[to_account_id], back_populates="incoming_buffer_rules")
```

Then add the `User` relationship — insert this line immediately after `backend/models.py:118` (the `savings_transfers` relationship line):

```python
    buffer_transfer_rules: Mapped[list[BufferTransferRule]] = relationship(back_populates="user", cascade="all, delete-orphan")
```

Then add the `Account` relationships — insert these lines immediately after `backend/models.py:151` (the `incoming_transfers` relationship line):

```python
    outgoing_buffer_rules: Mapped[list[BufferTransferRule]] = relationship(foreign_keys="BufferTransferRule.from_account_id", back_populates="from_account")
    incoming_buffer_rules: Mapped[list[BufferTransferRule]] = relationship(foreign_keys="BufferTransferRule.to_account_id", back_populates="to_account")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_buffer_transfer_schedule.py -v`
Expected: PASS

- [ ] **Step 5: Extend schemas.py**

In `backend/schemas.py`, change the `ForecastTransaction` class (currently lines 295-304) to add one field:

```python
class ForecastTransaction(BaseModel):
    name: str
    amount: Decimal
    type: str  # "income" | "expense" | "credit_card_payment"
    category_name: Optional[str]
    is_actual: bool
    is_planned: bool = False
    is_cc_payment: bool = False
    is_transfer: bool = False
    recurring_item_id: Optional[int] = None
    transaction_id: Optional[int] = None
```

Change the `ForecastRisk` class (currently lines 313-317) to add the transfer-signal fields:

```python
class ForecastRisk(BaseModel):
    at_risk: bool
    date: Optional[date]
    amount: Optional[Decimal]
    threshold: Decimal
    transfer_triggered: bool = False
    transfer_date: Optional[date] = None
    transfer_amount: Optional[Decimal] = None
    transfer_from: Optional[str] = None
```

Add these new schemas directly after the `ForecastRisk` class:

```python
class BufferTransferRuleCreate(BaseModel):
    from_account_id: int
    to_account_id: int
    action_threshold: Decimal
    target_floor: Decimal
    increment: Decimal = Decimal("1000.00")
    check_day: int = 1

    @field_validator("target_floor")
    @classmethod
    def floor_above_threshold(cls, v, info):
        threshold = info.data.get("action_threshold")
        if threshold is not None and v <= threshold:
            raise ValueError("target_floor must be greater than action_threshold")
        return v


class BufferTransferRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    from_account_id: int
    to_account_id: int
    action_threshold: Decimal
    target_floor: Decimal
    increment: Decimal
    check_day: int
    is_active: bool
```

- [ ] **Step 6: Run the full backend test suite**

Run: `cd backend && python -m pytest -q`
Expected: PASS (no regressions — `create_all` picks up the new table automatically, no migration statement needed since it's a brand-new table)

- [ ] **Step 7: Commit**

```bash
cd ~/Programming/Dev/OfflineBudget
git add backend/models.py backend/schemas.py backend/tests/test_buffer_transfer_schedule.py
git commit -m "feat: add BufferTransferRule model and forecast schema fields"
```

---

### Task 2: Schedule computation — `_compute_transfer_schedule()`

**Files:**
- Modify: `backend/services/forecast_engine.py` (add helper near the top, after `_adjust_for_weekend` at line 28).
- Test: `backend/tests/test_buffer_transfer_schedule.py` (append to the file from Task 1).

**Interfaces:**
- Consumes: `models.BufferTransferRule` (Task 1), `build_forecast(db, user_id, account_id, start_date, end_date, *, overrides=None, apply_buffer_transfers=True)` — note the new `apply_buffer_transfers` kwarg this task adds to the signature (implemented in Task 3, but Task 2's helper already calls it with `apply_buffer_transfers=False`, so Task 2 and Task 3 must land together — do not commit Task 2 alone if it breaks the build; see Step 2 below for why the test still passes standalone).
- Produces: `_compute_transfer_schedule(db, user_id, rule, start_date, end_date) -> dict[date, Decimal]` — maps each check-day that needs a transfer to the transfer amount.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_buffer_transfer_schedule.py`:

```python
from datetime import date
from backend.services.forecast_engine import _compute_transfer_schedule


def _make_user_accounts(db):
    user = models.User(username="t2", hashed_password="x", display_name="T2")
    db.add(user)
    db.flush()
    savings = models.Account(user_id=user.id, name="Savings", type=models.AccountType.savings, current_balance=Decimal("0"))
    checking = models.Account(user_id=user.id, name="Main Checking", type=models.AccountType.checking, current_balance=Decimal("500.00"))
    db.add_all([savings, checking])
    db.flush()
    return user, savings, checking


def _make_rule(db, user, savings, checking, action=Decimal("100"), floor=Decimal("200"), increment=Decimal("1000"), check_day=1):
    rule = models.BufferTransferRule(
        user_id=user.id, from_account_id=savings.id, to_account_id=checking.id,
        action_threshold=action, target_floor=floor, increment=increment, check_day=check_day,
    )
    db.add(rule)
    db.flush()
    return rule


def test_schedule_empty_when_balance_never_dips_below_action_threshold(db_session):
    user, savings, checking = _make_user_accounts(db_session)
    rule = _make_rule(db_session, user, savings, checking)
    db_session.commit()

    schedule = _compute_transfer_schedule(db_session, user.id, rule, date(2026, 7, 1), date(2026, 7, 31))
    assert schedule == {}


def test_schedule_injects_rounded_up_transfer_when_shortfall_detected(db_session):
    user, savings, checking = _make_user_accounts(db_session)
    rule = _make_rule(db_session, user, savings, checking)
    # Checking starts at $500, one big expense on 7/15 drops it to -$2,625.
    db_session.add(models.RecurringItem(
        user_id=user.id, account_id=checking.id, name="Big Bill", amount=Decimal("3125.00"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=15, start_date=date(2026, 1, 1),
    ))
    db_session.commit()

    schedule = _compute_transfer_schedule(db_session, user.id, rule, date(2026, 7, 1), date(2026, 7, 31))

    # Raw low is -$2,625; shortfall to $200 floor is $2,825 -> rounds up to $3,000.
    assert schedule == {date(2026, 7, 1): Decimal("3000.00")}


def test_schedule_carries_prior_transfer_credit_into_next_month(db_session):
    user, savings, checking = _make_user_accounts(db_session)
    rule = _make_rule(db_session, user, savings, checking)
    # $3,125 bill on the 15th, $3,000 paycheck on the 20th, every month.
    # The raw (no-transfer) trajectory is cumulative across the whole window,
    # so August's raw low is deeper than July's -- this test exists to prove
    # the credit from July's injected transfer is carried forward correctly
    # rather than each month being evaluated against a reset baseline.
    db_session.add_all([
        models.RecurringItem(
            user_id=user.id, account_id=checking.id, name="Big Bill", amount=Decimal("3125.00"),
            type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
            day_of_month=15, start_date=date(2026, 1, 1),
        ),
        models.RecurringItem(
            user_id=user.id, account_id=checking.id, name="Paycheck", amount=Decimal("3000.00"),
            type=models.RecurringType.income, frequency=models.RecurringFrequency.monthly,
            day_of_month=20, start_date=date(2026, 1, 1),
        ),
    ])
    db_session.commit()

    schedule = _compute_transfer_schedule(db_session, user.id, rule, date(2026, 7, 1), date(2026, 8, 31))

    # July: raw low is -$2,625 (500 open - $3,125 bill, before the day-20
    # paycheck) -> shortfall to the $200 floor is $2,825, rounds up to $3,000.
    assert schedule[date(2026, 7, 1)] == Decimal("3000.00")
    # August: raw low (cumulative, still no transfers applied) is -$2,750.
    # Credited with July's +$3,000 that's $250 -- already clears both the
    # $100 action threshold and the $200 floor, so no second transfer fires.
    assert date(2026, 8, 1) not in schedule
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_buffer_transfer_schedule.py -v`
Expected: FAIL with `ImportError: cannot import name '_compute_transfer_schedule'`

- [ ] **Step 3: Implement `_compute_transfer_schedule()`**

In `backend/services/forecast_engine.py`, add this import to the top (with the other `sqlalchemy` imports):

```python
from decimal import Decimal, ROUND_CEILING
```

(Replace the existing `from decimal import Decimal` line at line 13 with the above — same line, adds `ROUND_CEILING`.)

Add this function immediately after `_adjust_for_weekend` (after line 28, before `_cc_actual_nearby`):

```python
def _compute_transfer_schedule(
    db: Session,
    user_id: int,
    rule: models.BufferTransferRule,
    start_date: date,
    end_date: date,
) -> dict[date, Decimal]:
    """Dry-run `rule.to_account_id` with no transfers applied, then decide on
    each check_day whether a buffer transfer is needed to keep it above
    `rule.action_threshold` before the next check_day. Each month's decision
    credits transfers already scheduled in earlier months, so a transfer
    from July isn't re-counted as still needed in August."""
    raw_entries = build_forecast(
        db, user_id, rule.to_account_id, start_date, end_date,
        apply_buffer_transfers=False,
    )
    if not raw_entries:
        return {}

    check_days: list[date] = []
    cur = date(start_date.year, start_date.month, 1)
    while cur <= end_date:
        last_day = _last_day_of_month(cur)
        cd = date(cur.year, cur.month, min(rule.check_day, last_day))
        if start_date <= cd <= end_date:
            check_days.append(cd)
        cur = date(cur.year + 1, 1, 1) if cur.month == 12 else date(cur.year, cur.month + 1, 1)

    schedule: dict[date, Decimal] = {}
    injected_so_far = Decimal("0")
    for i, cd in enumerate(check_days):
        window_end = check_days[i + 1] - timedelta(days=1) if i + 1 < len(check_days) else end_date
        window = [e for e in raw_entries if cd <= e.date <= window_end]
        if not window:
            continue
        lowest_raw = min(e.projected_balance for e in window)
        lowest_adjusted = lowest_raw + injected_so_far
        if lowest_adjusted < rule.action_threshold:
            shortfall = rule.target_floor - lowest_adjusted
            steps = int((shortfall / rule.increment).to_integral_value(rounding=ROUND_CEILING))
            amount = rule.increment * steps
            schedule[cd] = amount
            injected_so_far += amount

    return schedule
```

Note: this function calls `build_forecast(..., apply_buffer_transfers=False)`, which doesn't exist as a parameter yet — that's added in Task 3. Do Task 3's Step 3 (adding the parameter) before running this task's tests, or run Tasks 2 and 3's implementation steps together before testing either. The test files stay separate because they test different units (schedule math vs. injection into the real walk).

- [ ] **Step 4: Add the `apply_buffer_transfers` parameter stub so Task 2's tests can run**

In `backend/services/forecast_engine.py`, change the `build_forecast` signature (currently ending `overrides: list[dict] | None = None,`) to:

```python
def build_forecast(
    db: Session,
    user_id: int,
    account_id: int,
    start_date: date,
    end_date: date,
    *,
    overrides: list[dict] | None = None,
    apply_buffer_transfers: bool = True,
) -> list[ForecastEntry]:
```

Leave the parameter unused for now (Task 3 wires it up) — this is enough for Task 2's tests to pass since they only exercise `_compute_transfer_schedule`, which itself passes `apply_buffer_transfers=False` and doesn't require the flag to do anything yet (no `BufferTransferRule` rows exist in these tests' dry-run target, so there's nothing to skip).

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_buffer_transfer_schedule.py -v`
Expected: PASS (all 4 tests: the Task 1 model test plus the 3 schedule tests)

- [ ] **Step 6: Run the full backend test suite**

Run: `cd backend && python -m pytest -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
cd ~/Programming/Dev/OfflineBudget
git add backend/services/forecast_engine.py backend/tests/test_buffer_transfer_schedule.py
git commit -m "feat: compute monthly buffer-transfer schedule from a dry-run forecast"
```

---

### Task 3: Inject transfers into `build_forecast()` (both sides)

**Files:**
- Modify: `backend/services/forecast_engine.py` (the `build_forecast` body — load rules, call `_compute_transfer_schedule`, inject into the day loop).
- Test: `backend/tests/test_buffer_transfer_injection.py` (new file).

**Interfaces:**
- Consumes: `_compute_transfer_schedule` (Task 2), `models.BufferTransferRule` (Task 1), `schemas.ForecastTransaction.is_transfer` (Task 1).
- Produces: `build_forecast()` now injects `ForecastTransaction(name="Transfer from {source}", is_transfer=True, ...)` on the destination account and a mirrored negative entry on the source account, on the dates `_compute_transfer_schedule` returns.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_buffer_transfer_injection.py`:

```python
from datetime import date
from decimal import Decimal
from backend import models
from backend.services.forecast_engine import build_forecast


def _make_user_accounts(db):
    user = models.User(username="t3", hashed_password="x", display_name="T3")
    db.add(user)
    db.flush()
    savings = models.Account(user_id=user.id, name="Savings", type=models.AccountType.savings, current_balance=Decimal("10000.00"))
    checking = models.Account(user_id=user.id, name="Main Checking", type=models.AccountType.checking, current_balance=Decimal("500.00"))
    db.add_all([savings, checking])
    db.flush()
    return user, savings, checking


def _make_rule(db, user, savings, checking):
    rule = models.BufferTransferRule(
        user_id=user.id, from_account_id=savings.id, to_account_id=checking.id,
        action_threshold=Decimal("100"), target_floor=Decimal("200"),
        increment=Decimal("1000"), check_day=1,
    )
    db.add(rule)
    db.flush()
    return rule


def _add_big_bill(db, user, checking):
    db.add(models.RecurringItem(
        user_id=user.id, account_id=checking.id, name="Big Bill", amount=Decimal("3125.00"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=15, start_date=date(2026, 1, 1),
    ))


def test_no_rule_means_no_behavior_change(db_session):
    user, savings, checking = _make_user_accounts(db_session)
    _add_big_bill(db_session, user, checking)
    db_session.commit()

    with_flag = build_forecast(db_session, user.id, checking.id, date(2026, 7, 1), date(2026, 7, 31))
    without_flag = build_forecast(db_session, user.id, checking.id, date(2026, 7, 1), date(2026, 7, 31), apply_buffer_transfers=False)

    assert [e.projected_balance for e in with_flag] == [e.projected_balance for e in without_flag]
    assert not any(t.is_transfer for e in with_flag for t in e.transactions)


def test_transfer_injected_on_checking_when_rule_active(db_session):
    user, savings, checking = _make_user_accounts(db_session)
    _make_rule(db_session, user, savings, checking)
    _add_big_bill(db_session, user, checking)
    db_session.commit()

    entries = build_forecast(db_session, user.id, checking.id, date(2026, 7, 1), date(2026, 7, 31))

    jul1 = next(e for e in entries if e.date == date(2026, 7, 1))
    transfer_txns = [t for t in jul1.transactions if t.is_transfer]
    assert len(transfer_txns) == 1
    assert transfer_txns[0].amount == Decimal("3000.00")
    assert transfer_txns[0].name == "Transfer from Savings"

    jul15 = next(e for e in entries if e.date == date(2026, 7, 15))
    # $500 open + $3,000 transfer - $3,125 bill = $375, never dips negative.
    assert jul15.projected_balance == Decimal("375.00")


def test_transfer_mirrored_as_outflow_on_savings(db_session):
    user, savings, checking = _make_user_accounts(db_session)
    _make_rule(db_session, user, savings, checking)
    _add_big_bill(db_session, user, checking)
    db_session.commit()

    savings_entries = build_forecast(db_session, user.id, savings.id, date(2026, 7, 1), date(2026, 7, 31))

    jul1 = next(e for e in savings_entries if e.date == date(2026, 7, 1))
    transfer_txns = [t for t in jul1.transactions if t.is_transfer]
    assert len(transfer_txns) == 1
    assert transfer_txns[0].amount == Decimal("-3000.00")
    assert transfer_txns[0].name == "Transfer to Main Checking"
    assert jul1.projected_balance == Decimal("7000.00")  # $10,000 - $3,000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_buffer_transfer_injection.py -v`
Expected: FAIL — `test_no_rule_means_no_behavior_change` passes trivially (no injection wired up yet, both calls identical), but `test_transfer_injected_on_checking_when_rule_active` and `test_transfer_mirrored_as_outflow_on_savings` FAIL because no transfer transactions are ever created yet.

- [ ] **Step 3: Wire up rule loading and injection**

In `backend/services/forecast_engine.py`, add this import at the top (with the other sqlalchemy import):

```python
from sqlalchemy import or_
```

In `build_forecast`, immediately after the `day_checkpoint_map = {...}` block (right before the `# Pre-compute which recurring item IDs have linked actuals...` comment), add:

```python
    incoming_transfer_schedules: list[tuple[models.BufferTransferRule, dict[date, Decimal]]] = []
    outgoing_transfer_schedules: list[tuple[models.BufferTransferRule, dict[date, Decimal]]] = []
    if apply_buffer_transfers:
        transfer_rules = db.query(models.BufferTransferRule).options(
            joinedload(models.BufferTransferRule.from_account),
            joinedload(models.BufferTransferRule.to_account),
        ).filter(
            models.BufferTransferRule.user_id == user_id,
            models.BufferTransferRule.is_active == True,
            or_(
                models.BufferTransferRule.to_account_id == account_id,
                models.BufferTransferRule.from_account_id == account_id,
            ),
        ).all()
        for rule in transfer_rules:
            schedule = _compute_transfer_schedule(db, user_id, rule, start_date, end_date)
            if not schedule:
                continue
            if rule.to_account_id == account_id:
                incoming_transfer_schedules.append((rule, schedule))
            if rule.from_account_id == account_id:
                outgoing_transfer_schedules.append((rule, schedule))
```

Then, inside the main `while current <= end_date:` loop, immediately after the interest-crediting block (`if (interest_rate and interest_rate > 0 and current.day == _last_day_of_month(current)): ...`) and before the `# Apply day checkpoint AFTER all transactions...` comment, add:

```python
        for rule, schedule in incoming_transfer_schedules:
            amt = schedule.get(current)
            if amt:
                balance += amt
                day_transactions.append(ForecastTransaction(
                    name=f"Transfer from {rule.from_account.name}",
                    amount=amt,
                    type="income",
                    category_name=None,
                    is_actual=False,
                    is_transfer=True,
                ))

        for rule, schedule in outgoing_transfer_schedules:
            amt = schedule.get(current)
            if amt:
                balance -= amt
                day_transactions.append(ForecastTransaction(
                    name=f"Transfer to {rule.to_account.name}",
                    amount=-amt,
                    type="expense",
                    category_name=None,
                    is_actual=False,
                    is_transfer=True,
                ))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_buffer_transfer_injection.py -v`
Expected: PASS (all 3 tests)

- [ ] **Step 5: Run the full backend test suite**

Run: `cd backend && python -m pytest -q`
Expected: PASS, no regressions — this is the point to double check `test_forecast_risk.py` and every other existing test still passes untouched.

- [ ] **Step 6: Commit**

```bash
cd ~/Programming/Dev/OfflineBudget
git add backend/services/forecast_engine.py backend/tests/test_buffer_transfer_injection.py
git commit -m "feat: inject buffer transfers into build_forecast on both accounts"
```

---

### Task 4: `find_transfer_signal()` + wire into `/forecast/risk`

**Files:**
- Modify: `backend/services/forecast_engine.py` (add `find_transfer_signal` after `find_balance_risk`, currently ending at line 443).
- Modify: `backend/routers/forecast.py` (the `get_forecast_risk` function, lines 28-40).
- Test: `backend/tests/test_forecast_risk.py` (append).

**Interfaces:**
- Consumes: `ForecastEntry`/`ForecastTransaction.is_transfer` (Task 1, Task 3).
- Produces: `find_transfer_signal(entries: list[ForecastEntry]) -> dict` with keys `triggered, date, amount, from_name` — same shape convention as `find_balance_risk`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_forecast_risk.py`:

```python
from backend.schemas import ForecastTransaction
from backend.services.forecast_engine import find_transfer_signal


def _entry_with_transfer(d: date, balance: str, transfer_amount: str | None = None, name: str = "Transfer from Savings") -> ForecastEntry:
    txns = []
    if transfer_amount is not None:
        txns.append(ForecastTransaction(
            name=name, amount=Decimal(transfer_amount), type="income",
            category_name=None, is_actual=False, is_transfer=True,
        ))
    return ForecastEntry(date=d, projected_balance=Decimal(balance), transactions=txns)


def test_find_transfer_signal_returns_not_triggered_when_no_transfers():
    entries = [_entry_with_transfer(date(2026, 8, 1), "500.00")]
    result = find_transfer_signal(entries)
    assert result == {"triggered": False, "date": None, "amount": None, "from_name": None}


def test_find_transfer_signal_returns_first_transfer():
    entries = [
        _entry_with_transfer(date(2026, 8, 1), "500.00"),
        _entry_with_transfer(date(2026, 9, 1), "3375.00", transfer_amount="3000.00", name="Transfer from Savings"),
    ]
    result = find_transfer_signal(entries)
    assert result == {
        "triggered": True,
        "date": date(2026, 9, 1),
        "amount": Decimal("3000.00"),
        "from_name": "Savings",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_forecast_risk.py -v`
Expected: FAIL with `ImportError: cannot import name 'find_transfer_signal'`

- [ ] **Step 3: Implement `find_transfer_signal()`**

In `backend/services/forecast_engine.py`, add this function immediately after `find_balance_risk` (after line 443):

```python
def find_transfer_signal(entries: list[ForecastEntry]) -> dict:
    """Scan forecast entries in order and return the first scheduled buffer
    transfer (a ForecastTransaction with is_transfer=True and a positive
    amount, i.e. money arriving). entries must already be sorted by date
    ascending (build_forecast returns them in that order).
    """
    for entry in entries:
        for txn in entry.transactions:
            if txn.is_transfer and txn.amount > 0:
                from_name = txn.name.removeprefix("Transfer from ")
                return {
                    "triggered": True,
                    "date": entry.date,
                    "amount": txn.amount,
                    "from_name": from_name,
                }
    return {"triggered": False, "date": None, "amount": None, "from_name": None}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_forecast_risk.py -v`
Expected: PASS

- [ ] **Step 5: Wire into the router**

In `backend/routers/forecast.py`, change the import line:

```python
from backend.services.forecast_engine import build_forecast, build_quarters, find_balance_risk, find_transfer_signal
```

Then replace the body of `get_forecast_risk` (lines 28-40) with:

```python
@router.get("/risk", response_model=schemas.ForecastRisk)
def get_forecast_risk(
    account_id: int,
    days: int = Query(default=90, ge=1, le=730),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    account = db.query(models.Account).filter(
        models.Account.id == account_id,
        models.Account.user_id == user.id,
    ).first()
    threshold = account.low_balance_threshold if account and account.low_balance_threshold is not None else Decimal("0")
    start = date.today()
    end = start + timedelta(days=days)
    entries = build_forecast(db, user.id, account_id, start, end)
    risk = find_balance_risk(entries, threshold)
    transfer = find_transfer_signal(entries)
    return schemas.ForecastRisk(
        at_risk=risk["at_risk"],
        date=risk["date"],
        amount=risk["amount"],
        threshold=risk["threshold"],
        transfer_triggered=transfer["triggered"],
        transfer_date=transfer["date"],
        transfer_amount=transfer["amount"],
        transfer_from=transfer["from_name"],
    )
```

- [ ] **Step 6: Manual verification (no router test precedent for authenticated endpoints in this codebase)**

Run: `cd ~/Programming/Dev/OfflineBudget && ./scripts/start.sh`, log in as `danford`, open the Forecast page for Main Checking in the browser, and confirm `GET /forecast/risk?account_id=3` (watch it in the Network tab) returns the new `transfer_triggered`/`transfer_date`/`transfer_amount`/`transfer_from` fields without erroring. Stop the server after confirming (`Ctrl+C`).

- [ ] **Step 7: Run the full backend test suite**

Run: `cd backend && python -m pytest -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
cd ~/Programming/Dev/OfflineBudget
git add backend/services/forecast_engine.py backend/routers/forecast.py backend/tests/test_forecast_risk.py
git commit -m "feat: surface buffer-transfer signal on /forecast/risk"
```

---

### Task 5: CLI command to configure the rule

**Files:**
- Modify: `cli/budget.py` (add `transfers_app` command group, following the `accounts_app` pattern at lines 77-105).

**Interfaces:**
- Consumes: `models.BufferTransferRule` (Task 1).
- Produces: `python cli/budget.py transfers add ...` / `python cli/budget.py transfers list ...`.

- [ ] **Step 1: Add the command group**

In `cli/budget.py`, insert this section immediately after the `recurring_app` section ends and before the `# ── Forecast ──` comment (after line 125):

```python
# ── Buffer Transfers ─────────────────────────────────────────────────────────

transfers_app = typer.Typer(help="Manage buffer transfer rules")
app.add_typer(transfers_app, name="transfers")

@transfers_app.command("add")
def add_transfer_rule(
    username: str = typer.Option(..., help="Username"),
    from_account: str = typer.Option(..., help="Source account name, e.g. Savings"),
    to_account: str = typer.Option(..., help="Destination account name, e.g. Main Checking"),
    action_threshold: float = typer.Option(..., help="Balance below this triggers a transfer"),
    target_floor: float = typer.Option(..., help="Transfer brings the balance up to at least this"),
    increment: float = typer.Option(1000.0, help="Transfer step size"),
    check_day: int = typer.Option(1, help="Day of month to evaluate, 1-28"),
):
    """Add a buffer transfer rule (e.g. top up Checking from Savings)."""
    db = get_db()
    user = _require_user(db, username)
    from_acc = db.query(models.Account).filter(
        models.Account.user_id == user.id, models.Account.name == from_account,
    ).first()
    to_acc = db.query(models.Account).filter(
        models.Account.user_id == user.id, models.Account.name == to_account,
    ).first()
    if not from_acc or not to_acc:
        console.print("[red]From/to account not found.[/red]")
        raise typer.Exit(1)
    if Decimal(str(target_floor)) <= Decimal(str(action_threshold)):
        console.print("[red]target_floor must be greater than action_threshold.[/red]")
        raise typer.Exit(1)
    rule = models.BufferTransferRule(
        user_id=user.id, from_account_id=from_acc.id, to_account_id=to_acc.id,
        action_threshold=Decimal(str(action_threshold)), target_floor=Decimal(str(target_floor)),
        increment=Decimal(str(increment)), check_day=check_day,
    )
    db.add(rule)
    db.commit()
    console.print(f"[green]✓ Added buffer transfer rule (id={rule.id}): {from_account} → {to_account}[/green]")


@transfers_app.command("list")
def list_transfer_rules(username: str = typer.Option(..., help="Username")):
    """List buffer transfer rules."""
    db = get_db()
    user = _require_user(db, username)
    rules = db.query(models.BufferTransferRule).filter(
        models.BufferTransferRule.user_id == user.id,
        models.BufferTransferRule.is_active == True,
    ).all()
    t = Table("ID", "From", "To", "Action <", "Floor", "Increment", "Check Day", box=box.ROUNDED)
    for r in rules:
        t.add_row(
            str(r.id), r.from_account.name, r.to_account.name,
            f"${r.action_threshold:,.2f}", f"${r.target_floor:,.2f}",
            f"${r.increment:,.2f}", str(r.check_day),
        )
    console.print(t)
```

- [ ] **Step 2: Manual verification**

Run:
```bash
cd ~/Programming/Dev/OfflineBudget && source .venv/bin/activate
python -c "from backend.database import upgrade_schema; upgrade_schema()"  # picks up any pending column changes, harmless if none
python cli/budget.py transfers add --username danford --from-account Savings --to-account "Main Checking" --action-threshold 100 --target-floor 200 --increment 1000 --check-day 1
python cli/budget.py transfers list --username danford
```
Expected: the `add` command prints a green confirmation with an id, and `list` shows one row: `Savings → Main Checking, $100.00, $200.00, $1,000.00, 1`.

- [ ] **Step 3: Commit**

```bash
cd ~/Programming/Dev/OfflineBudget
git add cli/budget.py
git commit -m "feat: add CLI commands to manage buffer transfer rules"
```

---

### Task 6: Two-tier low-balance banner on the Forecast page

**Files:**
- Modify: `frontend/src/components/RiskBanner.tsx`.

**Interfaces:**
- Consumes: the extended `/forecast/risk` response shape from Task 4 (`transfer_triggered`, `transfer_date`, `transfer_amount`, `transfer_from`), already flowing through `frontend/src/pages/Forecast.tsx:97-99`'s existing `risk` query with no changes needed there — `Forecast.tsx:423` already passes the whole `risk` object to `<RiskBanner risk={risk} />`.

- [ ] **Step 1: Update the component**

Replace the full contents of `frontend/src/components/RiskBanner.tsx` with:

```tsx
import { AlertTriangle, ArrowRightLeft } from "lucide-react";
import { fmt } from "../lib/utils";

interface Risk {
  at_risk: boolean;
  date: string | null;
  amount: string | null;
  threshold: string;
  transfer_triggered?: boolean;
  transfer_date?: string | null;
  transfer_amount?: string | null;
  transfer_from?: string | null;
}

function formatDate(iso: string): string {
  return new Date(iso + "T00:00:00").toLocaleDateString("en-US", {
    month: "long",
    day: "numeric",
  });
}

export function RiskBanner({ risk }: { risk: Risk | undefined }) {
  if (!risk) return null;

  const showAlert = risk.at_risk && risk.date && risk.amount != null;
  const showTransfer = risk.transfer_triggered && risk.transfer_date && risk.transfer_amount != null;

  if (!showAlert && !showTransfer) return null;

  return (
    <div className="flex flex-col gap-2">
      {showTransfer && (
        <div className="card border-orange-200 dark:border-orange-700 bg-orange-50/60 dark:bg-orange-900/20">
          <div className="flex items-start gap-3">
            <ArrowRightLeft size={18} className="text-orange-500 mt-0.5 shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="font-semibold text-orange-900 dark:text-orange-200 text-sm">
                {`Needs a ${fmt(parseFloat(risk.transfer_amount!))} transfer from ${risk.transfer_from} around ${formatDate(risk.transfer_date!)}`}
              </p>
              <p className="text-xs text-orange-700 dark:text-orange-400 mt-0.5">
                Modeled automatically to keep the account above its action threshold.
              </p>
            </div>
          </div>
        </div>
      )}
      {showAlert && (
        <div className="card border-red-200 dark:border-red-700 bg-red-50/60 dark:bg-red-900/20">
          <div className="flex items-start gap-3">
            <AlertTriangle size={18} className="text-red-500 mt-0.5 shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="font-semibold text-red-900 dark:text-red-200 text-sm">
                {parseFloat(risk.threshold) > 0
                  ? `Projected to drop below ${fmt(parseFloat(risk.threshold))} on ${formatDate(risk.date!)}`
                  : `Projected to go negative on ${formatDate(risk.date!)}`}
              </p>
              <p className="text-xs text-red-700 dark:text-red-400 mt-0.5">
                Projected balance: <strong>{fmt(parseFloat(risk.amount!))}</strong>
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Manual verification (no frontend test runner in this project)**

Run: `cd ~/Programming/Dev/OfflineBudget && ./scripts/start.sh`, open the Forecast page for Main Checking with the rule from Task 5 active and a big enough expense in range to trigger it (the seeded `Big Bill`-style scenario from the backend tests, or any real recurring item that dips it below $100). Confirm the orange transfer banner renders above the existing red alert banner (or alone, if only the transfer tier trips). Confirm the page renders with no console errors when `risk` has no transfer fields (e.g. an account with no `BufferTransferRule`) — the banner should either not render or render only the existing red alert, unchanged from today.

- [ ] **Step 3: Commit**

```bash
cd ~/Programming/Dev/OfflineBudget
git add frontend/src/components/RiskBanner.tsx
git commit -m "feat: show a distinct banner when a buffer transfer is modeled"
```

---

## Self-Review Notes

**Spec coverage:**
- "New model: BufferTransferRule" → Task 1.
- "Forecast engine change" (dry-run, monthly lookahead, mirrored outflow) → Tasks 2-3.
- "Two-tier low-balance alert" → Tasks 4 and 6.
- "Settings UI" → deliberately downgraded to CLI-only for v1 per Dan's "core fix first" scope decision; the spec's own open question ("whether BufferTransferRule needs a UI at all for v1") is resolved here as "not yet" — a Settings screen is a natural, separate follow-up once the CLI-configured rule has been used for a month.
- "Testing" section's four cases → all four are Task 2/3 tests (empty-schedule, rounded shortfall, no-rule regression guard, mirrored outflow) plus the added carry-forward-credit case Task 2 needed to get the algorithm right.

**Type/name consistency check:** `BufferTransferRule` fields (`action_threshold`, `target_floor`, `increment`, `check_day`, `from_account_id`, `to_account_id`) are spelled identically across Tasks 1, 2, 3, 5. `is_transfer` on `ForecastTransaction` matches from Task 1 through Task 4/6. `find_transfer_signal`'s return shape (`triggered`, `date`, `amount`, `from_name`) matches between Task 4's implementation and its router usage.
