# Contingency Planning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dedicated "Contingency Planning" page showing a 3-month essential-expense floor against the emergency-fund balance, plus an essential/non-essential flag per recurring item and a manually-confirmed "paused" tracker for non-essential items.

**Architecture:** Two new nullable/defaulted columns on `RecurringItem` (`is_essential`, `contingency_paused_at`), one new backend endpoint reusing existing amortization/exclusion/budget-override machinery, and one new frontend page plus a new form checkbox on the existing Recurring item form.

**Tech Stack:** FastAPI + SQLAlchemy + SQLite (backend), React + TypeScript + TanStack Query (frontend). `uv` for Python, `bun` for JS.

**Spec:** `docs/superpowers/specs/2026-11-16-contingency-planning-design.md`

## Global Constraints

- No real names, balances, or amounts in commits or test fixtures — invented placeholders only.
- Backend: `uv run --locked`; ruff clean; coverage floor never lowered.
- Frontend: `bun`; `bunx vite build`; no new client-side money arithmetic — the page only renders server-returned figures.
- `is_essential`/`contingency_paused_at` are new columns on an existing table (`recurring_items`) — each needs its own `upgrade_schema()` `ALTER TABLE` entry.
- The 6-month figure is explicitly out of scope — nowhere in this plan computes or displays it.
- No automated pause/cancel action anywhere — `contingency_paused_at` is only ever set by a human-initiated checkbox click, never inferred from anything else happening in the app.
- Commits go directly to `main` — no feature branches for this repo.
- Live UI changes verified via Interceptor before calling the work done.

## Review Focus

- **Groceries category missing or renamed.** `budget_allocation_total()` returning nothing for "Groceries" must resolve the floor's grocery component to `$0`, not raise or 500 — the spec's silence on a missing category isn't permission to crash a financial figure Dan is relying on.
- **An essential item must never appear in the cut list, regardless of cost.** The cut list is a hard filter on `is_essential == False`, not a sort order — a $4,404 mortgage tagged essential must never show up next to the $25 items Dan actually intends to cut.
- **Pausing an essential item must be rejected.** `POST /{item_id}/contingency-pause` on an `is_essential=True` item should 400, the same shape as the existing skip endpoint's floating-only guard — "paused" only makes sense for something already flagged as something Dan can live without.
- **Deactivating a previously-essential item must drop it from both the floor and the cut list immediately.** `is_active=False` items are excluded from the floor calculation AND would never have appeared in the cut list in the first place (both are expense-type-only), so this is really: don't let a stale soft-deleted item silently inflate the floor.
- **Cross-user scoping.** The emergency-fund balance, the groceries figure, and the cut list must never read another user's accounts, budget rows, or recurring items — the floating-expenses and owner-tags plans each shipped with a real cross-user bug the first time around; this plan pins the scoping down in the task's own tests from the start instead of finding it in a later review.

---

### Task 1: Data model — `is_essential`, `contingency_paused_at`, migration, schemas

**Files:**
- Modify: `backend/models.py` (`RecurringItem`, near `owner_id`/`is_floating`, ~line 294-300)
- Modify: `backend/database.py` (`upgrade_schema()`)
- Modify: `backend/schemas.py` (`RecurringCreate`, `RecurringUpdate`, `RecurringOut`, `CategoryOut`)
- Test: `backend/tests/test_models_contingency.py` (new)

**Interfaces:**
- Produces: `models.RecurringItem.is_essential: bool` (default `True`), `models.RecurringItem.contingency_paused_at: datetime | None` (default `None`). `schemas.RecurringCreate.is_essential: bool = True`, `RecurringUpdate.is_essential: Optional[bool] = None`, `RecurringOut.is_essential: bool = True`. `schemas.CategoryOut.is_discretionary: bool = False`.
- Consumes: nothing from other tasks.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_models_contingency.py
from datetime import date
from decimal import Decimal
from backend import models

def test_new_item_defaults_essential_true(db_session, test_user, test_account):
    item = models.RecurringItem(
        user_id=test_user.id, account_id=test_account.id, name="Test Item",
        amount=Decimal("45.00"), type=models.RecurringType.expense,
        day_of_month=15, start_date=date(2026, 1, 1),
    )
    db_session.add(item)
    db_session.commit()
    assert item.is_essential is True
    assert item.contingency_paused_at is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run --locked python -m pytest tests/test_models_contingency.py -v`
Expected: FAIL — `is_essential` / `contingency_paused_at` don't exist.

- [ ] **Step 3: Add the columns**

In `backend/models.py`'s `RecurringItem` (near `owner_id`, ~line 294): add
`is_essential: Mapped[bool] = mapped_column(Boolean, default=True)` and
`contingency_paused_at: Mapped[datetime | None] = mapped_column(DateTime)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run --locked python -m pytest tests/test_models_contingency.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing migration-backfill test**

`upgrade_schema()` runs against the module-level `backend.database.engine`
global, which in this app defaults to the REAL `data/budget.db` file
(`config.py`'s `DATABASE_URL` default) — it is NOT the same engine as the
`db_session` fixture's isolated in-memory database. Calling
`upgrade_schema()` directly in a test without swapping that global first
would run `ALTER`/`UPDATE` statements against Dan's real production
database as a side effect of running `pytest`. There is already a safe,
established pattern for this exact situation in
`backend/tests/test_plaid_schema.py::test_upgrade_schema_adds_plaid_columns`
— `monkeypatch.setattr(database_module, "engine", test_engine)` to point
the function at a throwaway engine, with a hand-built minimal schema (not
the full `Base.metadata.create_all`) so the statement for every table this
minimal DB doesn't have just fails and rolls back individually, exactly as
that existing test's docstring explains `upgrade_schema()` is written to
tolerate. Follow that same pattern here, not `db_session`:

```python
# backend/tests/test_models_contingency.py (continued)
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

def test_existing_item_backfills_essential_from_category(monkeypatch):
    """A pre-existing row (simulating data from before this migration) with a
    discretionary category backfills to is_essential=False; one with a
    non-discretionary category backfills to True. Mirrors
    test_plaid_schema.py's engine-swap pattern -- never touches the real DB."""
    import backend.database as database_module

    test_engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    with test_engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE categories (
                id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
                name VARCHAR(64) NOT NULL, is_discretionary BOOLEAN DEFAULT 0
            )
        """))
        conn.execute(text("""
            CREATE TABLE recurring_items (
                id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
                account_id INTEGER NOT NULL, category_id INTEGER,
                name VARCHAR(128) NOT NULL, amount NUMERIC(14,2) NOT NULL,
                type VARCHAR(20) NOT NULL, frequency VARCHAR(10) DEFAULT 'monthly',
                day_of_month INTEGER NOT NULL, start_date DATE NOT NULL,
                is_active BOOLEAN DEFAULT 1
            )
        """))
        conn.execute(text(
            "INSERT INTO categories (id, user_id, name, is_discretionary) VALUES "
            "(1, 1, 'Test Discretionary', 1), (2, 1, 'Test Necessary', 0)"
        ))
        conn.execute(text(
            "INSERT INTO recurring_items (user_id, account_id, category_id, name, amount, type, day_of_month, start_date) "
            "VALUES (1, 1, 1, 'Pre-migration Discretionary', 45.00, 'expense', 15, '2026-01-01'), "
            "(1, 1, 2, 'Pre-migration Necessary', 45.00, 'expense', 15, '2026-01-01')"
        ))
        conn.commit()

    monkeypatch.setattr(database_module, "engine", test_engine)
    database_module.upgrade_schema()

    with test_engine.connect() as conn:
        rows = {
            row[0]: row[1] for row in conn.execute(
                text("SELECT name, is_essential FROM recurring_items")
            )
        }
    assert rows["Pre-migration Discretionary"] == 0
    assert rows["Pre-migration Necessary"] == 1
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd backend && uv run --locked python -m pytest tests/test_models_contingency.py -v`
Expected: FAIL with `sqlite3.OperationalError: no such column: is_essential` — the
hand-built minimal schema has no `is_essential` column yet, and
`upgrade_schema()` doesn't add one until the next step.

- [ ] **Step 7: Add the migration — ALTER plus a one-time backfill, bundled so the backfill never re-runs**

In `backend/database.py`'s `upgrade_schema()`: **do not** add the backfill as
another entry in the flat `stmts` list — a plain `UPDATE` statement in that
list would re-run (and re-overwrite Dan's manual edits) on every server
restart, since `UPDATE` doesn't fail the way `ALTER TABLE ADD COLUMN` does
when already applied. Add `"ALTER TABLE recurring_items ADD COLUMN
contingency_paused_at DATETIME"` as a normal entry in `stmts` (same pattern
as every other line). Handle `is_essential` separately, in its own block
right after the `stmts` loop, so its one-time backfill only runs the single
time the column is newly added:

```python
    # is_essential needs a backfill from each item's category, not just a
    # flat default -- unlike every other line above, a plain UPDATE here
    # would re-run (and clobber Dan's manual edits) on every restart, since
    # UPDATE doesn't fail once already applied the way ALTER does. Running
    # the backfill only inside the branch where the ALTER just newly
    # succeeded makes it a true one-time migration.
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE recurring_items ADD COLUMN is_essential BOOLEAN DEFAULT 1"))
            conn.execute(text(
                "UPDATE recurring_items SET is_essential = 0 WHERE category_id IN "
                "(SELECT id FROM categories WHERE is_discretionary = 1)"
            ))
            conn.commit()
        except Exception:
            conn.rollback()  # column already exists -- backfill already ran
```

Place this new block immediately after the existing `stmts` loop inside
`upgrade_schema()`, following that loop's own `with engine.connect() as
conn:` style.

- [ ] **Step 8: Run test to verify it passes**

Run: `cd backend && uv run --locked python -m pytest tests/test_models_contingency.py -v`
Expected: PASS

- [ ] **Step 9: Expose the fields on the API schemas**

In `backend/schemas.py`: add `is_essential: bool = True` to `RecurringCreate` (mirrors `is_floating: bool = False`'s style) and to `RecurringOut`; add `is_essential: Optional[bool] = None` to `RecurringUpdate` (mirrors `is_floating: Optional[bool] = None`). Add `is_discretionary: bool = False` to `CategoryOut` (near `tax_deductible`, ~line 295) — this field already exists on the `Category` model, it's just never been exposed to API responses; the frontend task needs it to compute the Essential checkbox's create-time default.

- [ ] **Step 10: Run the full backend suite**

Run: `cd backend && uv run --locked python -m pytest -q`
Expected: all pass

- [ ] **Step 11: Commit**

```bash
git add backend/models.py backend/database.py backend/schemas.py backend/tests/test_models_contingency.py
git commit -m "feat: is_essential and contingency_paused_at on RecurringItem"
```

---

### Task 2: Backend — contingency endpoint + pause/unpause

**Files:**
- Modify: `backend/schemas.py` (new `ContingencyCutItem`, `ContingencyPlan`)
- Modify: `backend/routers/recurring.py` (new `GET /recurring/contingency`, `POST`/`DELETE /recurring/{item_id}/contingency-pause`)
- Test: `backend/tests/test_recurring_contingency.py` (new)

**Interfaces:**
- Consumes: `RecurringItem.is_essential`/`contingency_paused_at` (Task 1), `backend.services.month_base.budget_allocation_total` (existing), `backend.services.recurring_math.monthly_equivalent` (existing, already imported in `recurring.py` as `_monthly_equivalent`).
- Produces: `GET /recurring/contingency` → `schemas.ContingencyPlan` = `{floor: Decimal, emergency_fund_balance: Decimal, surplus: Decimal, cut_list: list[ContingencyCutItem]}`, each `ContingencyCutItem = {id: int, name: str, monthly_equivalent: Decimal, is_paused: bool}`. `POST /recurring/{item_id}/contingency-pause` (201, sets `contingency_paused_at = now`), `DELETE /recurring/{item_id}/contingency-pause` (204, clears to `None`).

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_recurring_contingency.py
from datetime import date
from decimal import Decimal
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.routers import recurring as recurring_router_module
from backend.dependencies import get_db, get_current_user


@pytest.fixture()
def client(db_session):
    user = models.User(username="cp", hashed_password="x", display_name="CP")
    db_session.add(user)
    db_session.flush()
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
    )
    db_session.add(account)
    db_session.commit()
    app = FastAPI()
    app.include_router(recurring_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app), user, account


def _essential_item(db, user, account, **kw):
    defaults = dict(
        user_id=user.id, account_id=account.id, name="Essential Thing",
        amount=Decimal("100.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=1,
        start_date=date(2026, 1, 1), is_essential=True,
    )
    defaults.update(kw)
    item = models.RecurringItem(**defaults)
    db.add(item)
    db.flush()
    return item


def test_floor_is_three_times_essential_monthly_total(client, db_session):
    test_client, user, account = client
    _essential_item(db_session, user, account, amount=Decimal("1000.00"))
    db_session.commit()

    body = test_client.get("/recurring/contingency").json()

    assert body["floor"] == "3000.00"


def test_non_essential_item_excluded_from_floor_but_in_cut_list(client, db_session):
    test_client, user, account = client
    _essential_item(db_session, user, account, name="Non-essential", amount=Decimal("50.00"), is_essential=False)
    db_session.commit()

    body = test_client.get("/recurring/contingency").json()

    assert body["floor"] == "0.00"
    assert [i["name"] for i in body["cut_list"]] == ["Non-essential"]


def test_essential_item_never_in_cut_list(client, db_session):
    test_client, user, account = client
    _essential_item(db_session, user, account, amount=Decimal("5000.00"))
    db_session.commit()

    body = test_client.get("/recurring/contingency").json()

    assert body["cut_list"] == []


def test_inactive_item_excluded_from_both_floor_and_cut_list(client, db_session):
    test_client, user, account = client
    _essential_item(db_session, user, account, amount=Decimal("1000.00"), is_active=False)
    _essential_item(db_session, user, account, name="Inactive non-essential", amount=Decimal("50.00"), is_essential=False, is_active=False)
    db_session.commit()

    body = test_client.get("/recurring/contingency").json()

    assert body["floor"] == "0.00"
    assert body["cut_list"] == []


def test_missing_groceries_category_resolves_to_zero_not_error(client, db_session):
    """No 'Groceries' category exists at all for this user -- the floor's
    grocery component must be $0, not a crash."""
    test_client, user, account = client

    resp = test_client.get("/recurring/contingency")

    assert resp.status_code == 200
    assert resp.json()["floor"] == "0.00"


def test_groceries_budget_allocation_added_to_floor(client, db_session):
    test_client, user, account = client
    groceries_cat = models.Category(
        user_id=user.id, name="Groceries", type=models.CategoryType.expense, color="#000000",
    )
    db_session.add(groceries_cat)
    db_session.flush()
    db_session.add(models.BudgetAllocation(
        user_id=user.id, category_id=groceries_cat.id, year=date.today().year,
        month=0, budgeted_amount=Decimal("700.00"),
    ))
    db_session.commit()

    body = test_client.get("/recurring/contingency").json()

    assert body["floor"] == "2100.00"  # 700 * 3, no recurring items


def test_contingency_pause_rejected_on_essential_item(client, db_session):
    test_client, user, account = client
    item = _essential_item(db_session, user, account)
    db_session.commit()

    resp = test_client.post(f"/recurring/{item.id}/contingency-pause")

    assert resp.status_code == 400


def test_contingency_pause_and_unpause_on_non_essential_item(client, db_session):
    test_client, user, account = client
    item = _essential_item(db_session, user, account, is_essential=False)
    db_session.commit()

    resp = test_client.post(f"/recurring/{item.id}/contingency-pause")
    assert resp.status_code == 201
    body = test_client.get("/recurring/contingency").json()
    assert body["cut_list"][0]["is_paused"] is True

    resp2 = test_client.delete(f"/recurring/{item.id}/contingency-pause")
    assert resp2.status_code == 204
    body2 = test_client.get("/recurring/contingency").json()
    assert body2["cut_list"][0]["is_paused"] is False


def test_other_users_accounts_and_items_never_leak_into_contingency(client, db_session):
    test_client, user, account = client
    other_user = models.User(username="cp-other", hashed_password="x", display_name="Other")
    db_session.add(other_user)
    db_session.flush()
    other_account = models.Account(
        user_id=other_user.id, name="Other Checking", type=models.AccountType.checking,
        is_emergency_fund=True, current_balance=Decimal("999999.00"),
    )
    db_session.add(other_account)
    _essential_item(db_session, other_user, other_account, name="Other User Item", amount=Decimal("99999.00"))
    db_session.commit()

    body = test_client.get("/recurring/contingency").json()

    assert body["floor"] == "0.00"
    assert body["emergency_fund_balance"] == "0.00"
    assert body["cut_list"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run --locked python -m pytest tests/test_recurring_contingency.py -v`
Expected: FAIL — route doesn't exist.

- [ ] **Step 3: Implement `GET /recurring/contingency`**

In `backend/schemas.py`: add
```python
class ContingencyCutItem(BaseModel):
    id: int
    name: str
    monthly_equivalent: Decimal
    is_paused: bool

class ContingencyPlan(BaseModel):
    floor: Decimal
    emergency_fund_balance: Decimal
    surplus: Decimal
    cut_list: list[ContingencyCutItem]
```

In `backend/routers/recurring.py`, add `GET /contingency` (register it
before `/{item_id}` the same way `/breakdown` already is, per that route's
own comment about shadowing). Query the user's active, expense-type
`RecurringItem` rows the same way `get_breakdown` already does (reuse its
`is_expense`/`credit_card_payment`-exclusion logic — only `type ==
RecurringType.expense` counts, exactly as `get_breakdown` already does).
Split into `is_essential=True` (sum their `_monthly_equivalent` into
`essential_monthly`) and `is_essential=False` (build `ContingencyCutItem`
rows, sorted by `monthly_equivalent` descending, `is_paused =
contingency_paused_at is not None`). Add groceries: `from
backend.services.month_base import budget_allocation_total; today =
date.today(); essential_monthly += budget_allocation_total(db, user.id,
"Groceries", today.year, today.month)`. `floor = essential_monthly * 3`.
Emergency-fund balance: sum `current_balance` of the user's active accounts
with `type.in_([models.AccountType.savings, models.AccountType.money_market])
and is_emergency_fund == True` (mirror `budget_snapshot.py:707-715`'s query
shape exactly, just flip the `is_emergency_fund` comparison). `surplus =
emergency_fund_balance - floor`.

- [ ] **Step 4: Implement the pause/unpause endpoints**

```python
@router.post("/{item_id}/contingency-pause", status_code=status.HTTP_201_CREATED)
def contingency_pause(item_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    item = _get_or_404(db, user.id, item_id)
    if item.is_essential:
        raise HTTPException(status_code=400, detail="Cannot pause an essential item")
    item.contingency_paused_at = datetime.utcnow()
    db.commit()
    return {"ok": True}


@router.delete("/{item_id}/contingency-pause", status_code=status.HTTP_204_NO_CONTENT)
def contingency_unpause(item_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    item = _get_or_404(db, user.id, item_id)
    item.contingency_paused_at = None
    db.commit()
```

Check this file's existing imports for `datetime` (it may already import it
for another field) before adding a duplicate import.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run --locked python -m pytest tests/test_recurring_contingency.py -v`
Expected: PASS

- [ ] **Step 6: Run the full backend suite**

Run: `cd backend && uv run --locked python -m pytest -q`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add backend/schemas.py backend/routers/recurring.py backend/tests/test_recurring_contingency.py
git commit -m "feat: contingency floor/surplus endpoint and pause tracking"
```

---

### Task 3: Frontend — Essential checkbox, Contingency Planning page, nav

**Files:**
- Modify: `frontend/src/pages/Recurring.tsx` (Essential checkbox in the item form)
- Create: `frontend/src/pages/Contingency.tsx`
- Modify: `frontend/src/api/index.ts` (contingency endpoint calls)
- Modify: `frontend/src/lib/navItems.ts` (new nav entry)
- Modify: `frontend/src/App.tsx` (new route)

**Interfaces:**
- Consumes: `GET /recurring/contingency`, `POST`/`DELETE /recurring/{id}/contingency-pause` (Task 2); `CategoryOut.is_discretionary` (Task 1).
- Produces: nothing consumed by other tasks (final task).

- [ ] **Step 1: Add API client calls**

In `frontend/src/api/index.ts`'s `recurringApi` block, add:
```ts
contingency: () => api.get("/recurring/contingency").then((r) => r.data),
contingencyPause: (itemId: number) => api.post(`/recurring/${itemId}/contingency-pause`).then((r) => r.data),
contingencyUnpause: (itemId: number) => api.delete(`/recurring/${itemId}/contingency-pause`),
```

- [ ] **Step 2: Essential checkbox on the Recurring item form**

In `frontend/src/pages/Recurring.tsx`: add `is_essential: true` to
`emptyForm` (~line 25), add `is_essential: !!i.is_essential` to
`openEdit`'s form-population (~line 214), include `is_essential:
form.is_essential` in the submit payload (~line 218). Add a checkbox near
the existing Floating/Amount-varies checkboxes (~line 694/706), labeled
"Essential (always keep paying this)". Create-time auto-default: when the
category `<select>`'s `onChange` fires (~line 664) and `editItem` is
`null` (i.e. this is a brand-new item, not editing an existing one) *and*
the user hasn't manually touched the Essential checkbox yet in this form
session, also set `is_essential` to the selected category's `!
is_discretionary` (categories are already in scope via the existing
`categories`/`allCats` query, Task 1 exposes `is_discretionary` on each).
Track "has the user manually touched it" with one extra boolean in
component state (reset to `false` whenever `openNew`/`openEdit` resets the
form), set to `true` the moment the Essential checkbox's own `onChange`
fires — once true, the category `onChange` handler never overwrites
`is_essential` again, satisfying the design's "create-time default, then
manual forever" rule (and, per that same rule, editing an *existing*
item's category must never touch `is_essential`, which this `editItem ===
null` guard already ensures).

- [ ] **Step 3: Create the Contingency Planning page**

Create `frontend/src/pages/Contingency.tsx`. Fetch `recurringApi.contingency()`
via `useQuery`. Render three headline numbers (floor, emergency-fund
balance, surplus — surplus in a warning color when negative, matching
this app's existing convention for a below-zero figure elsewhere, e.g.
check `Dashboard.tsx` for the pattern it already uses) and a list of
`cut_list` items sorted as the backend already returns them (no client-side
sort), each row showing name, monthly cost, and a checkbox bound to
`is_paused` that calls `contingencyPause`/`contingencyUnpause` on toggle
and invalidates the `["recurring-contingency"]` query key on success (mirror
the mutation/invalidation pattern already used for skip/unskip in
`Recurring.tsx`).

- [ ] **Step 4: Register the page**

In `frontend/src/lib/navItems.ts`: add `{ to: "/contingency", icon:
ShieldCheck, label: "Contingency Planning" }` to the `planning` group's
`items` array (import `ShieldCheck` from `lucide-react` alongside the
other icons already imported there — pick a different icon only if
`ShieldCheck` isn't available in this project's pinned `lucide-react`
version).

In `frontend/src/App.tsx`: import `Contingency` from `./pages/Contingency`
and add `<Route path="contingency" element={<Contingency />} />` inside
the existing private route group (alongside `budget`/`goals`/`forecast`).

- [ ] **Step 5: Run frontend checks**

Run: `cd frontend && bun test && bunx vite build`
Expected: all pass, build succeeds

- [ ] **Step 6: Live-verify via Interceptor**

Open the Recurring page: confirm the Essential checkbox renders, defaults
correctly when picking a discretionary vs. non-discretionary category on a
*new* item, and does NOT change when editing an existing item's category.
Open the new Contingency Planning page from the sidebar: confirm the floor,
emergency-fund balance, and surplus render with real numbers, the cut list
shows the expected non-essential items, and toggling a Paused checkbox
persists after a refresh.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/Recurring.tsx frontend/src/pages/Contingency.tsx frontend/src/api/index.ts frontend/src/lib/navItems.ts frontend/src/App.tsx
git commit -m "feat: Contingency Planning page, Essential checkbox, nav entry"
```
