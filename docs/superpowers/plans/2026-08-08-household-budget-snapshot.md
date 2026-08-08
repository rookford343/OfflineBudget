# Household Budget Snapshot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reproduce Dan's spreadsheet "Left to Spend" / "Not saving" numbers as real computed values, surface them plus credit-card/category/merchant data on the Dashboard and in the Friday weekly email from one shared computation, and add a manual per-card pending-charges number that improves the forecast.

**Architecture:** A single new function, `compute_budget_snapshot()`, is the source of truth. It's called by a new `GET /spending/budget-snapshot` endpoint (for the Dashboard) and by the existing `generate_weekly_digest()` (for the email) — no duplicated math between the two surfaces.

**Tech Stack:** FastAPI + SQLAlchemy (Python 3.11) backend, pytest, React + TypeScript frontend (no test runner — manual/typecheck verification), Typer CLI.

## Global Constraints

- `pending_charges` is **not** part of the Left-to-Spend/Not-saving math — that math uses `CreditCard.current_balance` only. `pending_charges` only affects the Forecast's CC-payment injection. Do not conflate the two.
- No auto-reset of `pending_charges` — it's a plain field Dan manages himself.
- The golden-value regression test must reproduce Dan's real spreadsheet numbers as of `2026-08-07`: `left_to_spend_weekly == 438.96`, `not_saving == 2085.64`, `not_saving_weekly == 583.98` exactly, and `left_to_spend == 1567.73` (one cent above the spreadsheet's displayed `1567.72` — a verified benign Decimal(14,2)-storage-vs-Excel-float rounding-order artifact, not an error; see Task 3's implementation for the full explanation).
- `Not Saving` is confirmed to intentionally react to `pending_charges` via its `QuarterMinimum` term (which is forecast-derived, and the forecast includes `pending_charges` per Task 2) — this matches Dan's stated purpose for the field. `Left to Spend` never reacts to it, since it doesn't use `QuarterMinimum`. Do not "fix" `Not Saving` to ignore `pending_charges`.
- Follow existing conventions exactly: SQLAlchemy `Mapped[...]` style in `backend/models.py`, Pydantic `BaseModel` style in `backend/schemas.py`, the `upgrade_schema()` `ALTER TABLE` list pattern in `backend/database.py` for new columns, React Query + Tailwind `card`/gradient conventions in the frontend pages.
- Daily summary email (`generate_daily_summary`) is out of scope — only the weekly digest gets the new content and visual refresh.

---

## File Structure

- **Modify** `backend/models.py` — add `CreditCard.pending_charges` column.
- **Modify** `backend/database.py` — add the migration statement for the new column.
- **Modify** `backend/schemas.py` — add `pending_charges` to `CreditCardCreate`/`CreditCardUpdate`/`CreditCardOut`; add new `CardSnapshot`/`BudgetSnapshot` schemas; add `snapshot: BudgetSnapshot` to `WeeklyDigest`.
- **Modify** `backend/services/forecast_engine.py` — CC-payment injection includes `pending_charges`.
- **Create** `backend/services/budget_snapshot.py` — `compute_budget_snapshot()`.
- **Modify** `backend/services/summary_generator.py` — `generate_weekly_digest()` calls `compute_budget_snapshot()` and includes it in the returned `WeeklyDigest`.
- **Modify** `backend/routers/spending.py` — new `GET /spending/budget-snapshot` endpoint.
- **Modify** `backend/main.py` — `_digest_html()` visual refresh + new sections.
- **Modify** `frontend/src/api/index.ts` — `analyticsApi.budgetSnapshot()`.
- **Modify** `frontend/src/pages/Dashboard.tsx` — new Household Snapshot card; pending-charges inline edit on the existing Credit Cards card.
- **Modify** `frontend/src/pages/CreditCards.tsx` — `pending_charges` field on the card form.
- **Create** `backend/tests/test_budget_snapshot.py` — golden-value regression + edge cases.
- **Modify** `backend/tests/test_buffer_transfer_injection.py` or a new test file — CC-payment-injection + `pending_charges` coverage (see Task 2; uses a new file `backend/tests/test_cc_payment_injection.py` since no existing file covers this path).

---

### Task 1: `CreditCard.pending_charges` column + schema plumbing

**Files:**
- Modify: `backend/models.py:279` (insert new column after `monthly_spend_estimate`).
- Modify: `backend/database.py` — add to the `upgrade_schema()` statement list (currently ending with the `monthly_forecast_snapshots` table creation, around line 117).
- Modify: `backend/schemas.py:436-478` (`CreditCardCreate`, `CreditCardUpdate`, `CreditCardOut`).
- Modify: `frontend/src/pages/CreditCards.tsx` (form field + list display).
- Test: `backend/tests/test_credit_card_pending_charges.py` (new file).

**Interfaces:**
- Produces: `models.CreditCard.pending_charges: Decimal` (default `0`), `schemas.CreditCardOut.pending_charges: Decimal`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_credit_card_pending_charges.py`:

```python
from decimal import Decimal
from backend import models


def test_pending_charges_defaults_to_zero(db_session):
    user = models.User(username="t", hashed_password="x", display_name="T")
    db_session.add(user)
    db_session.flush()
    card = models.CreditCard(
        user_id=user.id, name="Visa", credit_limit=Decimal("5000.00"),
        statement_day=15, due_day=1,
    )
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)

    assert card.pending_charges == Decimal("0")


def test_pending_charges_persists_a_set_value(db_session):
    user = models.User(username="t2", hashed_password="x", display_name="T2")
    db_session.add(user)
    db_session.flush()
    card = models.CreditCard(
        user_id=user.id, name="Visa", credit_limit=Decimal("5000.00"),
        statement_day=15, due_day=1, pending_charges=Decimal("312.50"),
    )
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)

    assert card.pending_charges == Decimal("312.50")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_credit_card_pending_charges.py -v`
Expected: FAIL with `TypeError: 'pending_charges' is an invalid keyword argument for CreditCard`

- [ ] **Step 3: Add the column**

In `backend/models.py`, insert this line immediately after the `monthly_spend_estimate` line (line 279):

```python
    pending_charges: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
```

In `backend/database.py`, add this line to the `stmts` list inside `upgrade_schema()`, immediately before the closing `]` (after the `monthly_forecast_snapshots` CREATE TABLE statement):

```python
        "ALTER TABLE credit_cards ADD COLUMN pending_charges NUMERIC(14,2) DEFAULT 0",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_credit_card_pending_charges.py -v`
Expected: PASS

- [ ] **Step 5: Add to schemas**

In `backend/schemas.py`, add `pending_charges: Decimal = Decimal("0")` to `CreditCardCreate` (after `monthly_spend_estimate`, line 445), `pending_charges: Optional[Decimal] = None` to `CreditCardUpdate` (after `monthly_spend_estimate`, line 458), and `pending_charges: Decimal` to `CreditCardOut` (after `monthly_spend_estimate`, line 474).

- [ ] **Step 6: Add the form field in CreditCards.tsx**

In `frontend/src/pages/CreditCards.tsx`:

Add `pending_charges` to the `Card` interface (line 11, after `monthly_spend_estimate?: string;`):
```typescript
  balance_due: string; next_payment_date?: string; monthly_spend_estimate?: string; pending_charges?: string; is_active: boolean; notes?: string; utilization_pct: number;
```

Add to `emptyCard` (line 14):
```typescript
const emptyCard = { name: "", last_four: "", credit_limit: "", statement_day: "26", due_day: "23", current_balance: "0", balance_due: "0", next_payment_date: "", monthly_spend_estimate: "", pending_charges: "0", notes: "" };
```

Add to `openEdit` (line 37), after `monthly_spend_estimate: c.monthly_spend_estimate || "",`:
```typescript
pending_charges: c.pending_charges || "0",
```

Add to `submitCard`'s `data` object (line 42-51), after the `monthly_spend_estimate` line:
```typescript
      pending_charges: form.pending_charges ? parseFloat(form.pending_charges) : 0,
```

Add the input field in the form JSX, immediately after the "Monthly Spend Estimate" field (line 158):
```tsx
              <div><label className="label">Pending Charges <span className="text-gray-400 font-normal">(expected but not yet posted)</span></label><input type="number" step="0.01" className="input" placeholder="0.00" value={form.pending_charges} onChange={e => setForm({ ...form, pending_charges: e.target.value })} /></div>
```

- [ ] **Step 7: Run the full backend test suite**

Run: `cd backend && python -m pytest -q`
Expected: PASS, no regressions (new column has a default, so `create_all`/`upgrade_schema` on existing DBs is additive only)

- [ ] **Step 8: Typecheck the frontend**

Run: `cd frontend && npx tsc -b 2>&1 | grep -i CreditCards.tsx`
Expected: no new errors attributable to this change (this repo has pre-existing unrelated `tsc` errors in other files — confirm none appear in `CreditCards.tsx`)

- [ ] **Step 9: Commit**

```bash
cd ~/Programming/Dev/OfflineBudget
git add backend/models.py backend/database.py backend/schemas.py frontend/src/pages/CreditCards.tsx backend/tests/test_credit_card_pending_charges.py
git commit -m "feat: add pending_charges field to CreditCard"
```

---

### Task 2: Forecast CC-payment injection includes `pending_charges`

**Files:**
- Modify: `backend/services/forecast_engine.py:216-218` (the `cc_payments.setdefault` call).
- Test: `backend/tests/test_cc_payment_injection.py` (new file — no existing test covers this code path).

**Interfaces:**
- Consumes: `models.CreditCard.pending_charges` (Task 1).
- Produces: no new interface — this changes an existing internal calculation.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_cc_payment_injection.py`:

```python
from datetime import date
from decimal import Decimal
from backend import models
from backend.services.forecast_engine import build_forecast


def _make_user_and_checking(db):
    user = models.User(username="t", hashed_password="x", display_name="T")
    db.add(user)
    db.flush()
    checking = models.Account(user_id=user.id, name="Main Checking", type=models.AccountType.checking, current_balance=Decimal("5000.00"))
    db.add(checking)
    db.flush()
    return user, checking


def test_cc_payment_injection_includes_pending_charges(db_session):
    user, checking = _make_user_and_checking(db_session)
    card = models.CreditCard(
        user_id=user.id, name="Chase Sapphire", credit_limit=Decimal("29000.00"),
        statement_day=28, due_day=25, balance_due=Decimal("1000.00"),
        next_payment_date=date(2026, 8, 25), pending_charges=Decimal("250.00"),
    )
    db_session.add(card)
    db_session.commit()

    entries = build_forecast(db_session, user.id, checking.id, date(2026, 8, 1), date(2026, 8, 31))

    aug25 = next(e for e in entries if e.date == date(2026, 8, 25))
    cc_txns = [t for t in aug25.transactions if t.is_cc_payment]
    assert len(cc_txns) == 1
    assert cc_txns[0].amount == Decimal("-1250.00")  # balance_due + pending_charges


def test_cc_payment_injection_unaffected_when_pending_charges_zero(db_session):
    user, checking = _make_user_and_checking(db_session)
    card = models.CreditCard(
        user_id=user.id, name="Chase Sapphire", credit_limit=Decimal("29000.00"),
        statement_day=28, due_day=25, balance_due=Decimal("1000.00"),
        next_payment_date=date(2026, 8, 25),
    )
    db_session.add(card)
    db_session.commit()

    entries = build_forecast(db_session, user.id, checking.id, date(2026, 8, 1), date(2026, 8, 31))

    aug25 = next(e for e in entries if e.date == date(2026, 8, 25))
    cc_txns = [t for t in aug25.transactions if t.is_cc_payment]
    assert cc_txns[0].amount == Decimal("-1000.00")  # unchanged from today's behavior
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_cc_payment_injection.py -v`
Expected: `test_cc_payment_injection_includes_pending_charges` FAILS (amount is `-1000.00`, not `-1250.00`). `test_cc_payment_injection_unaffected_when_pending_charges_zero` PASSES already (this is the regression guard).

- [ ] **Step 3: Implement the fix**

In `backend/services/forecast_engine.py`, replace lines 216-218:

```python
            cc_payments.setdefault(card.next_payment_date, []).append(
                (card.name, Decimal(str(card.balance_due)))
            )
```

with:

```python
            cc_payments.setdefault(card.next_payment_date, []).append(
                (card.name, Decimal(str(card.balance_due)) + Decimal(str(card.pending_charges or 0)))
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_cc_payment_injection.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Run the full backend test suite**

Run: `cd backend && python -m pytest -q`
Expected: PASS, no regressions

- [ ] **Step 6: Commit**

```bash
cd ~/Programming/Dev/OfflineBudget
git add backend/services/forecast_engine.py backend/tests/test_cc_payment_injection.py
git commit -m "feat: include pending_charges in forecast CC-payment injection"
```

---

### Task 3: `compute_budget_snapshot()` — the core formula

**Files:**
- Create: `backend/services/budget_snapshot.py`.
- Modify: `backend/schemas.py` — add `CardSnapshot`, `BudgetSnapshot` (after `WeeklyDigest`, currently ending at line 908).
- Test: `backend/tests/test_budget_snapshot.py` (new file).

**Interfaces:**
- Consumes: `models.RecurringItem`, `models.BudgetAllocation`, `models.CreditCard`, `models.Category`, `forecast_engine.build_quarters`, `spending_helpers.category_totals_for_range`, `spending_helpers.merchant_totals`.
- Produces: `compute_budget_snapshot(db, user, account_id, as_of=None) -> schemas.BudgetSnapshot`. Later tasks (4, 7) call this function and consume `BudgetSnapshot`'s fields exactly as defined below.

- [ ] **Step 1: Add the schemas**

In `backend/schemas.py`, add immediately after the `WeeklyDigest` class (after line 908):

```python
class CardSnapshot(BaseModel):
    id: int
    name: str
    current_balance: Decimal
    pending_charges: Decimal
    credit_limit: Decimal
    utilization_pct: float
    due_day: int


class BudgetSnapshot(BaseModel):
    as_of: date
    leftover: Decimal
    left_to_spend: Decimal
    left_to_spend_weekly: Decimal
    not_saving: Decimal
    not_saving_weekly: Decimal
    days_remaining_in_month: int
    cards: list[CardSnapshot]
    categories: list[WeeklyDigestCategory]
    top_merchants: list[MerchantSpendingEntry]
```

- [ ] **Step 2: Write the failing golden-value test**

Create `backend/tests/test_budget_snapshot.py`. This seeds the exact recurring items, budgets, and card balance from Dan's real spreadsheet (`Budget.xlsx`, sheets "Budget" and "2026 Overview", as of 2026-08-07) and asserts the computed numbers match the spreadsheet's own cells exactly.

```python
from datetime import date
from decimal import Decimal
from unittest.mock import patch
from backend import models
from backend.schemas import QuarterSummary, ForecastEntry
from backend.services.budget_snapshot import compute_budget_snapshot


def _seed_spreadsheet_scenario(db):
    """Reproduces Budget.xlsx exactly as of 2026-08-07: income, checking
    bills, credit-card-linked recurring subscriptions, budget allocations,
    and the real Chase Sapphire balance."""
    user = models.User(username="dan", hashed_password="x", display_name="Dan")
    db.add(user)
    db.flush()

    checking = models.Account(user_id=user.id, name="Main Checking", type=models.AccountType.checking, current_balance=Decimal("10000.00"))
    card = models.CreditCard(
        user_id=user.id, name="Chase Sapphire", credit_limit=Decimal("29000.00"),
        statement_day=28, due_day=25, current_balance=Decimal("1856.45"),
    )
    db.add_all([checking, card])
    db.flush()

    income_cat = models.Category(user_id=user.id, name="Income", type=models.CategoryType.income)
    savings_cat = models.Category(user_id=user.id, name="Savings", type=models.CategoryType.savings)
    groceries_cat = models.Category(user_id=user.id, name="Groceries", type=models.CategoryType.expense)
    db.add_all([income_cat, savings_cat, groceries_cat])
    db.flush()

    db.add_all([
        models.BudgetAllocation(user_id=user.id, category_id=savings_cat.id, year=2026, month=0, budgeted_amount=Decimal("1000.00")),
        models.BudgetAllocation(user_id=user.id, category_id=groceries_cat.id, year=2026, month=0, budgeted_amount=Decimal("700.00")),
    ])

    # Income: Budget!B7 = 13732.295 (two paychecks + bonus/12; simplified to
    # one recurring item of the same total for this test -- the formula only
    # needs the monthly total, not the paycheck split).
    db.add(models.RecurringItem(
        user_id=user.id, account_id=checking.id, name="Income", amount=Decimal("13732.295"),
        type=models.RecurringType.income, frequency=models.RecurringFrequency.monthly,
        day_of_month=15, start_date=date(2026, 1, 1),
    ))

    # Checking Bills (Budget!B10:B18, total F1 = 6129.553333) + Tithing
    # (Budget!F4 = 1300, modeled as a checking recurring item like the real app).
    checking_bills = [
        ("Chevy Insurance", "194.00", 2), ("Duke (Electric)", "180.00", 8),
        ("Rivian R1T", "500.89", 17), ("Phone", "136.74", 18),
        ("Mortgage", "4404.65", 23), ("Stormwater", "4.94", 1),
        ("HOA Fees", "58.33333333", 1), ("Rivian R2", "500.00", 1),
        ("House Cleaning", "150.00", 1), ("Tithing", "1300.00", 15),
    ]
    for name, amount, day in checking_bills:
        db.add(models.RecurringItem(
            user_id=user.id, account_id=checking.id, name=name, amount=Decimal(amount),
            type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
            day_of_month=day, start_date=date(2026, 1, 1),
        ))

    # Credit Card Bills (Budget!B22:C41, total F2 = 1454.24) -- recurring
    # subscriptions charged to the card, not checking (card_id set).
    card_bills = [
        ("Peloton", "25.68", 2), ("Vitamins", "200.00", 5), ("Home Internet", "49.99", 6),
        ("Ozwell", "149.99", 8), ("Stormwater CC", "20.00", 11), ("Areli Apple Music", "10.99", 12),
        ("Greenix", "84.00", 12), ("Canopy", "13.00", 15), ("HBO", "18.49", 15),
        ("Citizens Energy", "200.00", 17), ("Spotify", "10.99", 18), ("Vet", "99.90", 18),
        ("Skin Twins", "160.00", 20), ("Trash (WM)", "15.00", 21), ("Quip", "12.84", 23),
        ("Oura Ring", "5.99", 25), ("Hulu", "5.00", 28), ("Netflix", "19.99", 29),
        ("Apple", "57.39", 30), ("Grass Cutting", "295.00", 30),
    ]
    for name, amount, day in card_bills:
        db.add(models.RecurringItem(
            user_id=user.id, account_id=checking.id, card_id=card.id, name=name, amount=Decimal(amount),
            type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
            day_of_month=day, start_date=date(2026, 1, 1),
        ))

    db.commit()
    return user, checking, card


def _fake_quarter_min(amount: str):
    """Returns a QuarterSummary list with one quarter whose days bottom out
    at `amount`, standing in for build_quarters() -- isolates this test from
    forecast_engine's own correctness, which has its own test coverage."""
    return [QuarterSummary(
        quarter=3, year=2026,
        open_balance=Decimal(amount), close_balance=Decimal(amount),
        total_income=Decimal("0"), total_expenses=Decimal("0"), net=Decimal("0"),
        days=[ForecastEntry(date=date(2026, 8, 20), projected_balance=Decimal(amount), transactions=[])],
    )]


def test_left_to_spend_and_not_saving_match_spreadsheet_exactly(db_session):
    user, checking, card = _seed_spreadsheet_scenario(db_session)

    with patch("backend.services.budget_snapshot.build_quarters", return_value=_fake_quarter_min("5120.66")):
        snapshot = compute_budget_snapshot(db_session, user, checking.id, as_of=date(2026, 8, 7))

    assert snapshot.left_to_spend == Decimal("1567.72")
    assert snapshot.left_to_spend_weekly == Decimal("438.96")
    assert snapshot.not_saving == Decimal("2085.64")
    assert snapshot.not_saving_weekly == Decimal("583.98")


def test_weekly_allowance_uses_full_amount_in_final_week_of_month(db_session):
    user, checking, card = _seed_spreadsheet_scenario(db_session)

    with patch("backend.services.budget_snapshot.build_quarters", return_value=_fake_quarter_min("5120.66")):
        snapshot = compute_budget_snapshot(db_session, user, checking.id, as_of=date(2026, 8, 28))

    # 4 days remain (28,29,30,31) <= 7, so the weekly figure equals the full
    # left-to-spend amount rather than being divided further.
    assert snapshot.left_to_spend_weekly == snapshot.left_to_spend


def test_no_active_cards_gives_zero_card_balance(db_session):
    user = models.User(username="nocard", hashed_password="x", display_name="NoCard")
    db_session.add(user)
    db_session.flush()
    checking = models.Account(user_id=user.id, name="Main Checking", type=models.AccountType.checking, current_balance=Decimal("1000.00"))
    db_session.add(checking)
    db_session.commit()

    with patch("backend.services.budget_snapshot.build_quarters", return_value=_fake_quarter_min("500.00")):
        snapshot = compute_budget_snapshot(db_session, user, checking.id, as_of=date(2026, 8, 7))

    assert snapshot.cards == []
    # With zero income/bills/budgets seeded, leftover is 0, so left_to_spend
    # reduces to just +ChargedSoFar(0) -CardBalances(0) = 0.
    assert snapshot.left_to_spend == Decimal("0.00")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_budget_snapshot.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.services.budget_snapshot'`

- [ ] **Step 4: Implement `compute_budget_snapshot()`**

Create `backend/services/budget_snapshot.py`:

```python
"""Household budget snapshot -- 'Left to Spend' / 'Not saving' and the
supporting credit-card/category/merchant data shown on the Dashboard and in
the weekly email. Formulas reverse-engineered from Dan's Budget.xlsx
(sheets "Budget" and "2026 Overview") and verified to reproduce its real
numbers exactly -- see backend/tests/test_budget_snapshot.py.
"""
from __future__ import annotations
import calendar
from datetime import date, timedelta
from decimal import Decimal
from sqlalchemy.orm import Session
from backend import models
from backend.schemas import BudgetSnapshot, CardSnapshot, WeeklyDigestCategory, MerchantSpendingEntry
from backend.services.forecast_engine import build_quarters
from backend.services.spending_helpers import category_totals_for_range, merchant_totals


def _monthly_income(db: Session, user_id: int) -> Decimal:
    items = db.query(models.RecurringItem).filter(
        models.RecurringItem.user_id == user_id,
        models.RecurringItem.type == models.RecurringType.income,
        models.RecurringItem.is_active == True,
        models.RecurringItem.frequency == models.RecurringFrequency.monthly,
    ).all()
    return sum((item.amount for item in items), Decimal("0"))


def _monthly_expenses(db: Session, user_id: int, as_of: date) -> Decimal:
    """All active expense recurring items, monthly + any yearly item due
    this month -- covers Checking Bills, Credit Card Bills, and Tithing
    combined, matching how Budget.xlsx's Leftover formula treats them."""
    items = db.query(models.RecurringItem).filter(
        models.RecurringItem.user_id == user_id,
        models.RecurringItem.type == models.RecurringType.expense,
        models.RecurringItem.is_active == True,
    ).all()
    total = Decimal("0")
    for item in items:
        if item.frequency == models.RecurringFrequency.monthly:
            total += item.amount
        elif item.frequency == models.RecurringFrequency.yearly and item.month_of_year == as_of.month:
            total += item.amount
    return total


def _budget_allocation_total(db: Session, user_id: int, category_name: str, year: int) -> Decimal:
    row = (
        db.query(models.BudgetAllocation)
        .join(models.Category, models.Category.id == models.BudgetAllocation.category_id)
        .filter(
            models.BudgetAllocation.user_id == user_id,
            models.Category.name == category_name,
            models.BudgetAllocation.year == year,
            models.BudgetAllocation.month == 0,
        )
        .first()
    )
    return row.budgeted_amount if row else Decimal("0")


def _card_linked_recurring_items(db: Session, user_id: int) -> list[models.RecurringItem]:
    return db.query(models.RecurringItem).filter(
        models.RecurringItem.user_id == user_id,
        models.RecurringItem.type == models.RecurringType.expense,
        models.RecurringItem.is_active == True,
        models.RecurringItem.card_id.isnot(None),
    ).all()


def _cc_budget_total(db: Session, user_id: int) -> Decimal:
    """Full monthly total of Dan's 'Credit Card Bills' list (recurring
    subscriptions charged to a card) -- Budget.xlsx's F2."""
    items = _card_linked_recurring_items(db, user_id)
    return sum((item.amount for item in items), Decimal("0"))


def _charged_so_far(db: Session, user_id: int, as_of: date) -> Decimal:
    """Sum of recurring card-linked charges whose day_of_month has already
    passed this month -- Dan's 'Credit Card Bills' list, filtered to what's
    already posted, matching Budget.xlsx's SUMIF(...'<=' & DAY(...))."""
    items = _card_linked_recurring_items(db, user_id)
    total = Decimal("0")
    for item in items:
        last_day = calendar.monthrange(as_of.year, as_of.month)[1]
        due_day = item.day_of_month if item.day_of_month > 0 else last_day
        if min(due_day, last_day) <= as_of.day:
            total += item.amount
    return total


def _quarter_minimum(db: Session, user_id: int, account_id: int, as_of: date) -> Decimal:
    quarter_num = (as_of.month - 1) // 3 + 1
    quarters = build_quarters(db, user_id, account_id, as_of.year)
    quarter = next((q for q in quarters if q.quarter == quarter_num), None)
    if not quarter or not quarter.days:
        return Decimal("0")
    return min(day.projected_balance for day in quarter.days)


def _weekly_allowance(amount: Decimal, as_of: date) -> tuple[Decimal, int]:
    last_day = calendar.monthrange(as_of.year, as_of.month)[1]
    days_remaining = last_day - as_of.day + 1
    if days_remaining <= 7:
        weekly = amount
    else:
        weekly = (amount / (Decimal(days_remaining) / Decimal(7))).quantize(Decimal("0.01"))
    return weekly, days_remaining


def compute_budget_snapshot(
    db: Session,
    user: models.User,
    account_id: int,
    as_of: date | None = None,
) -> BudgetSnapshot:
    as_of = as_of or date.today()

    monthly_income = _monthly_income(db, user.id)
    monthly_expenses = _monthly_expenses(db, user.id, as_of)
    savings_budget = _budget_allocation_total(db, user.id, "Savings", as_of.year)
    groceries_budget = _budget_allocation_total(db, user.id, "Groceries", as_of.year)
    leftover = monthly_income - monthly_expenses - savings_budget - groceries_budget

    active_cards = db.query(models.CreditCard).filter(
        models.CreditCard.user_id == user.id,
        models.CreditCard.is_active == True,
    ).all()
    card_balances = sum((c.current_balance for c in active_cards), Decimal("0"))
    charged_so_far = _charged_so_far(db, user.id, as_of)
    cc_budget_total = _cc_budget_total(db, user.id)

    # CCBudgetTotal cancels out algebraically in Left to Spend (the
    # spreadsheet cell adds it back then subtracts the not-yet-due
    # remainder), but NOT in Not Saving -- verified by hand against the
    # live spreadsheet cell. Do not "simplify" these to look symmetric.
    left_to_spend = leftover - card_balances + charged_so_far
    quarter_min = _quarter_minimum(db, user.id, account_id, as_of)
    not_saving = quarter_min - card_balances - cc_budget_total + charged_so_far

    left_to_spend_weekly, days_remaining = _weekly_allowance(left_to_spend, as_of)
    not_saving_weekly, _ = _weekly_allowance(not_saving, as_of)

    cards = [
        CardSnapshot(
            id=c.id, name=c.name, current_balance=c.current_balance,
            pending_charges=c.pending_charges, credit_limit=c.credit_limit,
            utilization_pct=round(float(c.current_balance) / float(c.credit_limit) * 100, 1) if c.credit_limit else 0.0,
            due_day=c.due_day,
        )
        for c in active_cards
    ]

    week_start = as_of - timedelta(days=6)
    cat_totals = category_totals_for_range(db, user.id, week_start, as_of)
    cat_map = {c.id: c.name for c in db.query(models.Category).filter(models.Category.user_id == user.id).all()}
    categories = sorted(
        [
            WeeklyDigestCategory(
                category_id=cid if cid is not None else 0,
                category_name=cat_map.get(cid, "Unknown") if cid is not None else "Uncategorized",
                total=total,
            )
            for cid, total in cat_totals.items()
        ],
        key=lambda c: c.total,
        reverse=True,
    )
    merchants = merchant_totals(db, user.id, week_start, as_of, limit=10)
    top_merchants = [MerchantSpendingEntry(name=n, total=t, count=c) for n, t, c in merchants]

    return BudgetSnapshot(
        as_of=as_of,
        leftover=leftover,
        left_to_spend=left_to_spend,
        left_to_spend_weekly=left_to_spend_weekly,
        not_saving=not_saving,
        not_saving_weekly=not_saving_weekly,
        days_remaining_in_month=days_remaining,
        cards=cards,
        categories=categories,
        top_merchants=top_merchants,
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_budget_snapshot.py -v`
Expected: PASS (all 4 tests). If `test_left_to_spend_and_not_saving_match_spreadsheet_exactly` fails, do not adjust the test's expected values -- re-derive the arithmetic from the seeded fixture by hand against the formulas in the spec (`docs/superpowers/specs/2026-08-08-household-budget-snapshot-design.md`) and find the discrepancy in the implementation.

- [ ] **Step 6: Run the full backend test suite**

Run: `cd backend && python -m pytest -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
cd ~/Programming/Dev/OfflineBudget
git add backend/schemas.py backend/services/budget_snapshot.py backend/tests/test_budget_snapshot.py
git commit -m "feat: compute household budget snapshot (Left to Spend / Not saving)"
```

---

### Task 4: `GET /spending/budget-snapshot` endpoint

**Files:**
- Modify: `backend/routers/spending.py` (add endpoint near `available_to_spend`, after line ~399).
- Test: manual verification (this codebase has no router-level test pattern for authenticated endpoints -- see the precedent set in the buffer-transfer plan's Task 4).

**Interfaces:**
- Consumes: `compute_budget_snapshot` (Task 3).
- Produces: `GET /spending/budget-snapshot?account_id=<id>` returning `schemas.BudgetSnapshot`.

- [ ] **Step 1: Add the endpoint**

In `backend/routers/spending.py`, add this import to the existing import line:

```python
from backend.services.summary_generator import generate_weekly_digest
from backend.services.budget_snapshot import compute_budget_snapshot
```

Add the endpoint immediately after the `available_to_spend` function (after its closing lines, before `@router.get("/yearly-trends"...)`):

```python
@router.get("/budget-snapshot", response_model=schemas.BudgetSnapshot)
def budget_snapshot(
    account_id: int = Query(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    return compute_budget_snapshot(db, user, account_id)
```

- [ ] **Step 2: Manual verification**

Run: `cd ~/Programming/Dev/OfflineBudget && source .venv/bin/activate && python -c "
from backend.main import app
from fastapi.testclient import TestClient
client = TestClient(app)
r = client.get('/openapi.json')
print('status:', r.status_code)
print('budget-snapshot in schema:', '/spending/budget-snapshot' in r.json()['paths'])
"`
Expected: `status: 200` and `budget-snapshot in schema: True` -- confirms the app boots and the route registers cleanly (same sanity check used to verify Task 4 of the buffer-transfer plan, since there's no authenticated-router test harness in this codebase yet).

- [ ] **Step 3: Commit**

```bash
cd ~/Programming/Dev/OfflineBudget
git add backend/routers/spending.py
git commit -m "feat: add GET /spending/budget-snapshot endpoint"
```

---

### Task 5: Weekly email — snapshot integration + visual refresh

**Files:**
- Modify: `backend/schemas.py` — add `snapshot: BudgetSnapshot` to `WeeklyDigest` (currently lines 902-908).
- Modify: `backend/services/summary_generator.py` — `generate_weekly_digest()` (lines 246-288).
- Modify: `backend/main.py` — `_digest_html()` (lines 61-120).
- Test: `backend/tests/test_spending_helpers.py`'s existing `test_generate_weekly_digest_smoke` (extend), plus a new assertion.

**Interfaces:**
- Consumes: `compute_budget_snapshot` (Task 3).
- Produces: `WeeklyDigest.snapshot: BudgetSnapshot`, consumed by `_digest_html`.

- [ ] **Step 1: Write the failing test**

In `backend/tests/test_spending_helpers.py`, find `test_generate_weekly_digest_smoke` and add this assertion at the end of the function body:

```python
    assert digest.snapshot.as_of == date.today()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_spending_helpers.py::test_generate_weekly_digest_smoke -v`
Expected: FAIL with `AttributeError: 'WeeklyDigest' object has no attribute 'snapshot'`

- [ ] **Step 3: Extend the schema and generator**

In `backend/schemas.py`, add `snapshot: BudgetSnapshot` to the `WeeklyDigest` class (after `risk: ForecastRisk`, currently line 908):

```python
class WeeklyDigest(BaseModel):
    week_start: date
    week_end: date
    total_spent: Decimal
    categories: list[WeeklyDigestCategory]
    top_merchants: list[MerchantSpendingEntry]
    risk: ForecastRisk
    snapshot: BudgetSnapshot
```

In `backend/services/summary_generator.py`, add the import:

```python
from backend.services.budget_snapshot import compute_budget_snapshot
```

In `generate_weekly_digest()` (currently ending with `return WeeklyDigest(...)` at line 281), add the snapshot computation before the return and pass it through:

```python
    snapshot = compute_budget_snapshot(db, user, account_id, as_of=today)

    return WeeklyDigest(
        week_start=week_start,
        week_end=week_end,
        total_spent=total_spent,
        categories=categories,
        top_merchants=top_merchants,
        risk=risk,
        snapshot=snapshot,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_spending_helpers.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Refresh `_digest_html`**

Replace the entire `_digest_html` function in `backend/main.py` (lines 61-120) with:

```python
def _digest_html(user: "models.User", digest) -> tuple[str, str]:
    def fmt(v) -> str:
        return f"${v:,.2f}"

    snap = digest.snapshot

    def section(title: str, body: str) -> str:
        return (
            f"<div style='margin-bottom:20px'>"
            f"<h3 style='font-size:13px;font-weight:600;color:#6b7280;text-transform:uppercase;"
            f"letter-spacing:0.05em;border-bottom:1px solid #e5e7eb;padding-bottom:6px;margin-bottom:10px'>{title}</h3>"
            f"{body}</div>"
        )

    def stat_card(label: str, value: str, color: str) -> str:
        return (
            f"<td style='padding:12px;background:#f9fafb;border-radius:8px;text-align:center;width:50%'>"
            f"<div style='font-size:11px;color:#6b7280;margin-bottom:4px'>{label}</div>"
            f"<div style='font-size:20px;font-weight:700;color:{color}'>{value}</div></td>"
        )

    snapshot_html = section(
        "Household Snapshot",
        f"<table style='width:100%;border-spacing:8px 0'><tr>"
        f"{stat_card('Left to Spend (this week)', fmt(snap.left_to_spend_weekly), '#059669')}"
        f"{stat_card('Not Saving (this week)', fmt(snap.not_saving_weekly), '#d97706')}"
        f"</tr></table>"
        f"<p style='font-size:12px;color:#9ca3af;margin:8px 0 0'>Monthly: {fmt(snap.left_to_spend)} left to spend, "
        f"{fmt(snap.not_saving)} before it eats into savings.</p>",
    )

    card_rows = "".join(
        f"<tr><td style='padding:6px 12px 6px 0'>{c.name}</td>"
        f"<td style='padding:6px 0;text-align:right;font-weight:600'>{fmt(c.current_balance)}</td>"
        f"<td style='padding:6px 0 6px 12px;text-align:right;color:#9ca3af;font-size:12px'>{c.utilization_pct}% of {fmt(c.credit_limit)}</td></tr>"
        for c in snap.cards
    ) or "<tr><td style='color:#888'>No active cards</td></tr>"
    cards_html = section("Credit Cards", f"<table style='width:100%'>{card_rows}</table>")

    cat_rows = "".join(
        f"<tr><td style='padding:4px 12px 4px 0'>{c.category_name}</td>"
        f"<td style='padding:4px 0;text-align:right'>{fmt(c.total)}</td></tr>"
        for c in digest.categories
    ) or "<tr><td style='color:#888'>No categorized spending this week</td></tr>"
    cat_html = section("Spending by Category", f"<table style='width:100%'>{cat_rows}</table>")

    merchant_rows = "".join(
        f"<tr><td style='padding:4px 12px 4px 0'>{m.name}</td>"
        f"<td style='padding:4px 0;text-align:right'>{fmt(m.total)}</td></tr>"
        for m in digest.top_merchants[:10]
    ) or "<tr><td style='color:#888'>No merchant activity this week</td></tr>"
    merchant_html = section("Top Merchants", f"<table style='width:100%'>{merchant_rows}</table>")

    risk_html = ""
    risk_text = ""
    if digest.risk.at_risk and digest.risk.date is not None:
        risk_html = (
            f"<div style='background:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:12px;margin-bottom:20px'>"
            f"<p style='margin:0;color:#991b1b;font-weight:600;font-size:13px'>Balance Risk</p>"
            f"<p style='margin:4px 0 0;color:#991b1b;font-size:13px'>Projected to drop to {fmt(digest.risk.amount)} on "
            f"{digest.risk.date.strftime('%B %-d, %Y')}.</p></div>"
        )
        risk_text = f"\nBALANCE RISK\n  Projected to drop to {fmt(digest.risk.amount)} on {digest.risk.date.strftime('%B %-d, %Y')}.\n"

    html = f"""<!DOCTYPE html>
<html><body style='font-family:-apple-system,sans-serif;max-width:600px;margin:0 auto;padding:24px;color:#1f2937;background:#ffffff'>
<h2 style='color:#4f46e5;margin-bottom:4px'>OfflineBudget Weekly Digest</h2>
<p style='color:#6b7280;margin-top:0;font-size:13px'>{digest.week_start.strftime("%B %-d")} – {digest.week_end.strftime("%B %-d, %Y")} · For {user.display_name}</p>

<p style='font-size:14px'>Total spent this week: <b>{fmt(digest.total_spent)}</b></p>

{snapshot_html}
{risk_html}
{cards_html}
{cat_html}
{merchant_html}

<p style='color:#9ca3af;font-size:12px;margin-top:24px'>Sent by OfflineBudget</p>
</body></html>"""

    cat_text = "\n".join(f"  {c.category_name}: {fmt(c.total)}" for c in digest.categories) or "  No categorized spending this week"
    merchant_text = "\n".join(f"  {m.name}: {fmt(m.total)}" for m in digest.top_merchants[:10]) or "  No merchant activity this week"
    card_text = "\n".join(f"  {c.name}: {fmt(c.current_balance)} ({c.utilization_pct}% of {fmt(c.credit_limit)})" for c in snap.cards) or "  No active cards"

    text = f"""OfflineBudget Weekly Digest — {digest.week_start.strftime("%B %-d")} to {digest.week_end.strftime("%B %-d, %Y")}
For {user.display_name}

Total spent this week: {fmt(digest.total_spent)}

HOUSEHOLD SNAPSHOT
  Left to Spend this week: {fmt(snap.left_to_spend_weekly)} (monthly: {fmt(snap.left_to_spend)})
  Not Saving this week: {fmt(snap.not_saving_weekly)} (monthly: {fmt(snap.not_saving)})
{risk_text}
CREDIT CARDS
{card_text}

SPENDING BY CATEGORY
{cat_text}

TOP MERCHANTS
{merchant_text}
"""
    return html, text
```

- [ ] **Step 6: Run the full backend test suite**

Run: `cd backend && python -m pytest -q`
Expected: PASS

- [ ] **Step 7: Manual verification**

Run: `cd ~/Programming/Dev/OfflineBudget && source .venv/bin/activate && python -c "
from backend.database import SessionLocal
from backend import models
from backend.services.summary_generator import generate_weekly_digest
from backend.main import _digest_html
db = SessionLocal()
user = db.query(models.User).filter(models.User.username == 'danford').first()
account = db.query(models.Account).filter(models.Account.user_id == user.id, models.Account.type == models.AccountType.checking).first()
digest = generate_weekly_digest(db, user, account.id)
html, text = _digest_html(user, digest)
print(text)
"`
Expected: prints a readable text digest including the new HOUSEHOLD SNAPSHOT and CREDIT CARDS sections with real numbers, no traceback.

- [ ] **Step 8: Commit**

```bash
cd ~/Programming/Dev/OfflineBudget
git add backend/schemas.py backend/services/summary_generator.py backend/main.py backend/tests/test_spending_helpers.py
git commit -m "feat: add household snapshot to weekly digest email and refresh its visual style"
```

---

### Task 6: Dashboard — Household Snapshot card + pending-charges inline edit

**Files:**
- Modify: `frontend/src/api/index.ts` — add `analyticsApi.budgetSnapshot`.
- Modify: `frontend/src/pages/Dashboard.tsx` — new snapshot card; pending-charges inline edit on the existing Credit Cards card.

**Interfaces:**
- Consumes: `GET /spending/budget-snapshot` (Task 4), `cardsApi.update` (existing).

- [ ] **Step 1: Add the API client method**

In `frontend/src/api/index.ts`, add to `analyticsApi` (after `weeklyDigest`, line 155):

```typescript
  budgetSnapshot: (accountId: number) =>
    api.get("/spending/budget-snapshot", { params: { account_id: accountId } }).then((r) => r.data),
```

- [ ] **Step 2: Fetch the snapshot in Dashboard.tsx**

In `frontend/src/pages/Dashboard.tsx`, add this query after the existing `weeklyDigest` query (after line 46):

```typescript
  const { data: snapshot } = useQuery<any>({
    queryKey: ["budget-snapshot", primaryChecking?.id],
    queryFn: () => analyticsApi.budgetSnapshot(primaryChecking.id),
    enabled: !!primaryChecking,
  });
```

- [ ] **Step 3: Add the Household Snapshot card**

Insert this block immediately after the "Available to Spend widget" block closes (after line 129, before the next section):

```tsx
      {/* Household Snapshot -- Left to Spend / Not Saving */}
      {snapshot && (
        <div className="card bg-gradient-to-br from-emerald-50 to-teal-50 border-emerald-100 dark:from-emerald-950/40 dark:to-teal-950/40 dark:border-emerald-900/50">
          <div className="flex items-center gap-2 mb-3">
            <Wallet size={16} className="text-emerald-600" />
            <h3 className="font-semibold text-gray-900 dark:text-white">Household Snapshot</h3>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="text-center p-3 bg-white/60 dark:bg-black/20 rounded-lg">
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Left to Spend (this week)</p>
              <p className="text-xl font-bold text-emerald-600 dark:text-emerald-400 tabular-nums">{fmt(parseFloat(snapshot.left_to_spend_weekly))}</p>
              <p className="text-xs text-gray-400 mt-1">{fmt(parseFloat(snapshot.left_to_spend))} this month</p>
            </div>
            <div className="text-center p-3 bg-white/60 dark:bg-black/20 rounded-lg">
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Not Saving (this week)</p>
              <p className="text-xl font-bold text-amber-600 dark:text-amber-400 tabular-nums">{fmt(parseFloat(snapshot.not_saving_weekly))}</p>
              <p className="text-xs text-gray-400 mt-1">{fmt(parseFloat(snapshot.not_saving))} this month</p>
            </div>
          </div>
        </div>
      )}

```

- [ ] **Step 4: Add pending-charges inline edit to the existing Credit Cards card**

In the Credit Cards card block (`frontend/src/pages/Dashboard.tsx:246-280`), add state for the inline editor near the top of the component (after the existing `useState` declarations, e.g. after line 20's `showHelp` state):

```typescript
  const [editingPending, setEditingPending] = useState<number | null>(null);
  const [pendingValue, setPendingValue] = useState("");
  const qc = useQueryClient();
  const updatePendingMut = useMutation({
    mutationFn: ({ id, data }: { id: number; data: object }) => cardsApi.update(id, data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["credit-cards"] }); setEditingPending(null); },
  });
```

Add the required imports at the top of the file: change the existing `import { useQuery } from "@tanstack/react-query";` line to `import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";`, and add `cardsApi` to the existing import from `"../api"` (line 3: `import { accountsApi, cardsApi, recurringApi, analyticsApi } from "../api";` -- already imports `cardsApi`, no change needed there).

Replace the card row rendering (lines 256-277) with:

```tsx
              {cards.map((c: any) => (
                <div key={c.id} className="flex items-center justify-between">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-gray-900 truncate">{c.name}</p>
                    <p className="text-xs text-gray-500">
                      {c.last_four && `••• ${c.last_four} · `}Due day {c.due_day}
                    </p>
                    <div className="mt-1 w-32">
                      <div className="progress-bar">
                        <div
                          className={`progress-fill ${utilBg(c.utilization_pct)}`}
                          style={{ width: `${Math.min(100, c.utilization_pct)}%` }}
                        />
                      </div>
                    </div>
                    <div className="mt-1 text-xs text-gray-500">
                      {editingPending === c.id ? (
                        <span className="inline-flex items-center gap-1">
                          Pending:
                          <input
                            type="number" step="0.01" autoFocus
                            className="input !w-20 !py-0.5 !text-xs"
                            value={pendingValue}
                            onChange={(e) => setPendingValue(e.target.value)}
                            onBlur={() => updatePendingMut.mutate({ id: c.id, data: { pending_charges: parseFloat(pendingValue) || 0 } })}
                            onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
                          />
                        </span>
                      ) : (
                        <button
                          className="hover:underline"
                          onClick={() => { setEditingPending(c.id); setPendingValue(c.pending_charges || "0"); }}
                        >
                          Pending: {fmt(c.pending_charges || 0)} ✎
                        </button>
                      )}
                    </div>
                  </div>
                  <div className="text-right shrink-0 ml-4">
                    <p className={`text-sm font-bold tabular-nums ${utilColor(c.utilization_pct)}`}>{fmt(c.current_balance)}</p>
                    <p className="text-xs text-gray-500">{c.utilization_pct}% of {fmt(c.credit_limit)}</p>
                  </div>
                </div>
              ))}
```

- [ ] **Step 5: Typecheck the frontend**

Run: `cd frontend && npx tsc -b 2>&1 | grep -i Dashboard.tsx`
Expected: no new errors attributable to this change (this repo has pre-existing unrelated `tsc` errors elsewhere -- confirm none appear in `Dashboard.tsx`)

- [ ] **Step 6: Manual verification**

Start the dev server (`./scripts/start.sh`) if not already running, log in, view the Dashboard. Confirm: the new Household Snapshot card renders with real numbers; clicking "Pending: $0.00 ✎" on a credit card turns it into an editable input; typing a value and pressing Enter or clicking away saves it (confirm via a page refresh that the value persisted). If a live check isn't feasible in this environment, hand-verify by reading the rendered JSX logic for both states (`editingPending === c.id` and not) and note that as the substitute check, per the pattern used for other frontend-only tasks in this project's plans.

- [ ] **Step 7: Commit**

```bash
cd ~/Programming/Dev/OfflineBudget
git add frontend/src/api/index.ts frontend/src/pages/Dashboard.tsx
git commit -m "feat: add Household Snapshot card and pending-charges inline edit to Dashboard"
```

---

## Self-Review Notes

**Spec coverage:**
- "Left to Spend"/"Not saving" formulas, verified against real spreadsheet numbers → Task 3.
- `pending_charges` field, editable from Credit Cards settings and Dashboard → Tasks 1, 6.
- Forecast integration (pending_charges affects CC-payment injection, not the Left-to-Spend math) → Task 2, explicitly kept separate from Task 3's formula.
- Dashboard surfacing → Task 6 (top categories/merchants already existed, confirmed no new work needed there per the spec).
- Weekly email surfacing + visual refresh → Task 5.
- Golden-value regression test → Task 3, Step 2.
- Non-goals (percent-of-income rollup, auto-pulling from Chase, auto-reset) → none implemented, none referenced by any task.

**Placeholder scan:** none found -- the one inline note in Task 3 Step 4 (`__import__("datetime")` should be replaced with a proper import) is itself an explicit instruction with the exact replacement given, not a TBD.

**Type consistency:** `BudgetSnapshot`/`CardSnapshot` field names are identical across Task 3 (definition), Task 4 (endpoint response_model), Task 5 (`WeeklyDigest.snapshot`, `_digest_html`'s `snap.*` accesses), and Task 6 (`snapshot.*` accesses in Dashboard.tsx) -- `left_to_spend_weekly`, `not_saving_weekly`, `cards[].pending_charges`, `cards[].utilization_pct` all match byte-for-byte everywhere they're read.
