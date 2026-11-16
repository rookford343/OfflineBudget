# Floating Recurring Expenses & Skip-This-Month Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a recurring expense be marked "floating" (budgeted monthly, no fixed date) so the real charge auto-matches wherever it lands in the month, on checking or a credit card, and let a floating month be explicitly skipped without deactivating the item.

**Architecture:** Add `is_floating` to `RecurringItem` and widen the existing checking-side matcher's date window for floating items from ±7 days to "anywhere this calendar month." Build an equivalent matcher for credit-card transactions from scratch (none exists today) and a new `recurring_item_id` link on `CreditCardTransaction`. Add a `RecurringSkip` table consulted by both `month_base.py` and `forecast_engine.py` wherever they currently ask "does this item fire this month." Add a status endpoint so the Recurring page can show Matched/Pending/Skipped per floating item for the viewed month.

**Tech Stack:** FastAPI + SQLAlchemy + SQLite (backend), React + TypeScript + TanStack Query (frontend). `uv` for Python, `bun` for JS.

**Spec:** `docs/superpowers/specs/2026-11-15-floating-recurring-expenses-design.md`

## Global Constraints

- No real balances/amounts/dates/merchant names anywhere in commits, test fixtures, or this plan — invented placeholders only.
- Backend: `uv run --locked`; ruff (Bandit `S` + Pyflakes `F`) clean; coverage floor in `backend/.coveragerc` never lowered.
- Frontend: `bun`; `bunx vite build`; no client-side money arithmetic (`frontend/tests/moneyGuard.test.ts` must stay green) — any variance/diff display is a server-computed field, read as-is.
- New columns on existing tables go in `backend/database.py`'s `upgrade_schema()` list (`ALTER TABLE ... ADD COLUMN`, wrapped in the existing try/commit/rollback-on-exists loop). Brand-new tables need no entry there — declaring the SQLAlchemy model is enough; `create_tables()`'s `Base.metadata.create_all` creates them.
- A match always wins over a skip (design doc §3 "My call"): if a transaction later links to an item for a month that already has a `RecurringSkip` row, the match overrides it — the skip row is deleted and status shows Matched.
- The floating-window fix is forward-looking only (confirmed with Dan) — no backfill/rematch of transactions already imported before `is_floating` was set.
- Scope is monthly floating items only. Quarterly/yearly floating matching is explicitly out of scope (future work per the design doc).
- Live UI changes verified via Interceptor before calling the work done.
- Commits go directly to `main` — no feature branches for this repo.

## Review Focus

- **A `RecurringSkip` honored in `month_base.py` but not `forecast_engine.py` (or the reverse).** This repo has a known failure mode (logged in project memory) of the Dashboard, Forecast tab, and Month-in-Review disagreeing on the same number because one code path updates and a sibling path doesn't. Task 3's tests must prove both paths agree for the same skipped `(item, year, month)`.
- **A floating item's actual transaction landing outside the old ±7-day window.** This is the concrete bug motivating the whole plan (House Cleaning's real charge missed the match). Task 2's test must use a transaction date the *old* window would have rejected and prove the new one accepts it.
- **A non-floating item must not change behavior.** Every existing matching/forecast test for a non-floating item must keep passing unmodified — floating is strictly opt-in per item.
- **A card-side match retroactively touching a transaction that predates the item being marked floating.** Per the forward-looking-only constraint, the card matcher must only ever see transactions created *after* this code ships; no backfill job exists to go find older ones, but a reasonable person would still expect the matcher to never reach into transactions from before the item existed at all (its `start_date`). Task 4's matcher must respect `start_date` the same way the checking-side one already does via `_fires_on`.
- **A skip row surviving a later match should not leave two contradictory truths visible.** Task 3 clears the stale skip row the moment a match lands (per the Global Constraints "match always wins" rule) rather than leaving both a skip row and a linked transaction in the database simultaneously.

---

### Task 1: Data model — `is_floating`, `RecurringSkip`, card-side linkage column

**Files:**
- Modify: `backend/models.py` (`RecurringItem` class at line ~288; `CreditCardTransaction` class at line ~536; add new `RecurringSkip` class near `BillAmountOverride`, line ~738)
- Modify: `backend/database.py` (`upgrade_schema()`'s `stmts` list, line ~113)
- Modify: `backend/schemas.py` (`RecurringCreate` line ~304, `RecurringUpdate` line ~337, `RecurringOut` line ~363)
- Test: `backend/tests/test_models_floating.py` (new)

**Interfaces:**
- Produces: `models.RecurringItem.is_floating: bool` (default `False`); `models.CreditCardTransaction.recurring_item_id: int | None`; new model `models.RecurringSkip` with columns `id`, `user_id`, `recurring_item_id`, `year: int`, `month: int`, `created_at`, unique on `(recurring_item_id, year, month)`. `schemas.RecurringCreate.is_floating: bool = False`, `schemas.RecurringUpdate.is_floating: Optional[bool] = None`, `schemas.RecurringOut.is_floating: bool = False`.
- Consumes: nothing from other tasks (this is the foundation task).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_models_floating.py
def test_recurring_item_is_floating_defaults_false(db_session, test_user, test_account):
    item = models.RecurringItem(
        user_id=test_user.id, account_id=test_account.id, name="Test Floating Co",
        amount=Decimal("45.00"), type=models.RecurringType.expense,
        day_of_month=15, start_date=date(2026, 1, 1),
    )
    db_session.add(item)
    db_session.commit()
    assert item.is_floating is False

def test_recurring_skip_unique_per_item_month(db_session, test_user, test_account):
    item = models.RecurringItem(
        user_id=test_user.id, account_id=test_account.id, name="Test Floating Co",
        amount=Decimal("45.00"), type=models.RecurringType.expense,
        day_of_month=15, start_date=date(2026, 1, 1), is_floating=True,
    )
    db_session.add(item)
    db_session.commit()
    db_session.add(models.RecurringSkip(user_id=test_user.id, recurring_item_id=item.id, year=2026, month=12))
    db_session.commit()
    db_session.add(models.RecurringSkip(user_id=test_user.id, recurring_item_id=item.id, year=2026, month=12))
    with pytest.raises(Exception):
        db_session.commit()
    db_session.rollback()

def test_credit_card_transaction_recurring_item_id(db_session, test_user, test_card):
    ct = models.CreditCardTransaction(
        card_id=test_card.id, user_id=test_user.id, date=date(2026, 11, 14),
        amount=Decimal("45.00"), merchant="Test Barbers",
    )
    db_session.add(ct)
    db_session.commit()
    assert ct.recurring_item_id is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run --locked python -m pytest tests/test_models_floating.py -v`
Expected: FAIL — `is_floating`/`recurring_item_id`/`RecurringSkip` don't exist yet.

- [ ] **Step 3: Add the columns and table**

In `backend/models.py`:
- `RecurringItem`: add `is_floating: Mapped[bool] = mapped_column(Boolean, default=False)` near `amount_varies` (line ~327). One short comment: when true, the checking/card matchers (Task 2/4) accept the real transaction anywhere in the item's due month instead of requiring it near `day_of_month`.
- `CreditCardTransaction`: add `recurring_item_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("recurring_items.id"))` near `category_id` (line ~542).
- New class `RecurringSkip(Base)`, `__tablename__ = "recurring_skips"`, placed near `BillAmountOverride`: `id` (PK), `user_id` (FK users, not null), `recurring_item_id` (FK recurring_items, not null), `year: Mapped[int]`, `month: Mapped[int]`, `created_at` (DateTime, server_default now). `__table_args__ = (UniqueConstraint("recurring_item_id", "year", "month"),)`.

In `backend/database.py`'s `upgrade_schema()` `stmts` list, append (new columns on existing tables only — `RecurringSkip` is a brand-new table, no entry needed):
```python
"ALTER TABLE recurring_items ADD COLUMN is_floating BOOLEAN DEFAULT 0",
"ALTER TABLE credit_card_transactions ADD COLUMN recurring_item_id INTEGER REFERENCES recurring_items(id)",
```

In `backend/schemas.py`, add `is_floating: bool = False` to `RecurringCreate` (after `statement_day`), `is_floating: Optional[bool] = None` to `RecurringUpdate` (after `amount_varies`), and `is_floating: bool = False` to `RecurringOut` (after `amount_varies`).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run --locked python -m pytest tests/test_models_floating.py -v`
Expected: PASS

- [ ] **Step 5: Run the full backend suite to confirm nothing regressed**

Run: `cd backend && uv run --locked python -m pytest -q`
Expected: all pass (same count as before this task, plus the 3 new tests)

- [ ] **Step 6: Commit**

```bash
git add backend/models.py backend/database.py backend/schemas.py backend/tests/test_models_floating.py
git commit -m "feat: add is_floating, RecurringSkip, and card-side recurring_item_id"
```

---

### Task 2: Checking-side floating match — widen the date window

**Files:**
- Modify: `backend/services/import_service.py` (`_best_recurring_match`, lines ~82-130)
- Test: `backend/tests/test_import_service_floating_match.py` (new)

**Interfaces:**
- Consumes: `models.RecurringItem.is_floating` (Task 1).
- Produces: nothing new consumed elsewhere — this task only changes `_best_recurring_match`'s internal date check; its signature is unchanged.

- [ ] **Step 1: Write the failing test**

Use an item with `is_floating=True`, `frequency=monthly`, `day_of_month=0` (last day), and a transaction dated the 12th of that same month — 19 days before the last day of a 31-day month, well outside the existing ±7-day window. Assert the match succeeds. Also assert a non-floating item with the same shape still requires the window (regression guard).

```python
# backend/tests/test_import_service_floating_match.py
from backend.services.import_service import _best_recurring_match

def test_floating_item_matches_anywhere_in_month():
    item = models.RecurringItem(
        id=1, user_id=1, account_id=1, name="Test Cleaning Co",
        amount=Decimal("150.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=0,
        start_date=date(2026, 1, 1), is_floating=True, card_id=None,
    )
    match = _best_recurring_match(
        [item], description="TEST CLEANING CO DEBIT", amount=Decimal("-150.00"),
        on=date(2026, 11, 12), confirmed_amounts={}, payee_history={},
    )
    assert match is item

def test_non_floating_item_still_requires_window():
    item = models.RecurringItem(
        id=1, user_id=1, account_id=1, name="Test Cleaning Co",
        amount=Decimal("150.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=0,
        start_date=date(2026, 1, 1), is_floating=False, card_id=None,
    )
    match = _best_recurring_match(
        [item], description="TEST CLEANING CO DEBIT", amount=Decimal("-150.00"),
        on=date(2026, 11, 12), confirmed_amounts={}, payee_history={},
    )
    assert match is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run --locked python -m pytest tests/test_import_service_floating_match.py -v`
Expected: the first test FAILs (returns `None`); the second PASSes already.

- [ ] **Step 3: Widen the window for floating items in `_best_recurring_match`**

In `backend/services/import_service.py`, the existing date check (around line 121-123):
```python
window = _MATCH_WINDOW_DAYS if name_hits else 3
if not any(_fires_on(item, on + timedelta(days=k)) for k in range(-window, window + 1)):
    continue
```
becomes: when `item.is_floating`, skip straight to checking whether the item is due *this calendar month* at all (reuse `_fires_on` across every day of `on`'s month, or equivalently check the item's frequency/start/end against `on`'s month the same way `month_base._fires_on`/`forecast_engine._fires_on` already determine monthly-ness) instead of the `±window` day check. Name/history evidence (`name_hits or history_hits`, already checked above this block) and the amount tolerance (`lo <= amount / t <= hi`, below this block) are untouched — they still gate a floating match, which is what keeps a wrong merchant from matching once the date window is gone. Scope to monthly frequency only, per Global Constraints.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run --locked python -m pytest tests/test_import_service_floating_match.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && uv run --locked python -m pytest -q`
Expected: all pass, no regressions in existing `test_import_service*` tests

- [ ] **Step 6: Commit**

```bash
git add backend/services/import_service.py backend/tests/test_import_service_floating_match.py
git commit -m "feat: widen checking-side match window to whole-month for floating items"
```

---

### Task 3: Skip-this-month

**Files:**
- Modify: `backend/services/month_base.py` (`build_month_base`, lines ~172-232)
- Modify: `backend/services/forecast_engine.py` (the day-walk around lines ~1215-1260)
- Modify: `backend/routers/recurring.py` (add skip/unskip endpoints)
- Modify: `backend/schemas.py` (add `RecurringSkipCreate`/`RecurringSkipOut` if needed for the endpoint bodies)
- Test: `backend/tests/test_month_base_skip.py` (new), `backend/tests/test_forecast_engine_skip.py` (new), `backend/tests/test_recurring_router_skip.py` (new)

**Interfaces:**
- Consumes: `models.RecurringSkip` (Task 1).
- Produces: `POST /recurring/{item_id}/skip` (body `{year: int, month: int}`, 201, idempotent — creating an existing skip is a no-op, not an error) and `DELETE /recurring/{item_id}/skip` (body or query `{year, month}`, 204) for Task 5 (status display) and the frontend to call.

- [ ] **Step 1: Write the failing test for `build_month_base`**

```python
# backend/tests/test_month_base_skip.py
def test_skipped_item_excluded_from_monthly_bills(db_session, test_user, test_account):
    item = models.RecurringItem(
        user_id=test_user.id, account_id=test_account.id, name="Test Cleaning Co",
        amount=Decimal("150.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=0,
        start_date=date(2026, 1, 1), is_floating=True,
    )
    db_session.add(item)
    db_session.commit()
    db_session.add(models.RecurringSkip(user_id=test_user.id, recurring_item_id=item.id, year=2026, month=11))
    db_session.commit()

    base = build_month_base(db_session, test_user, 2026, 11)
    assert all(o.recurring_item_id != item.id for o in base.monthly_bills)

    base_other_month = build_month_base(db_session, test_user, 2026, 12)
    assert any(o.recurring_item_id == item.id for o in base_other_month.monthly_bills)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run --locked python -m pytest tests/test_month_base_skip.py -v`
Expected: FAIL — the skipped item still appears in November's `monthly_bills`.

- [ ] **Step 3: Honor `RecurringSkip` in `build_month_base`**

In `backend/services/month_base.py`, query `RecurringSkip` for this `(user, year, month)` the same way `overrides` is built from `BillAmountOverride` (lines 196-203) — a `{recurring_item_id}` set — and skip appending an occurrence for any item in that set, inside the existing `for item in items: for d in days:` loop (line ~209-232), right after `if not _fires_on(item, d): continue`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run --locked python -m pytest tests/test_month_base_skip.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing test for `forecast_engine`**

```python
# backend/tests/test_forecast_engine_skip.py
def test_skipped_item_not_projected_in_forecast(db_session, test_user, test_account):
    item = models.RecurringItem(
        user_id=test_user.id, account_id=test_account.id, name="Test Cleaning Co",
        amount=Decimal("150.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=0,
        start_date=date(2026, 1, 1), is_floating=True,
    )
    db_session.add(item)
    db_session.commit()
    db_session.add(models.RecurringSkip(user_id=test_user.id, recurring_item_id=item.id, year=2026, month=11))
    db_session.commit()

    entries = build_forecast(db_session, test_user.id, test_account.id, date(2026, 11, 1), date(2026, 11, 30))
    assert not any(
        t.recurring_item_id == item.id
        for e in entries for t in e.transactions
    )
```

(Adjust the call signature/return shape to whatever `build_forecast` actually exposes — check the existing tests in `backend/tests/test_forecast_engine*.py` for the real call pattern and mirror it exactly.)

- [ ] **Step 6: Run test to verify it fails, then wire the skip check into the day-walk**

In `backend/services/forecast_engine.py`, around lines 1215-1260 (the `for item in recurring_items: natural_fires = _fires_on(item, current)` loop), build a `skipped_by_ri: dict[int, set[tuple[int,int]]]` or simply a `{(recurring_item_id, year, month)}` set from `RecurringSkip` for the query's date range, alongside the existing `actual_by_ri`/`bill_actuals` maps built earlier in the same function (around line 1184). Skip the item for `current` when `(item.id, current.year, current.month)` is in that set — add this check next to the existing `if not fires_projected: continue` / `if item.id in adj_actual_recurring_ids: continue` guards (lines 1255-1258), before the amount/entry is built.

Run: `cd backend && uv run --locked python -m pytest tests/test_forecast_engine_skip.py -v`
Expected: PASS

- [ ] **Step 7: Write the failing test for the skip/unskip endpoints**

```python
# backend/tests/test_recurring_router_skip.py
def test_skip_then_unskip(client, auth_headers, test_recurring_item):
    r = client.post(f"/recurring/{test_recurring_item.id}/skip", json={"year": 2026, "month": 11}, headers=auth_headers)
    assert r.status_code == 201

    # idempotent
    r2 = client.post(f"/recurring/{test_recurring_item.id}/skip", json={"year": 2026, "month": 11}, headers=auth_headers)
    assert r2.status_code == 201

    r3 = client.delete(f"/recurring/{test_recurring_item.id}/skip", params={"year": 2026, "month": 11}, headers=auth_headers)
    assert r3.status_code == 204
```

- [ ] **Step 8: Run test to verify it fails, then add the endpoints**

In `backend/schemas.py`, add `RecurringSkipBody(BaseModel): year: int; month: int`.

In `backend/routers/recurring.py`, near `link_pattern_to_item` (line ~397):
```python
@router.post("/{item_id}/skip", status_code=status.HTTP_201_CREATED)
def skip_month(item_id: int, body: schemas.RecurringSkipBody, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    item = _get_or_404(db, user.id, item_id)
    existing = db.query(models.RecurringSkip).filter(
        models.RecurringSkip.recurring_item_id == item.id,
        models.RecurringSkip.year == body.year, models.RecurringSkip.month == body.month,
    ).first()
    if not existing:
        db.add(models.RecurringSkip(user_id=user.id, recurring_item_id=item.id, year=body.year, month=body.month))
        db.commit()
    return {"ok": True}


@router.delete("/{item_id}/skip", status_code=status.HTTP_204_NO_CONTENT)
def unskip_month(item_id: int, year: int, month: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    item = _get_or_404(db, user.id, item_id)
    db.query(models.RecurringSkip).filter(
        models.RecurringSkip.recurring_item_id == item.id,
        models.RecurringSkip.year == year, models.RecurringSkip.month == month,
    ).delete()
    db.commit()
```

Run: `cd backend && uv run --locked python -m pytest tests/test_recurring_router_skip.py -v`
Expected: PASS

- [ ] **Step 9: Run the full backend suite**

Run: `cd backend && uv run --locked python -m pytest -q`
Expected: all pass

- [ ] **Step 10: Commit**

```bash
git add backend/services/month_base.py backend/services/forecast_engine.py backend/routers/recurring.py backend/schemas.py backend/tests/test_month_base_skip.py backend/tests/test_forecast_engine_skip.py backend/tests/test_recurring_router_skip.py
git commit -m "feat: skip-this-month for recurring items"
```

---

### Task 4: Card-side matching and linkage

**Files:**
- Create: `backend/services/card_recurring_match.py`
- Modify: `backend/services/import_service.py` (`build_preview` signature + card branch of `run_import`, lines ~167 and ~553-589)
- Modify: `backend/services/bank_sync_service.py` (its `build_preview` call site, line ~382, and wherever it then calls `run_import` for card rows)
- Modify: `backend/services/plaid_sync_service.py` (its `build_preview` call site, line ~224, same)
- Test: `backend/tests/test_card_recurring_match.py` (new)

**Interfaces:**
- Consumes: `models.CreditCardTransaction.recurring_item_id` and `models.RecurringItem.is_floating` (Task 1).
- Produces: `card_recurring_match.best_card_recurring_match(candidates: list[models.RecurringItem], description: str, amount: Decimal, on: date, confirmed_amounts: dict[int, list[Decimal]], payee_history: dict[int, set[str]]) -> models.RecurringItem | None` — same contract as `import_service._best_recurring_match`, but `candidates` are filtered to `item.card_id is not None` instead of `is None`, and only `item.is_floating` items are matched this round (non-floating card expenses stay out of scope, per the design doc).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_card_recurring_match.py
from backend.services.card_recurring_match import best_card_recurring_match

def test_floating_card_item_matches_anywhere_in_month():
    item = models.RecurringItem(
        id=1, user_id=1, account_id=1, card_id=7, name="Test Barbers",
        amount=Decimal("45.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=15,
        start_date=date(2026, 1, 1), is_floating=True,
    )
    match = best_card_recurring_match(
        [item], description="TEST BARBERS #42", amount=Decimal("45.00"),
        on=date(2026, 11, 3), confirmed_amounts={}, payee_history={},
    )
    assert match is item

def test_non_floating_card_item_never_matched():
    item = models.RecurringItem(
        id=1, user_id=1, account_id=1, card_id=7, name="Test Barbers",
        amount=Decimal("45.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=15,
        start_date=date(2026, 1, 1), is_floating=False,
    )
    match = best_card_recurring_match(
        [item], description="TEST BARBERS #42", amount=Decimal("45.00"),
        on=date(2026, 11, 3), confirmed_amounts={}, payee_history={},
    )
    assert match is None

def test_checking_only_item_never_matched_on_card_side():
    item = models.RecurringItem(
        id=1, user_id=1, account_id=1, card_id=None, name="Test Cleaning Co",
        amount=Decimal("150.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=0,
        start_date=date(2026, 1, 1), is_floating=True,
    )
    match = best_card_recurring_match(
        [item], description="TEST CLEANING CO", amount=Decimal("150.00"),
        on=date(2026, 11, 3), confirmed_amounts={}, payee_history={},
    )
    assert match is None

def test_predates_start_date_never_matched():
    item = models.RecurringItem(
        id=1, user_id=1, account_id=1, card_id=7, name="Test Barbers",
        amount=Decimal("45.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=15,
        start_date=date(2026, 12, 1), is_floating=True,
    )
    match = best_card_recurring_match(
        [item], description="TEST BARBERS #42", amount=Decimal("45.00"),
        on=date(2026, 11, 3), confirmed_amounts={}, payee_history={},
    )
    assert match is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run --locked python -m pytest tests/test_card_recurring_match.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement `card_recurring_match.py`**

Mirror `import_service._best_recurring_match` (lines ~82-130): reuse `import_service._evidence_tokens` and `import_service._name_score` (import them rather than duplicating), keep the same amount-tolerance constant (`import_service._AMOUNT_RATIO`), same name/history evidence gate, same `_fires_on` + `start_date`/`end_date` check for "due this item's month" (this review focus item from the plan header: respect `start_date`). Candidate filter: `item.card_id is not None and item.is_floating and item.amount > 0`. No `±window` day check at all — floating-only, so it's always whole-month. Flag in a code comment that the amount tolerance is carried over unexamined from the checking-side constant per the design doc's open flag; not a defect to fix in this task.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run --locked python -m pytest tests/test_card_recurring_match.py -v`
Expected: PASS

- [ ] **Step 5: Wire the matcher into `build_preview` and `run_import`**

In `backend/services/import_service.py`:
- Add `card_id: int | None = None` parameter to `build_preview` (signature at line ~167). When `card_id is not None`, build the card-side matcher pool from `all_recurring` filtered to `card_id == card_id` instead of calling `_best_suggestion(expense_recurring + cc_payment_recurring, row)`; call `best_card_recurring_match` instead of `_best_recurring_match` for the suggestion.
- In `run_import`'s card branch (lines ~553-589), set `recurring_item_id=row.recurring_item_id` on the new `CreditCardTransaction` the same way the checking branch already does (line 477), and when `not row.recurring_item_id`, call a new `_try_auto_match_card(ct, db)` helper (mirrors `_try_auto_match`, lines 151-164, but candidates filtered to `card_id == ct.card_id` and matched via `best_card_recurring_match`).

- [ ] **Step 6: Thread `card_id` through every `build_preview` call site that already knows it**

`backend/routers/imports.py:46` already has `card_id` in scope (the endpoint's own parameter) — pass it through. `backend/services/bank_sync_service.py:382` and `backend/services/plaid_sync_service.py:224` each already iterate per linked account/card in their own sync loop — locate the card_id each already holds there and pass it through too. Each of these three call sites either has an `account_id` (checking) or a `card_id` (card) for the batch being previewed, never both — pass whichever one it has.

- [ ] **Step 7: Run the full backend suite**

Run: `cd backend && uv run --locked python -m pytest -q`
Expected: all pass, no regressions in existing `test_import_service*`, `test_bank_sync*`, `test_plaid_sync*` tests

- [ ] **Step 8: Commit**

```bash
git add backend/services/card_recurring_match.py backend/services/import_service.py backend/services/bank_sync_service.py backend/services/plaid_sync_service.py backend/tests/test_card_recurring_match.py
git commit -m "feat: card-side recurring-item matching for floating expenses"
```

---

### Task 5: Status endpoint, Recurring page UI, House Cleaning + Haircut setup

**Files:**
- Modify: `backend/schemas.py` (new `RecurringFloatingStatus` schema)
- Modify: `backend/routers/recurring.py` (new `GET /recurring/floating-status` endpoint)
- Modify: `frontend/src/pages/Recurring.tsx` (floating checkbox in the item form, line ~24 `emptyForm` / line ~145-150 `openNew`/`openEdit`/submit handler; skip toggle + status display in `ItemRow`, lines ~158-184)
- Modify: `frontend/src/api.ts` (or wherever `recurringApi` is defined — add `skipMonth`/`unskipMonth`/`floatingStatus` calls)
- Test: `backend/tests/test_recurring_floating_status.py` (new)

**Interfaces:**
- Consumes: `RecurringSkip` CRUD (Task 3), `is_floating` (Task 1), `CreditCardTransaction.recurring_item_id` + checking `Transaction.recurring_item_id` (Tasks 2/4).
- Produces: `GET /recurring/floating-status?year=&month=` → `list[RecurringFloatingStatus]`, one row per active floating item, with `recurring_item_id: int`, `status: Literal["matched","pending","skipped"]`, `matched_date: date | None`, `matched_amount: Decimal | None`, `variance: Decimal | None` (= `matched_amount - item.amount`, server-computed).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_recurring_floating_status.py
def test_pending_when_no_skip_or_match(db_session, test_user, test_account):
    item = models.RecurringItem(
        user_id=test_user.id, account_id=test_account.id, name="Test Cleaning Co",
        amount=Decimal("150.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=0,
        start_date=date(2026, 1, 1), is_floating=True,
    )
    db_session.add(item)
    db_session.commit()
    out = build_floating_status(db_session, test_user.id, 2026, 11)
    assert out[0].status == "pending"

def test_skipped_when_skip_row_exists(db_session, test_user, test_account):
    # ... create item + RecurringSkip for (2026, 11) ...
    out = build_floating_status(db_session, test_user.id, 2026, 11)
    assert out[0].status == "skipped"

def test_matched_wins_over_skip(db_session, test_user, test_account):
    # create item, RecurringSkip for (2026, 11), AND a Transaction linked via recurring_item_id dated in November
    out = build_floating_status(db_session, test_user.id, 2026, 11)
    assert out[0].status == "matched"
    assert out[0].matched_date is not None

    # the stale skip row is gone
    remaining = db_session.query(models.RecurringSkip).filter_by(recurring_item_id=item.id).count()
    assert remaining == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run --locked python -m pytest tests/test_recurring_floating_status.py -v`
Expected: FAIL — `build_floating_status` doesn't exist.

- [ ] **Step 3: Implement `build_floating_status(db, user_id, year, month) -> list[schemas.RecurringFloatingStatus]`**

Add to `backend/routers/recurring.py` (or a new `backend/services/recurring_floating_status.py` if the router file is getting long — follow whichever the codebase's existing file-size pattern favors; check `wc -l backend/routers/recurring.py` first). For each active floating `RecurringItem`: look for a linked `Transaction` (checking items) or `CreditCardTransaction` (card items) with `recurring_item_id == item.id` and a date in `(year, month)`. If found: status "matched", clear any `RecurringSkip` row for this `(item, year, month)` (match wins, per Global Constraints), return the linked date/amount/variance. Else if a `RecurringSkip` row exists for `(item, year, month)`: status "skipped". Else: status "pending".

Add `GET /recurring/floating-status` to `backend/routers/recurring.py`, same param validation pattern as `get_month_summary` (year/month range checks, lines ~343-346).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run --locked python -m pytest tests/test_recurring_floating_status.py -v`
Expected: PASS

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && uv run --locked python -m pytest -q`
Expected: all pass

- [ ] **Step 6: Frontend — floating checkbox, skip toggle, status display**

In `frontend/src/pages/Recurring.tsx`: add `is_floating` to `emptyForm` (line ~24) and to the `openEdit`/submit payload (lines ~146, ~150), with a checkbox in the item form near the `day_of_month` input (line ~553) labeled "Floating (date varies — matches anywhere in the month)". Fetch `GET /recurring/floating-status` for the month `RecurringSummaryStrip` is currently showing (it already tracks `year`/`month` state, line ~39-40 of `RecurringSummaryStrip.tsx` — lift that state up or fetch independently keyed on the same month, whichever fits the existing component boundary better). For each floating item's row (inside `ItemRow`, lines ~158-184), render: a "Skip this month" toggle button (calls the new skip/unskip endpoints, invalidates the status query on success) and the status text — "Matched: $X on <date> (variance $Y)" / "Pending — expected this month" / "Skipped this month" — scoped to floating items only, per the design doc's §3.

- [ ] **Step 7: Run frontend checks**

Run: `cd frontend && bun test && bunx vite build`
Expected: all pass, build succeeds, `moneyGuard.test.ts` still green (variance is read as a field from the API response, never computed client-side)

- [ ] **Step 8: Live-verify via Interceptor**

Open the Recurring page, confirm: the floating checkbox appears and persists on save; toggling skip shows "Skipped this month" immediately; the status text matches what the backend reports for the current month. Required before this task is called done (per OPERATIONAL_RULES and this plan's Global Constraints).

- [ ] **Step 9: Set up House Cleaning (floating) and Dan's Haircut (new, floating)**

Through the running app's UI (not a script, not a direct DB write): edit the existing House Cleaning recurring item to check "Floating." Create a new recurring item: name "Haircut", type expense, amount $45.00, frequency monthly, card = Dan's credit card, floating checked, day_of_month any reasonable placeholder (e.g. 15), category = whichever existing category fits (ask Dan if none obviously fits — this is explicitly left to the builder's judgment per the design doc, but the category choice itself, if ambiguous, is Dan's to confirm).

- [ ] **Step 10: Commit**

```bash
git add backend/schemas.py backend/routers/recurring.py backend/tests/test_recurring_floating_status.py frontend/src/pages/Recurring.tsx frontend/src/api.ts
git commit -m "feat: floating-expense status display, skip toggle, and setup for House Cleaning + Haircut"
```
