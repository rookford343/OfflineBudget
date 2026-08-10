# Weekly Spendable Pacer & Email Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Household Snapshot's weekly spendable figure with a transaction-driven, calendar-week pacer that adapts daily to actual spending and rolls over within the month; consolidate the Daily Summary and Weekly Digest emails so only one sends on digest day; give the digest a visual refresh.

**Architecture:** A new, self-contained module (`backend/services/spendable_pacer.py`) computes the pacer from real `Transaction`/`CreditCardTransaction` rows and a `leftover` figure the caller already has — it does not touch or duplicate `budget_snapshot.py`'s existing, spreadsheet-verified `left_to_spend`/`not_saving` formulas. `budget_snapshot.py` wires the result into `BudgetSnapshot`, which the Dashboard and email digest already consume. `main.py` gets a small scheduling guard plus a styling pass on the existing digest HTML template.

**Tech Stack:** FastAPI + SQLAlchemy + SQLite (backend), React + TypeScript (frontend), pytest, existing in-memory `db_session` test fixture.

## Global Constraints

- Rollover is whole-month: one shared pool, overspend/underspend in a week changes future weeks' targets. No persisted state — recompute fresh on every read from `leftover` (caller-supplied) and actual transactions.
- "Discretionary spend" excludes: transactions linked to a `RecurringItem` (checking `recurring_item_id IS NOT NULL`), transactions in a `savings`-type category, transactions referenced by any `PlannedTransfer.verified_transaction_id`, and card charges already counted via a card-linked recurring item (`RecurringItem.card_id IS NOT NULL`) for the date range in question.
- Weeks are calendar weeks, Sunday–Saturday. A week that straddles a month boundary is clipped to the current month for spend-tracking purposes (never count last month's spend against this month's pool).
- `left_to_spend` and `not_saving` (and `not_saving_weekly`) are NOT modified — their formulas are spreadsheet-verified against Dan's real Budget.xlsx and stay exactly as they are.
- `left_to_spend_weekly` stays in `BudgetSnapshot` (existing consumers read it) but its value is now `compute_weekly_spendable(...).spendable_this_week` instead of the old `_weekly_allowance` calculation.
- New `BudgetSnapshot` fields: `spendable_today: Decimal`, `days_left_in_week: int`, `on_pace: bool`.
- Daily Summary is skipped (not deleted — still runs every other day) on the same weekday the Weekly Digest sends (`settings.WEEKLY_DIGEST_DAY`).
- Digest visual style: Option A from the approved mockup — refined stat cards, same inline-styled table-based HTML (email-client compatible), no structural rewrite.

---

### Task 1: Week/date math (pure functions)

**Files:**
- Create: `backend/services/spendable_pacer.py`
- Test: `backend/tests/test_spendable_pacer.py`

**Interfaces:**
- Consumes: nothing (pure date math, no DB, no other modules).
- Produces: `week_bounds(as_of: date) -> tuple[date, date]`, `weeks_remaining_in_month(as_of: date) -> Decimal`. Both used by Task 3.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_spendable_pacer.py
from datetime import date
from decimal import Decimal
from backend.services.spendable_pacer import week_bounds, weeks_remaining_in_month


def test_week_bounds_for_a_midweek_date():
    # Aug 7 2026 is a Friday; the Sun-Sat week containing it is Aug 2-8.
    assert week_bounds(date(2026, 8, 7)) == (date(2026, 8, 2), date(2026, 8, 8))


def test_week_bounds_when_as_of_is_the_sunday_itself():
    assert week_bounds(date(2026, 8, 2)) == (date(2026, 8, 2), date(2026, 8, 8))


def test_week_bounds_when_as_of_is_the_saturday_itself():
    assert week_bounds(date(2026, 8, 8)) == (date(2026, 8, 2), date(2026, 8, 8))


def test_weeks_remaining_in_month_on_the_first_of_a_28_day_month():
    # Feb 2026 has 28 days (not a leap year) -- exactly 4 weeks remain on day 1.
    assert weeks_remaining_in_month(date(2026, 2, 1)) == Decimal("4")


def test_weeks_remaining_in_month_on_the_last_day():
    # 1 day remaining -> 1/7 of a week, never zero (avoids downstream division by zero).
    assert weeks_remaining_in_month(date(2026, 2, 28)) == Decimal("1") / Decimal("7")


def test_weeks_remaining_in_month_mid_month():
    # Feb 8 2026: days_remaining = 28 - 8 + 1 = 21 -> 21/7 = 3 exactly.
    assert weeks_remaining_in_month(date(2026, 2, 8)) == Decimal("3")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && source ../.venv/bin/activate && python -m pytest tests/test_spendable_pacer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.services.spendable_pacer'`

- [ ] **Step 3: Write the implementation**

```python
# backend/services/spendable_pacer.py
"""Weekly spendable pacer -- a transaction-driven, calendar-week view into
the same monthly discretionary budget `budget_snapshot.py` already computes
as `leftover`. Does NOT touch left_to_spend/not_saving (spreadsheet-verified,
balance-derived, unchanged) -- this is a second, independent calculation
that fixes the gap those formulas have: discretionary checking/debit
spending never moved them at all, only credit card balances did.

No persisted state. Every value here is recomputed fresh from `leftover`
(caller-supplied) and actual Transaction/CreditCardTransaction rows on every
call, so a week's over/underspend is automatically visible today and
automatically reshapes every later week's target this month -- one shared
pool, not four independent per-week budgets.
"""
from __future__ import annotations
import calendar
from datetime import date, timedelta
from decimal import Decimal


def week_bounds(as_of: date) -> tuple[date, date]:
    """The Sunday-Saturday calendar week containing as_of."""
    # date.weekday(): Monday=0 .. Sunday=6. Convert to "days since Sunday".
    days_since_sunday = (as_of.weekday() + 1) % 7
    week_start = as_of - timedelta(days=days_since_sunday)
    week_end = week_start + timedelta(days=6)
    return week_start, week_end


def weeks_remaining_in_month(as_of: date) -> Decimal:
    """Fractional weeks remaining in as_of's month, counting today through
    month-end inclusive, in 7-day units -- e.g. a 3-day final stretch of
    the month counts as 3/7, not a full week. Always > 0 since as_of is
    always on or before its own month's last day."""
    last_day = calendar.monthrange(as_of.year, as_of.month)[1]
    month_end = date(as_of.year, as_of.month, last_day)
    days_remaining = (month_end - as_of).days + 1
    return Decimal(days_remaining) / Decimal(7)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && source ../.venv/bin/activate && python -m pytest tests/test_spendable_pacer.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/services/spendable_pacer.py backend/tests/test_spendable_pacer.py
git commit -m "Add week-boundary and weeks-remaining math for the spendable pacer"
```

---

### Task 2: Discretionary spend calculation

**Files:**
- Modify: `backend/services/spendable_pacer.py` (append to Task 1's file)
- Test: `backend/tests/test_spendable_pacer.py` (append)

**Interfaces:**
- Consumes: `models.Transaction`, `models.CreditCardTransaction`, `models.RecurringItem`, `models.PlannedTransfer`, `models.Category`, `spending_helpers.NOT_SAVINGS` (existing, `backend/services/spending_helpers.py`).
- Produces: `discretionary_spend_in_range(db: Session, user_id: int, start: date, end: date) -> Decimal`. Used by Task 3.

- [ ] **Step 1: Write the failing tests**

```python
# append to backend/tests/test_spendable_pacer.py
from backend import models
from backend.services.spendable_pacer import discretionary_spend_in_range


def _make_user_and_checking(db):
    user = models.User(username="t", hashed_password="x", display_name="T")
    db.add(user)
    db.flush()
    checking = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking)
    db.add(checking)
    db.flush()
    return user, checking


def test_counts_a_plain_discretionary_checking_transaction(db_session):
    user, checking = _make_user_and_checking(db_session)
    db_session.add(models.Transaction(
        user_id=user.id, account_id=checking.id, date=date(2026, 8, 3),
        amount=Decimal("-45.00"), description="Coffee shop", is_actual=True,
    ))
    db_session.commit()

    assert discretionary_spend_in_range(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7)) == Decimal("45.00")


def test_excludes_a_recurring_linked_checking_transaction(db_session):
    """A bill payment (e.g. mortgage debit) is already counted in `leftover`
    up front -- counting it again here would double-dip."""
    user, checking = _make_user_and_checking(db_session)
    recurring = models.RecurringItem(
        user_id=user.id, account_id=checking.id, name="Mortgage", amount=Decimal("2000.00"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=3, start_date=date(2026, 1, 1),
    )
    db_session.add(recurring)
    db_session.flush()
    db_session.add(models.Transaction(
        user_id=user.id, account_id=checking.id, date=date(2026, 8, 3),
        amount=Decimal("-2000.00"), description="Mortgage Co", is_actual=True,
        recurring_item_id=recurring.id,
    ))
    db_session.commit()

    assert discretionary_spend_in_range(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7)) == Decimal("0.00")


def test_excludes_a_savings_category_checking_transaction(db_session):
    user, checking = _make_user_and_checking(db_session)
    savings_cat = models.Category(user_id=user.id, name="Savings", type=models.CategoryType.savings)
    db_session.add(savings_cat)
    db_session.flush()
    db_session.add(models.Transaction(
        user_id=user.id, account_id=checking.id, date=date(2026, 8, 3),
        amount=Decimal("-500.00"), description="To savings", is_actual=True,
        category_id=savings_cat.id,
    ))
    db_session.commit()

    assert discretionary_spend_in_range(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7)) == Decimal("0.00")


def test_excludes_a_verified_planned_transfer_transaction(db_session):
    """A PlannedTransfer's verified_transaction_id points at the real
    transaction that fulfilled it -- a savings movement, not spending, even
    if it landed in an uncategorized or non-savings-tagged row."""
    user, checking = _make_user_and_checking(db_session)
    savings = models.Account(user_id=user.id, name="Savings", type=models.AccountType.savings)
    db_session.add(savings)
    db_session.flush()
    txn = models.Transaction(
        user_id=user.id, account_id=checking.id, date=date(2026, 8, 3),
        amount=Decimal("-1000.00"), description="Transfer to savings", is_actual=True,
    )
    db_session.add(txn)
    db_session.flush()
    db_session.add(models.PlannedTransfer(
        user_id=user.id, from_account_id=checking.id, to_account_id=savings.id,
        amount=Decimal("1000.00"), target_date=date(2026, 8, 3),
        status=models.PlannedTransferStatus.verified, verified_transaction_id=txn.id,
    ))
    db_session.commit()

    assert discretionary_spend_in_range(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7)) == Decimal("0.00")


def test_counts_a_plain_card_charge(db_session):
    user, checking = _make_user_and_checking(db_session)
    card = models.CreditCard(
        user_id=user.id, name="Visa", credit_limit=Decimal("5000.00"),
        statement_day=28, due_day=15,
    )
    db_session.add(card)
    db_session.flush()
    db_session.add(models.CreditCardTransaction(
        card_id=card.id, user_id=user.id, date=date(2026, 8, 3),
        amount=Decimal("80.00"), merchant="Grocery Store",
    ))
    db_session.commit()

    assert discretionary_spend_in_range(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7)) == Decimal("80.00")


def test_excludes_a_card_linked_recurring_subscription_from_card_spend(db_session):
    """A subscription billed to a card (RecurringItem.card_id set) is
    already counted in `leftover` via _cc_budget_total -- deduct it from
    the card total for the range it fires in, the same day-of-month
    'firing' logic budget_snapshot.py's _charged_so_far already uses
    (not per-transaction fuzzy matching)."""
    user, checking = _make_user_and_checking(db_session)
    card = models.CreditCard(
        user_id=user.id, name="Visa", credit_limit=Decimal("5000.00"),
        statement_day=28, due_day=15,
    )
    db_session.add(card)
    db_session.flush()
    db_session.add(models.RecurringItem(
        user_id=user.id, account_id=checking.id, name="Streaming", amount=Decimal("15.99"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=3, start_date=date(2026, 1, 1), card_id=card.id,
    ))
    db_session.add(models.CreditCardTransaction(
        card_id=card.id, user_id=user.id, date=date(2026, 8, 3),
        amount=Decimal("80.00"), merchant="Grocery Store",
    ))
    db_session.add(models.CreditCardTransaction(
        card_id=card.id, user_id=user.id, date=date(2026, 8, 3),
        amount=Decimal("15.99"), merchant="Streaming Co",
    ))
    db_session.commit()

    # Total card charges in range = 95.99; the subscription's 15.99 is
    # deducted (it fires day_of_month=3, inside [Aug 1, Aug 7]) -> 80.00.
    assert discretionary_spend_in_range(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7)) == Decimal("80.00")


def test_recurring_card_charge_firing_across_a_month_boundary(db_session):
    user, checking = _make_user_and_checking(db_session)
    card = models.CreditCard(
        user_id=user.id, name="Visa", credit_limit=Decimal("5000.00"),
        statement_day=28, due_day=15,
    )
    db_session.add(card)
    db_session.flush()
    # Fires on the 2nd of every month -- Sep 2 falls inside a week that
    # starts Aug 30 (Sunday) and ends Sep 5 (Saturday).
    db_session.add(models.RecurringItem(
        user_id=user.id, account_id=checking.id, name="Streaming", amount=Decimal("15.99"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=2, start_date=date(2026, 1, 1), card_id=card.id,
    ))
    db_session.add(models.CreditCardTransaction(
        card_id=card.id, user_id=user.id, date=date(2026, 9, 2),
        amount=Decimal("100.00"), merchant="Grocery Store",
    ))
    db_session.commit()

    # 100.00 total in range, 15.99 subscription deducted (fires Sep 2, inside range).
    assert discretionary_spend_in_range(db_session, user.id, date(2026, 8, 30), date(2026, 9, 5)) == Decimal("84.01")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && source ../.venv/bin/activate && python -m pytest tests/test_spendable_pacer.py -v`
Expected: FAIL with `ImportError: cannot import name 'discretionary_spend_in_range'`

- [ ] **Step 3: Write the implementation**

```python
# append to backend/services/spendable_pacer.py
from sqlalchemy import or_
from sqlalchemy.orm import Session
from backend import models
from backend.services.spending_helpers import NOT_SAVINGS


def _recurring_card_charges_in_range(db: Session, user_id: int, start: date, end: date) -> Decimal:
    """Sum of card-linked recurring items (RecurringItem.card_id set --
    subscriptions billed to a card, already counted in the monthly leftover
    pool via budget_snapshot.py's _cc_budget_total) that fire on any day in
    [start, end]. Mirrors _charged_so_far's day-of-month firing logic but
    over an arbitrary range instead of "month start through as_of", so it
    still works when a calendar week straddles a month boundary. Like
    _charged_so_far, this fires on the calendar day regardless of whether a
    matching real CreditCardTransaction has posted yet -- same accepted
    tradeoff already established there, not a new gap.
    """
    items = db.query(models.RecurringItem).filter(
        models.RecurringItem.user_id == user_id,
        models.RecurringItem.type == models.RecurringType.expense,
        models.RecurringItem.is_active == True,
        models.RecurringItem.card_id.isnot(None),
    ).all()
    total = Decimal("0")
    day = start
    while day <= end:
        last_day_of_month = calendar.monthrange(day.year, day.month)[1]
        for item in items:
            if item.start_date > day or (item.end_date and item.end_date < day):
                continue
            if item.frequency == models.RecurringFrequency.monthly:
                fires = True
            elif item.frequency == models.RecurringFrequency.yearly:
                fires = item.month_of_year == day.month
            else:
                fires = False
            if not fires:
                continue
            due_day = item.day_of_month if item.day_of_month > 0 else last_day_of_month
            if min(due_day, last_day_of_month) == day.day:
                total += item.amount
        day += timedelta(days=1)
    return total


def discretionary_spend_checking(db: Session, user_id: int, start: date, end: date) -> Decimal:
    verified_txn_ids = {
        row[0] for row in db.query(models.PlannedTransfer.verified_transaction_id)
        .filter(
            models.PlannedTransfer.user_id == user_id,
            models.PlannedTransfer.verified_transaction_id.isnot(None),
        ).all()
    }
    rows = (
        db.query(models.Transaction)
        .outerjoin(models.Category, models.Transaction.category_id == models.Category.id)
        .filter(
            models.Transaction.user_id == user_id,
            models.Transaction.is_actual == True,
            models.Transaction.date >= start,
            models.Transaction.date <= end,
            models.Transaction.amount < 0,
            models.Transaction.recurring_item_id.is_(None),
            NOT_SAVINGS,
        )
        .all()
    )
    return sum((abs(t.amount) for t in rows if t.id not in verified_txn_ids), Decimal("0"))


def discretionary_spend_card(db: Session, user_id: int, start: date, end: date) -> Decimal:
    rows = (
        db.query(models.CreditCardTransaction)
        .outerjoin(models.Category, models.CreditCardTransaction.category_id == models.Category.id)
        .filter(
            models.CreditCardTransaction.user_id == user_id,
            models.CreditCardTransaction.date >= start,
            models.CreditCardTransaction.date <= end,
            models.CreditCardTransaction.amount > 0,
            or_(
                models.CreditCardTransaction.category_id.is_(None),
                models.Category.type != models.CategoryType.savings,
            ),
        )
        .all()
    )
    total = sum((t.amount for t in rows), Decimal("0"))
    recurring = _recurring_card_charges_in_range(db, user_id, start, end)
    return max(total - recurring, Decimal("0"))


def discretionary_spend_in_range(db: Session, user_id: int, start: date, end: date) -> Decimal:
    """Total discretionary spend (checking + card) in [start, end] --
    excludes bills, savings movements, and card subscriptions already
    counted elsewhere. See module docstring."""
    return discretionary_spend_checking(db, user_id, start, end) + discretionary_spend_card(db, user_id, start, end)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && source ../.venv/bin/activate && python -m pytest tests/test_spendable_pacer.py -v`
Expected: PASS (all tests in the file so far)

- [ ] **Step 5: Commit**

```bash
git add backend/services/spendable_pacer.py backend/tests/test_spendable_pacer.py
git commit -m "Add discretionary-spend calculation, excluding bills/savings/card subscriptions"
```

---

### Task 3: Weekly pacer orchestrator (rollover)

**Files:**
- Modify: `backend/services/spendable_pacer.py` (append to Tasks 1-2's file)
- Test: `backend/tests/test_spendable_pacer.py` (append)

**Interfaces:**
- Consumes: `week_bounds`, `weeks_remaining_in_month` (Task 1), `discretionary_spend_in_range` (Task 2).
- Produces: `WeeklySpendable` dataclass (`spendable_this_week: Decimal`, `spendable_today: Decimal`, `days_left_in_week: int`, `on_pace: bool`) and `compute_weekly_spendable(db: Session, user_id: int, leftover: Decimal, as_of: date) -> WeeklySpendable`. Used by Task 4.

- [ ] **Step 1: Write the failing tests**

```python
# append to backend/tests/test_spendable_pacer.py
from backend.services.spendable_pacer import compute_weekly_spendable


def test_this_week_target_splits_the_pool_evenly_with_no_spend_yet(db_session):
    user, checking = _make_user_and_checking(db_session)
    db_session.commit()

    # Feb 1 2026 is a Sunday, Feb has 28 days -> exactly 4 whole weeks.
    result = compute_weekly_spendable(db_session, user.id, Decimal("2500.00"), date(2026, 2, 1))

    assert result.spendable_this_week == Decimal("625.00")  # 2500 / 4
    assert result.days_left_in_week == 7
    assert result.spendable_today == Decimal("89.29")  # 625 / 7, quantized
    assert result.on_pace is True


def test_overspending_shrinks_a_later_weeks_target(db_session):
    """Rollover: $700 spent in week 1 (target was $625, so $75 over) eats
    into every remaining week, not just week 1."""
    user, checking = _make_user_and_checking(db_session)
    db_session.add(models.Transaction(
        user_id=user.id, account_id=checking.id, date=date(2026, 2, 3),
        amount=Decimal("-700.00"), description="Big week", is_actual=True,
    ))
    db_session.commit()

    # Feb 8 2026 is the Sunday starting week 2. 3 whole weeks remain (21/7).
    result = compute_weekly_spendable(db_session, user.id, Decimal("2500.00"), date(2026, 2, 8))

    # remaining_pool = 2500 - 700 = 1800; 1800 / 3 weeks = 600 (vs the
    # original 625/week even pace -- the $75 overspend split across 3
    # remaining weeks is exactly the $25/week shortfall: 625 - 25 = 600).
    assert result.spendable_this_week == Decimal("600.00")
    assert result.on_pace is True


def test_prior_week_and_this_weeks_spend_are_not_double_counted(db_session):
    """Regression: the pool must be depleted by spend from BEFORE this
    week only. Depleting it by full month-to-date (which always includes
    this week's own spend) and then ALSO subtracting this week's spend
    from the per-week target double-counts every dollar spent so far this
    week."""
    user, checking = _make_user_and_checking(db_session)
    db_session.add(models.Transaction(  # week 1 spend
        user_id=user.id, account_id=checking.id, date=date(2026, 2, 3),
        amount=Decimal("-700.00"), description="Week 1", is_actual=True,
    ))
    db_session.add(models.Transaction(  # week 2 spend, on the day being evaluated
        user_id=user.id, account_id=checking.id, date=date(2026, 2, 8),
        amount=Decimal("-50.00"), description="Week 2 so far", is_actual=True,
    ))
    db_session.commit()

    result = compute_weekly_spendable(db_session, user.id, Decimal("2500.00"), date(2026, 2, 8))

    # this_week_target = (2500 - 700) / 3 weeks = 600 (week 1's spend only,
    # matching test_overspending_shrinks_a_later_weeks_target above);
    # spendable_this_week = 600 - 50 (week 2's own spend, subtracted once) = 550.
    # A double-counting bug would instead deplete the pool by 750 (700+50)
    # before dividing AND subtract the 50 again, landing on 533.33.
    assert result.spendable_this_week == Decimal("550.00")


def test_this_weeks_spend_reduces_spendable_this_week(db_session):
    user, checking = _make_user_and_checking(db_session)
    db_session.add(models.Transaction(
        user_id=user.id, account_id=checking.id, date=date(2026, 2, 1),
        amount=Decimal("-900.00"), description="Overspend", is_actual=True,
    ))
    db_session.commit()

    result = compute_weekly_spendable(db_session, user.id, Decimal("2500.00"), date(2026, 2, 1))

    # this_week_target = 2500/4 = 625; spend_this_week (Feb1-Feb1) = 900.
    assert result.spendable_this_week == Decimal("-275.00")
    assert result.on_pace is False


def test_this_weeks_spend_is_clipped_to_the_current_month(db_session):
    """A calendar week can start in the previous month -- Aug 1 2026 is a
    Saturday, so its Sun-Sat week runs Jul 26 - Aug 1. Spend from before
    the month started must not count against THIS week's target, even
    though it falls inside the raw Sun-Sat window."""
    user, checking = _make_user_and_checking(db_session)
    db_session.add(models.Transaction(
        user_id=user.id, account_id=checking.id, date=date(2026, 7, 31),
        amount=Decimal("-5000.00"), description="July spending", is_actual=True,
    ))
    db_session.commit()

    result = compute_weekly_spendable(db_session, user.id, Decimal("2500.00"), date(2026, 8, 1))

    # this_week_target = leftover / weeks_remaining_in_month(Aug 1) = 2500 / (31/7).
    # spend_this_week must be 0 -- July's $5000 sits outside the clipped
    # [Aug 1, Aug 1] window -- so spendable_this_week is the full target,
    # completely unaffected by July's spend.
    expected_target = (Decimal("2500.00") / (Decimal("31") / Decimal("7"))).quantize(Decimal("0.01"))
    assert result.spendable_this_week == expected_target
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && source ../.venv/bin/activate && python -m pytest tests/test_spendable_pacer.py -v`
Expected: FAIL with `ImportError: cannot import name 'compute_weekly_spendable'`

- [ ] **Step 3: Write the implementation**

```python
# append to backend/services/spendable_pacer.py
from dataclasses import dataclass


@dataclass
class WeeklySpendable:
    spendable_this_week: Decimal
    spendable_today: Decimal
    days_left_in_week: int
    on_pace: bool


def compute_weekly_spendable(db: Session, user_id: int, leftover: Decimal, as_of: date) -> WeeklySpendable:
    """The weekly/daily spendable pacer. `leftover` is the caller's already-
    computed monthly discretionary budget (budget_snapshot.py's `leftover` --
    income minus fixed bills minus savings/groceries budgets). Recomputed
    fresh every call from actual transactions; no persisted state. See
    module docstring for the rollover model.

    IMPORTANT: the pool that gets divided across remaining weeks must be
    depleted only by spend from BEFORE this week (`spend_prior_to_this_week`)
    -- not month-to-date spend. Month-to-date always includes this week's
    own spend-so-far (effective_week_start is always >= month_start), so
    subtracting the full MTD total here and then ALSO subtracting this
    week's spend from the per-week target a few lines down would double
    count every dollar spent so far this week. Depleting the pool by prior
    weeks only, then subtracting this week's own spend exactly once from
    this_week_target, is what makes a prior week's overspend roll into
    later weeks without a second, redundant deduction inside the very week
    that spend happened in.
    """
    month_start = as_of.replace(day=1)
    week_start, week_end = week_bounds(as_of)
    effective_week_start = max(week_start, month_start)

    if effective_week_start > month_start:
        spend_prior_to_this_week = discretionary_spend_in_range(
            db, user_id, month_start, effective_week_start - timedelta(days=1)
        )
    else:
        spend_prior_to_this_week = Decimal("0")  # this week IS the first week of the month
    remaining_pool = leftover - spend_prior_to_this_week

    weeks_left = weeks_remaining_in_month(as_of)
    this_week_target = remaining_pool / weeks_left

    spend_this_week = discretionary_spend_in_range(db, user_id, effective_week_start, as_of)
    spendable_this_week = (this_week_target - spend_this_week).quantize(Decimal("0.01"))

    days_left_in_week = (week_end - as_of).days + 1
    spendable_today = (spendable_this_week / Decimal(days_left_in_week)).quantize(Decimal("0.01"))

    return WeeklySpendable(
        spendable_this_week=spendable_this_week,
        spendable_today=spendable_today,
        days_left_in_week=days_left_in_week,
        on_pace=spendable_this_week >= 0,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && source ../.venv/bin/activate && python -m pytest tests/test_spendable_pacer.py -v`
Expected: PASS (all tests in the file, ~17 total across Tasks 1-3)

- [ ] **Step 5: Commit**

```bash
git add backend/services/spendable_pacer.py backend/tests/test_spendable_pacer.py
git commit -m "Add compute_weekly_spendable orchestrator with month-wide rollover"
```

---

### Task 4: Wire into BudgetSnapshot

**Files:**
- Modify: `backend/schemas.py` (`BudgetSnapshot` class, around line 1033-1043)
- Modify: `backend/services/budget_snapshot.py` (`compute_budget_snapshot`, around lines 168-209)
- Modify: `backend/tests/test_budget_snapshot.py`

**Interfaces:**
- Consumes: `compute_weekly_spendable` (Task 3).
- Produces: `BudgetSnapshot.spendable_today`, `BudgetSnapshot.days_left_in_week`, `BudgetSnapshot.on_pace` -- consumed by Task 6 (email) and Task 7 (frontend). `BudgetSnapshot.left_to_spend_weekly` keeps its existing name/type but is now `compute_weekly_spendable(...).spendable_this_week`.

- [ ] **Step 1: Update the schema**

In `backend/schemas.py`, add three fields to `BudgetSnapshot` right after `left_to_spend_weekly`:

```python
class BudgetSnapshot(BaseModel):
    as_of: date
    leftover: Decimal
    left_to_spend: Decimal
    left_to_spend_weekly: Decimal
    spendable_today: Decimal
    days_left_in_week: int
    on_pace: bool
    not_saving: Decimal
    not_saving_weekly: Decimal
    days_remaining_in_month: int
    cards: list[CardSnapshot]
    categories: list[WeeklyDigestCategory]
    top_merchants: list[MerchantSpendingEntry]
```

- [ ] **Step 2: Update two now-invalid existing tests first**

The old `left_to_spend_weekly` was a simple division of `left_to_spend` (`_weekly_allowance`); the new one is a completely different, transaction-driven calculation, so these two assertions no longer hold and must be removed (their behavior is now covered by `test_spendable_pacer.py`, Tasks 1-3):

In `backend/tests/test_budget_snapshot.py`, in `test_left_to_spend_and_not_saving_match_spreadsheet_exactly`, delete this line and replace with a comment:

```python
    # left_to_spend_weekly is no longer derived from left_to_spend -- it's
    # the transaction-driven weekly pacer now (see test_spendable_pacer.py).
    # Not asserted here; this test only covers the spreadsheet-verified
    # left_to_spend/not_saving formulas, which are unchanged.
```

(i.e. remove `assert snapshot.left_to_spend_weekly == Decimal("438.96")`, keep the other three assertions in that test as-is.)

Delete the entire `test_weekly_allowance_uses_full_amount_in_final_week_of_month` test function -- its premise ("collapse to the full amount when <=7 days remain") was specific to the old `_weekly_allowance` helper, which no longer computes `left_to_spend_weekly`. `weeks_remaining_in_month`'s fractional-week behavior is covered by `test_spendable_pacer.py`.

- [ ] **Step 3: Run to confirm the now-simplified tests still pass on old code, then wire the new call**

Run: `cd backend && source ../.venv/bin/activate && python -m pytest tests/test_budget_snapshot.py -v`
Expected: PASS (with the two edits from Step 2, still against the OLD `compute_budget_snapshot` -- confirms the test file itself is valid before touching the implementation)

In `backend/services/budget_snapshot.py`, add the import near the top:

```python
from backend.services.spendable_pacer import compute_weekly_spendable
```

Replace these two lines:

```python
    left_to_spend_weekly, days_remaining = _weekly_allowance(left_to_spend, as_of)
    not_saving_weekly, _ = _weekly_allowance(not_saving, as_of)
```

with:

```python
    not_saving_weekly, days_remaining = _weekly_allowance(not_saving, as_of)
    weekly_spendable = compute_weekly_spendable(db, user.id, leftover, as_of)
```

Update the `BudgetSnapshot(...)` return near the bottom of the function:

```python
    return BudgetSnapshot(
        as_of=as_of,
        leftover=leftover,
        left_to_spend=left_to_spend,
        left_to_spend_weekly=weekly_spendable.spendable_this_week,
        spendable_today=weekly_spendable.spendable_today,
        days_left_in_week=weekly_spendable.days_left_in_week,
        on_pace=weekly_spendable.on_pace,
        not_saving=not_saving,
        not_saving_weekly=not_saving_weekly,
        days_remaining_in_month=days_remaining,
        cards=cards,
        categories=categories,
        top_merchants=top_merchants,
    )
```

- [ ] **Step 4: Run the full backend suite**

Run: `cd backend && source ../.venv/bin/activate && python -m pytest -v`
Expected: PASS. `test_budget_snapshot.py`'s remaining assertions (on `left_to_spend`, `not_saving`, `not_saving_weekly`) must be unchanged in value -- if any of those three fail, the wiring touched something it shouldn't have; stop and re-check Step 3's edit only replaced the two named lines.

- [ ] **Step 5: Commit**

```bash
git add backend/schemas.py backend/services/budget_snapshot.py backend/tests/test_budget_snapshot.py
git commit -m "Wire the weekly spendable pacer into BudgetSnapshot"
```

---

### Task 5: Skip Daily Summary on the digest day

**Files:**
- Modify: `backend/main.py` (`_send_daily_summaries`, around line 34; new pure helper alongside it)
- Test: `backend/tests/test_email_scheduling.py` (new)

**Interfaces:**
- Consumes: `settings.WEEKLY_DIGEST_DAY` (existing, `backend/config.py`).
- Produces: `_is_digest_day(today: date, digest_day: str) -> bool`, importable from `backend.main` for the test.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_email_scheduling.py
from datetime import date
from backend.main import _is_digest_day


def test_is_digest_day_true_on_the_matching_weekday():
    # Aug 14 2026 is a Friday.
    assert _is_digest_day(date(2026, 8, 14), "fri") is True


def test_is_digest_day_false_on_other_weekdays():
    # Aug 13 2026 is a Thursday.
    assert _is_digest_day(date(2026, 8, 13), "fri") is False


def test_is_digest_day_is_case_and_whitespace_insensitive():
    assert _is_digest_day(date(2026, 8, 14), " FRI ") is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && source ../.venv/bin/activate && python -m pytest tests/test_email_scheduling.py -v`
Expected: FAIL with `ImportError: cannot import name '_is_digest_day'`

- [ ] **Step 3: Write the implementation**

In `backend/main.py`, add above `_send_daily_summaries`:

```python
_WEEKDAY_ABBREVIATIONS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _is_digest_day(today: date, digest_day: str) -> bool:
    """True when `today` is the weekday the Weekly Digest sends on
    (settings.WEEKLY_DIGEST_DAY, APScheduler cron day_of_week format, e.g.
    'fri') -- the Daily Summary is skipped that day since the digest
    already covers the same ground (account/card balances, spending)."""
    return _WEEKDAY_ABBREVIATIONS[today.weekday()] == digest_day.strip().lower()
```

Then add the guard as the first line inside `_send_daily_summaries`:

```python
def _send_daily_summaries() -> None:
    if _is_digest_day(date.today(), settings.WEEKLY_DIGEST_DAY):
        logger.info("Skipping daily summary -- weekly digest covers today.")
        return
    from backend.database import SessionLocal
    from backend import models
    from backend.services.email_service import send_email
    from backend.services.summary_generator import generate_daily_summary
    db = SessionLocal()
    ...  # rest of the function unchanged
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && source ../.venv/bin/activate && python -m pytest tests/test_email_scheduling.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/main.py backend/tests/test_email_scheduling.py
git commit -m "Skip Daily Summary email on the Weekly Digest's send day"
```

---

### Task 6: Digest visual refresh + Household Snapshot section

**Files:**
- Modify: `backend/main.py` (`_digest_html`, around lines 63-172)

**Interfaces:**
- Consumes: `BudgetSnapshot.spendable_today`, `.on_pace`, `.left_to_spend_weekly` (Task 4).
- Produces: updated HTML/text digest bodies -- no new callers, `_send_weekly_digest` already calls `_digest_html` unchanged.

This task is a template-only change (no new logic to unit test -- `_digest_html` isn't covered by an automated test today and this plan doesn't add one; verify visually per Step 3). Read the CURRENT `_digest_html` in `backend/main.py` before editing -- do not guess at surrounding code, the exact `fmt`/`section`/`stat_card` helpers and their call sites are already there.

- [ ] **Step 1: Replace the `stat_card` helper and `snapshot_html` block**

Replace the existing `stat_card` helper:

```python
    def stat_card(label: str, value: str, color: str, sub: str = "") -> str:
        sub_html = f"<div style='font-size:10px;color:{color};margin-top:2px'>{sub}</div>" if sub else ""
        return (
            f"<td style='padding:14px;background:#f9fafb;border-radius:10px;text-align:center;width:50%;"
            f"box-shadow:0 1px 2px rgba(0,0,0,0.04)'>"
            f"<div style='font-size:11px;color:#6b7280;margin-bottom:4px'>{label}</div>"
            f"<div style='font-size:22px;font-weight:700;color:{color}'>{value}</div>{sub_html}</td>"
        )
```

Replace the existing `snapshot_html` assignment:

```python
    pace_color = "#059669" if snap.on_pace else "#dc2626"
    pace_text = f"${abs(float(snap.spendable_today)):,.2f}/day" + (" · on pace" if snap.on_pace else " · over pace")
    snapshot_html = section(
        "Household Snapshot",
        f"<table style='width:100%;border-spacing:10px 0'><tr>"
        f"{stat_card('Spendable this week', fmt(snap.left_to_spend_weekly), pace_color, pace_text)}"
        f"{stat_card('Not Saving (this week)', fmt(snap.not_saving_weekly), '#d97706')}"
        f"</tr></table>"
        f"<p style='font-size:12px;color:#9ca3af;margin:8px 0 0'>Monthly: {fmt(snap.left_to_spend)} left to spend, "
        f"{fmt(snap.not_saving)} before it eats into savings.</p>",
    )
```

- [ ] **Step 2: Tighten the outer card shadow/radius to match the approved mockup**

In the `html = f"""..."""` block, the outer body `<div>` currently reads (find the line starting `<html><body`) -- change the inline body style from plain padding to the refined-card look used in the mockup (rounded corners + shadow on the card, light gray page background so the white card reads as a card):

```python
    html = f"""<!DOCTYPE html>
<html><body style='font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:0;padding:24px;background:#f3f4f6'>
<div style='max-width:520px;margin:0 auto;padding:28px;color:#1f2937;background:#ffffff;border-radius:12px;box-shadow:0 1px 3px rgba(0,0,0,0.08)'>
<h2 style='color:#4f46e5;margin:0 0 4px;font-size:20px'>OfflineBudget Weekly Digest</h2>
<p style='color:#6b7280;margin:0 0 20px;font-size:13px'>{digest.week_start.strftime("%B %-d")} – {digest.week_end.strftime("%B %-d, %Y")} · For {user.display_name}</p>

<p style='font-size:14px'>Total spent this week: <b>{fmt(digest.total_spent)}</b></p>

{snapshot_html}
{risk_html}
{cards_html}
{cat_html}
{merchant_html}

<p style='color:#9ca3af;font-size:11px;margin-top:20px'>Sent by OfflineBudget</p>
</div>
</body></html>"""
```

(This wraps the existing content in the rounded/shadowed card div from the mockup; the `section`/`stat_card`/`cards_html`/`cat_html`/`merchant_html`/`risk_html` helpers and variables are unchanged from the existing function -- only the outer wrapper and the snapshot section change.)

- [ ] **Step 3: Update the plain-text body to mention the new pace line**

Find the `text = f"""..."""` block's `HOUSEHOLD SNAPSHOT` section and update it:

```python
HOUSEHOLD SNAPSHOT
  Spendable this week: {fmt(snap.left_to_spend_weekly)} ({fmt(snap.spendable_today)}/day, {"on pace" if snap.on_pace else "over pace"})
  Not Saving this week: {fmt(snap.not_saving_weekly)} (monthly: {fmt(snap.not_saving)})
```

- [ ] **Step 4: Manually verify the rendered HTML**

Run: `cd backend && source ../.venv/bin/activate && python -c "
from datetime import date
from decimal import Decimal
from backend.schemas import WeeklyDigest, BudgetSnapshot, ForecastRisk
from backend.main import _digest_html
import backend.models as models

user = models.User(username='t', display_name='Dan')
snap = BudgetSnapshot(
    as_of=date.today(), leftover=Decimal('2500'), left_to_spend=Decimal('1567.73'),
    left_to_spend_weekly=Decimal('412.00'), spendable_today=Decimal('58.86'),
    days_left_in_week=7, on_pace=True, not_saving=Decimal('2085.64'),
    not_saving_weekly=Decimal('180.00'), days_remaining_in_month=20,
    cards=[], categories=[], top_merchants=[],
)
digest = WeeklyDigest(
    week_start=date(2026,8,3), week_end=date(2026,8,9), total_spent=Decimal('312.52'),
    categories=[], top_merchants=[], snapshot=snap,
    risk=ForecastRisk(at_risk=False, date=None, amount=None, threshold=Decimal('0')),
)
html, text = _digest_html(user, digest)
open('/tmp/digest-preview.html', 'w').write(html)
print(text)
print('Wrote /tmp/digest-preview.html')
"`
Expected: no exception, prints the text body, writes an HTML file you can open in a browser to visually confirm it matches the approved Option A mockup (card shadow, rounded stat cards, pace subline).

- [ ] **Step 5: Commit**

```bash
git add backend/main.py
git commit -m "Refresh Weekly Digest visual style (Option A) and show the weekly pace"
```

---

### Task 7: Dashboard on-pace subline

**Files:**
- Modify: `frontend/src/pages/Dashboard.tsx` (Household Snapshot card, around lines 157-174)

**Interfaces:**
- Consumes: `snapshot.spendable_today`, `snapshot.on_pace` (Task 4, already present on the `/budget/snapshot` response `useQuery<any>` reads from -- no frontend type change needed).

- [ ] **Step 1: Add the pace subline**

Read the existing block first (`frontend/src/pages/Dashboard.tsx`, the `<div className="text-center p-3 bg-white/60...">` for "Left to Spend (this week)"). Replace its inner paragraph list:

```tsx
                <div className="text-center p-3 bg-white/60 dark:bg-black/20 rounded-lg">
                  <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Left to Spend (this week)</p>
                  <p className="text-xl font-bold text-emerald-600 dark:text-emerald-400 tabular-nums">{fmt(parseFloat(snapshot.left_to_spend_weekly))}</p>
                  <p className={`text-xs mt-1 ${snapshot.on_pace ? "text-emerald-500 dark:text-emerald-400" : "text-red-500 dark:text-red-400"}`}>
                    {fmt(parseFloat(snapshot.spendable_today))}/day · {snapshot.on_pace ? "on pace" : "over pace"}
                  </p>
                  <p className="text-xs text-gray-400 mt-1">{fmt(parseFloat(snapshot.left_to_spend))} this month</p>
                </div>
```

(Only the "Left to Spend (this week)" card changes -- adds one line between the existing weekly figure and the existing monthly subline. The "Not Saving" card next to it is untouched.)

- [ ] **Step 2: Verify with tsc**

Run: `cd frontend && npx tsc -b 2>&1 | grep -c "error TS"`
Expected: same count as before this task started (check with `git stash` / `git stash pop` if unsure of the baseline -- known baseline is 13 as of this plan's writing, all pre-existing and unrelated to this file).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/Dashboard.tsx
git commit -m "Show daily spend pace on the Dashboard Household Snapshot card"
```

---

## Global verification (after all tasks)

```bash
cd backend && source ../.venv/bin/activate && python -m pytest -v
cd ../frontend && npx tsc -b 2>&1 | grep -c "error TS"
```

Expected: full backend suite green, tsc error count unchanged from the pre-task baseline (13, all pre-existing).
