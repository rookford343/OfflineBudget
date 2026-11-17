# Recurring Item Scheduled Amount Change Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Dan enter a recurring item's known future amount change today (e.g. "Mortgage drops to $1,950 starting 1/1/2027") without it retroactively applying to months before the change takes effect, and have the app forget the scheduled change automatically once that date arrives.

**Architecture:** Two new nullable fields on `RecurringItem` (`pending_amount`, `pending_amount_effective_date`) carry the scheduled change. The forecast walk's single amount-resolution point picks the new amount for any projected occurrence on or after the effective date and the old amount otherwise, so every forward-looking figure (next month's low, the 3-month low, Contingency's floor) already sees the right number the moment the change is entered — no other reader of `RecurringItem.amount` needs to change, because they only ever care about "now," and "now" stays correct until the date actually passes. A guarded step in the existing periodic scheduler sweep promotes `pending_amount` into `amount` and clears both fields once `pending_amount_effective_date` has arrived, which is the "auto clear."

**Tech Stack:** FastAPI + SQLAlchemy + SQLite (backend), React + TypeScript (frontend, one page). `uv` for Python, `bun` for JS.

**Spec:** No separate design doc -- brainstormed in chat 2026-11-16 and approved as a "small change": Dan said "yes" to the proposed mechanism (a dated "changes to $Y on this date" field pair, usable on any recurring item, editable from the existing Recurring page item form) and added one explicit requirement: "make it auto clear once that date passes." Every other decision below (field names, exact resolution point, the sweep mechanism) is grounded in this session's recon of the existing codebase, not a guess -- each is called out as such.

## Global Constraints

- Backend: `uv run --locked`; `ruff check` clean; coverage floor in `backend/.coveragerc` never lowered.
- Frontend: `bun`; `bunx vite build`.
- Commits go directly to `main` -- no feature branches, no git worktree (this repo's convention). This plan's own execution queues behind the Account Totals and Change History plans already running/queued on this branch -- never run concurrently with them.
- No real account/bill names, balances, or amounts in commits or test fixtures -- invented placeholders only.
- No new money math beyond picking which of two already-known numbers applies to a given date -- this plan adds no new calculation, only a selection.

## Review Focus

- **A pending change whose effective date is still in the future must not affect "right now."** `GET /recurring/breakdown`'s totals, Contingency's floor, and any other reader of `RecurringItem.amount` must keep returning today's `amount`, unaffected by a scheduled future value. Covered in Task 1 (no other reader touched) and Task 2 (the forecast walk only switches for occurrence dates on/after the effective date, verified against an occurrence date before it).
- **A real confirmed statement amount for an exact date must still win over a scheduled change.** The existing `actual_override` branch in `build_forecast` already beats a plain `item.amount`; it must keep beating a pending amount too, since this plan only touches the fallback branch beneath it. Covered in Task 2.
- **The effective date is a boundary, not a strict "after."** An occurrence falling exactly ON `pending_amount_effective_date` must already use the new amount. Covered in Task 2.
- **The sweep must be safe to run more than once on or after the effective date** (it already runs every 20 minutes). A second run after the first has already promoted and cleared the fields must find nothing to do and change nothing, matching this sweep's existing idempotency doctrine. Covered in Task 3.
- **A half-entered pending change (one of the two fields set, the other left null) must be rejected**, both on create and on a partial update -- an item with a scheduled dollar amount but no date, or a date but no amount, has no defined behavior in Task 2's resolution logic. Covered in Task 1.

---

### Task 1: `pending_amount` / `pending_amount_effective_date` on `RecurringItem`

**Files:**
- Modify: `backend/models.py` -- `RecurringItem` (after `contingency_paused_at`, ~line 360)
- Modify: `backend/database.py` -- `upgrade_schema()` (append after the most recent `recurring_items` column, ~line 344)
- Modify: `backend/schemas.py` -- `RecurringCreate` (~line 317), `RecurringUpdate` (~line 368), `RecurringOut` (~line 397)
- Modify: `backend/routers/recurring.py` -- `update_recurring` (~line 563)
- Test: `backend/tests/test_pending_amount_change.py` (new)

**Interfaces:**
- Consumes: nothing new.
- Produces: `RecurringItem.pending_amount: Decimal | None`, `RecurringItem.pending_amount_effective_date: date | None`, both `None` by default; exposed identically on `RecurringCreate`, `RecurringUpdate` (both `Optional[Decimal]` / `Optional[date]`, default `None`), and `RecurringOut`. These are the two fields Task 2 and Task 3 read and Task 4 renders.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_pending_amount_change.py
from datetime import date
from decimal import Decimal
import pytest
from backend import models

D = Decimal


def _world(db):
    user = models.User(username="pendingamt", hashed_password="x", display_name="PendingAmt")
    db.add(user)
    db.flush()
    checking = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=D("1000.00"),
    )
    db.add(checking)
    db.flush()
    item = models.RecurringItem(
        user_id=user.id, account_id=checking.id, name="Test Mortgage", amount=D("2200.00"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=1, start_date=date(2026, 1, 1),
    )
    db.add(item)
    db.commit()
    return user, checking, item


def test_pending_fields_default_to_none(db_session):
    _, _, item = _world(db_session)
    assert item.pending_amount is None and item.pending_amount_effective_date is None


def test_create_rejects_a_half_entered_pair(client, auth_headers, test_account):
    body = {
        "name": "Half Entered", "amount": "100.00", "type": "expense", "frequency": "monthly",
        "account_id": test_account.id, "day_of_month": 1, "start_date": "2026-01-01",
        "pending_amount": "90.00",
    }
    r = client.post("/recurring", json=body, headers=auth_headers)
    assert r.status_code == 422


def test_create_accepts_a_complete_pair(client, auth_headers, test_account):
    body = {
        "name": "Complete Pair", "amount": "2200.00", "type": "expense", "frequency": "monthly",
        "account_id": test_account.id, "day_of_month": 1, "start_date": "2026-01-01",
        "pending_amount": "1950.00", "pending_amount_effective_date": "2027-01-01",
    }
    r = client.post("/recurring", json=body, headers=auth_headers)
    assert r.status_code == 201
    assert r.json()["pending_amount"] == "1950.00"
    assert r.json()["pending_amount_effective_date"] == "2027-01-01"


def test_update_rejects_a_half_entered_pair(client, auth_headers, db_session, test_user, test_account):
    item = models.RecurringItem(
        user_id=test_user.id, account_id=test_account.id, name="Test Item", amount=D("100.00"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=1, start_date=date(2026, 1, 1),
    )
    db_session.add(item)
    db_session.commit()
    r = client.patch(f"/recurring/{item.id}", json={"pending_amount": "90.00"}, headers=auth_headers)
    assert r.status_code == 422


def test_breakdown_is_unaffected_by_a_future_pending_change(client, auth_headers, db_session, test_user, test_account):
    item = models.RecurringItem(
        user_id=test_user.id, account_id=test_account.id, name="Test Mortgage", amount=D("2200.00"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=1, start_date=date(2026, 1, 1),
        pending_amount=D("1950.00"), pending_amount_effective_date=date(2027, 1, 1),
    )
    db_session.add(item)
    db_session.commit()
    r = client.get("/recurring/breakdown", headers=auth_headers)
    row = next(
        i for g in r.json()["by_category"] for i in (g["items"] or [it for c in g["categories"] for it in c["items"]])
        if i["id"] == item.id
    )
    assert row["amount"] == "2200.00"


def test_update_can_clear_a_scheduled_change(client, auth_headers, db_session, test_user, test_account):
    item = models.RecurringItem(
        user_id=test_user.id, account_id=test_account.id, name="Test Item", amount=D("100.00"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=1, start_date=date(2026, 1, 1),
        pending_amount=D("90.00"), pending_amount_effective_date=date(2027, 1, 1),
    )
    db_session.add(item)
    db_session.commit()
    r = client.patch(
        f"/recurring/{item.id}", json={"pending_amount": None, "pending_amount_effective_date": None},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["pending_amount"] is None and r.json()["pending_amount_effective_date"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run --locked python -m pytest tests/test_pending_amount_change.py -v`
Expected: FAIL -- `RecurringItem` has no attribute `pending_amount`

- [ ] **Step 3: Add the model fields and migration**

In `backend/models.py`, add to `RecurringItem` right after `contingency_paused_at`:
```python
pending_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
pending_amount_effective_date: Mapped[date | None] = mapped_column(Date)
```

In `backend/database.py`'s `upgrade_schema()`, append to the plain ALTER-TABLE string list (the same list `contingency_paused_at`'s line belongs to, not the special-cased block a few lines below it that needs a data backfill -- this needs none, since every existing row's correct default is `NULL`):
```python
"ALTER TABLE recurring_items ADD COLUMN pending_amount NUMERIC(14,2)",
"ALTER TABLE recurring_items ADD COLUMN pending_amount_effective_date DATE",
```

- [ ] **Step 4: Add the schema fields and the both-or-neither validator**

In `RecurringCreate` (`backend/schemas.py`), add `pending_amount: Optional[Decimal] = None` and `pending_amount_effective_date: Optional[date] = None`, and extend the existing `_validate_floating_scope` `model_validator(mode="after")` method (or add a second one beside it) to also raise `ValueError("pending_amount and pending_amount_effective_date must both be set or both be None")` when exactly one of the two is `None`.

In `RecurringUpdate`, add the same two optional fields (no validator here -- `RecurringUpdate` is partial, same reason `is_floating`'s cross-field check lives in the router instead of a validator).

In `RecurringOut`, add the same two fields so the API always returns them.

In `backend/routers/recurring.py`'s `update_recurring`, add a merged-state check in the same style as the existing `merged_is_floating` block just above it: compute `merged_pending_amount = updates.get("pending_amount", item.pending_amount)` and `merged_pending_amount_effective_date = updates.get("pending_amount_effective_date", item.pending_amount_effective_date)`, and raise the same `HTTPException(status_code=422, ...)` shape when exactly one is `None`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run --locked python -m pytest tests/test_pending_amount_change.py -v`
Expected: all pass

- [ ] **Step 6: Run the full backend suite**

Run: `cd backend && uv run --locked python -m pytest -q`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add backend/models.py backend/database.py backend/schemas.py backend/routers/recurring.py backend/tests/test_pending_amount_change.py
git commit -m "feat: pending_amount/pending_amount_effective_date fields on RecurringItem"
```

---

### Task 2: The forecast walk resolves the scheduled change by date

**Files:**
- Modify: `backend/services/forecast_engine.py` -- `build_forecast` (~line 1313-1314)
- Test: `backend/tests/test_pending_amount_change.py`

**Interfaces:**
- Consumes: `RecurringItem.pending_amount` / `pending_amount_effective_date` (Task 1).
- Produces: nothing new consumed elsewhere -- this is `build_forecast`'s existing output (`ForecastEntry.transactions[].amount`), just correct across the transition date.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_pending_amount_change.py -- add

from decimal import Decimal
from backend.services.forecast_engine import build_forecast


def _mortgage_world(db, pending_amount=None, effective_date=None):
    user = models.User(username="forecastpending", hashed_password="x", display_name="ForecastPending")
    db.add(user)
    db.flush()
    checking = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=D("10000.00"),
    )
    db.add(checking)
    db.flush()
    item = models.RecurringItem(
        user_id=user.id, account_id=checking.id, name="Test Mortgage", amount=D("2200.00"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=1, start_date=date(2026, 1, 1),
        pending_amount=pending_amount, pending_amount_effective_date=effective_date,
    )
    db.add(item)
    db.commit()
    return user, checking, item


def _amount_on(entries, name, on_day):
    for e in entries:
        if e.date == on_day:
            for t in e.transactions:
                if t.name == name:
                    return t.amount
    return None


def test_pre_effective_occurrence_keeps_the_old_amount(db_session):
    user, checking, _ = _mortgage_world(
        db_session, pending_amount=D("1950.00"), effective_date=date(2027, 1, 1),
    )
    entries = build_forecast(db_session, user.id, checking.id, date(2026, 12, 1), date(2026, 12, 31))
    assert _amount_on(entries, "Test Mortgage", date(2026, 12, 1)) == D("2200.00")


def test_on_and_after_effective_occurrence_uses_the_new_amount(db_session):
    user, checking, _ = _mortgage_world(
        db_session, pending_amount=D("1950.00"), effective_date=date(2027, 1, 1),
    )
    entries = build_forecast(db_session, user.id, checking.id, date(2027, 1, 1), date(2027, 1, 31))
    assert _amount_on(entries, "Test Mortgage", date(2027, 1, 1)) == D("1950.00")


def test_no_pending_amount_is_unaffected(db_session):
    user, checking, _ = _mortgage_world(db_session)
    entries = build_forecast(db_session, user.id, checking.id, date(2027, 1, 1), date(2027, 1, 31))
    assert _amount_on(entries, "Test Mortgage", date(2027, 1, 1)) == D("2200.00")


def test_a_confirmed_statement_amount_still_beats_a_pending_change(db_session):
    user, checking, item = _mortgage_world(
        db_session, pending_amount=D("1950.00"), effective_date=date(2027, 1, 1),
    )
    db_session.add(models.BillAmountOverride(
        user_id=user.id, recurring_item_id=item.id, due_date=date(2027, 1, 1), actual_amount=D("2015.42"),
    ))
    db_session.commit()
    entries = build_forecast(db_session, user.id, checking.id, date(2027, 1, 1), date(2027, 1, 31))
    assert _amount_on(entries, "Test Mortgage", date(2027, 1, 1)) == D("2015.42")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run --locked python -m pytest tests/test_pending_amount_change.py -k pending_occurrence_keeps -v`
Expected: the "before effective date" test passes already (nothing changed yet); the "on and after" test FAILS, showing `2200.00` instead of `1950.00`

- [ ] **Step 3: Resolve the base amount by date in `build_forecast`**

In `build_forecast` (~line 1313-1314), change the final `else` branch of the `base_amount` resolution (the one beneath the `actual_override`/`bonus_gross_amt` checks, which stay untouched):

```python
else:
    base = (
        item.pending_amount
        if item.pending_amount is not None and current >= item.pending_amount_effective_date
        else item.amount
    )
    base_amount = base + override_map.get(item.id, Decimal("0"))
```

`current` is this loop's existing occurrence-date variable; comparing it directly against `pending_amount_effective_date` (both `date`) handles the on-the-boundary case correctly already (`>=`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run --locked python -m pytest tests/test_pending_amount_change.py -v`
Expected: all pass

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && uv run --locked python -m pytest -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add backend/services/forecast_engine.py backend/tests/test_pending_amount_change.py
git commit -m "feat: forecast walk resolves a scheduled amount change by occurrence date"
```

---

### Task 3: Auto-clear once the effective date passes

**Files:**
- Create: `backend/services/pending_amount.py`
- Modify: `backend/main.py` -- `_scheduler_sweep()` (~line 350-410)
- Test: `backend/tests/test_pending_amount_change.py`

**Interfaces:**
- Consumes: `RecurringItem.pending_amount` / `pending_amount_effective_date` (Task 1).
- Produces: `promote_due_pending_amounts(db: Session, as_of: date) -> list[int]` -- the ids of every item it promoted, for the test and sweep log line.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_pending_amount_change.py -- add

from backend.services.pending_amount import promote_due_pending_amounts


def test_promotes_an_item_whose_date_has_arrived(db_session):
    _, _, item = _mortgage_world(db_session, pending_amount=D("1950.00"), effective_date=date(2027, 1, 1))
    ids = promote_due_pending_amounts(db_session, date(2027, 1, 1))
    db_session.refresh(item)
    assert ids == [item.id]
    assert item.amount == D("1950.00")
    assert item.pending_amount is None and item.pending_amount_effective_date is None


def test_leaves_a_not_yet_due_item_alone(db_session):
    _, _, item = _mortgage_world(db_session, pending_amount=D("1950.00"), effective_date=date(2027, 1, 1))
    ids = promote_due_pending_amounts(db_session, date(2026, 12, 31))
    db_session.refresh(item)
    assert ids == []
    assert item.amount == D("2200.00") and item.pending_amount == D("1950.00")


def test_running_it_twice_on_the_same_day_is_a_no_op_the_second_time(db_session):
    _, _, item = _mortgage_world(db_session, pending_amount=D("1950.00"), effective_date=date(2027, 1, 1))
    promote_due_pending_amounts(db_session, date(2027, 1, 1))
    ids = promote_due_pending_amounts(db_session, date(2027, 1, 1))
    assert ids == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run --locked python -m pytest tests/test_pending_amount_change.py -k promote -v`
Expected: FAIL -- `backend.services.pending_amount` doesn't exist

- [ ] **Step 3: Implement `promote_due_pending_amounts`**

```python
# backend/services/pending_amount.py
"""Promotes a scheduled amount change once its effective date arrives."""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from backend import models


def promote_due_pending_amounts(db: Session, as_of: date) -> list[int]:
    """Every RecurringItem whose pending_amount_effective_date has arrived:
    amount becomes pending_amount, and both pending fields clear. Returns the
    promoted ids. Safe to call repeatedly -- an item with nothing pending, or
    whose date hasn't arrived yet, is left untouched."""
    items = db.query(models.RecurringItem).filter(
        models.RecurringItem.pending_amount.isnot(None),
        models.RecurringItem.pending_amount_effective_date <= as_of,
    ).all()
    for item in items:
        item.amount = item.pending_amount
        item.pending_amount = None
        item.pending_amount_effective_date = None
    db.commit()
    return [item.id for item in items]
```

- [ ] **Step 4: Wire it into the scheduler sweep**

In `backend/main.py`'s `_scheduler_sweep()`, add a guarded block in the same style as the existing bonus-plan-refresh step just above the "Record once when the calculation rules change" block:

```python
try:
    from backend.services.pending_amount import promote_due_pending_amounts
    promoted = promote_due_pending_amounts(db, date.today())
    if promoted:
        logger.info("Scheduler sweep: promoted pending amount change for recurring items %s", promoted)
except Exception:
    logger.exception("Scheduler sweep: pending amount promotion step failed")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run --locked python -m pytest tests/test_pending_amount_change.py -v`
Expected: all pass

- [ ] **Step 6: Run the full backend suite and lint**

Run: `cd backend && uv run --locked python -m pytest -q && uv run --locked ruff check .`
Expected: all tests pass, ruff clean, coverage floor met

- [ ] **Step 7: Commit**

```bash
git add backend/services/pending_amount.py backend/main.py backend/tests/test_pending_amount_change.py
git commit -m "feat: auto-clear a scheduled amount change once its effective date arrives"
```

---

### Task 4: Recurring page -- enter and see a scheduled change

**Files:**
- Modify: `frontend/src/pages/Recurring.tsx` -- `emptyForm` (~line 26), `openEdit` (~line 221), submit payload (~line 225), the item form (near the existing `amount_varies` checkbox, ~line 743), `ItemRow` (~line 243-312)

**Interfaces:**
- Consumes: `pending_amount` / `pending_amount_effective_date` on each item returned by `GET /recurring` and `GET /recurring/breakdown` (Task 1).
- Produces: nothing consumed by another task.

- [ ] **Step 1: Add the fields to the form state**

Add `pending_amount: "", pending_amount_effective_date: ""` to `emptyForm`. In `openEdit`, prefill them from the item (`pending_amount: i.pending_amount != null ? String(i.pending_amount) : "", pending_amount_effective_date: i.pending_amount_effective_date ?? ""`). In the submit payload builder, send `pending_amount: form.pending_amount ? parseFloat(form.pending_amount) : null, pending_amount_effective_date: form.pending_amount_effective_date || null`.

- [ ] **Step 2: Add the two inputs to the item form**

Near the existing "amount varies" checkbox (~line 743), add a labeled pair of inputs -- a number input bound to `form.pending_amount` (placeholder e.g. "New amount") and a date input bound to `form.pending_amount_effective_date` (label e.g. "starting on"), styled consistently with the surrounding `statement_day`/`amount_varies` inputs in this same form section. No client-side validation beyond what the browser's own `type="number"`/`type="date"` already give -- the both-or-neither rule is enforced server-side (Task 1); leaving one filled and submitting lets the existing 422 surface through whatever error-display this form already uses for a failed save.

- [ ] **Step 3: Show a badge on the item row when a change is scheduled**

In `ItemRow`, add a badge next to the existing `end_date` badge (~line 286-292), shown when `item.pending_amount != null`: `<span className="badge-amber" title={...}>→ {fmt(item.pending_amount)} on {item.pending_amount_effective_date}</span>` (format the date the same way `endMonthLabel`/the surrounding badges already format dates in this file, reusing an existing helper rather than inventing a new date format).

- [ ] **Step 4: Run frontend checks**

Run: `cd frontend && bun test && bunx vite build`
Expected: all pass, build succeeds

- [ ] **Step 5: Live-verify via Interceptor**

Open the Recurring page, edit an existing expense item, enter a pending amount and a future date, save, and confirm: the badge appears on that item's row; reopening the edit form shows the same values prefilled; clearing both fields and saving removes the badge.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/Recurring.tsx
git commit -m "feat: enter and display a scheduled future amount change on the Recurring page"
```
