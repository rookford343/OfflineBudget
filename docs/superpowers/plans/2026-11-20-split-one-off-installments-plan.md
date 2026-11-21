# Split One-Off Installments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a one-off (`PlannedExpense`) be created as 2-6 dated installments under one name and one payment method, with a combined cancel lifecycle: deleting any unpaid installment cancels the rest of the plan, and deleting after part is paid leaves that history alone and opens a cancelable refund-watch.

**Architecture:** Two new nullable columns on `planned_expenses` (a self-referencing group link, and a flag marking a refund-watch row) added through the repo's existing idempotent `ALTER TABLE` list. A new service module owns the group-specific behavior — building the legs, previewing their combined effect, and cancelling a group — while every existing single-leg endpoint, and the existing bank-sync auto-settle matcher, stay untouched and keep working exactly as today.

**Tech Stack:** FastAPI + SQLAlchemy + Pydantic (backend), React + TanStack Query (frontend), pytest (backend tests), bun test (frontend logic tests).

**Spec:** `docs/superpowers/specs/2026-11-20-split-one-off-installments-design.md`

## Global Constraints

- Cap: every installment group has 2-6 legs. Reject outside that range.
- One shared `account_id`/`card_id` for the whole group, set once at creation; no per-leg override.
- Each leg's stored `name` gets a "(k of N)" suffix baked in at creation time (e.g. "Leia dental (1 of 2)"); never recomputed later.
- Funding fields (`funding_account_id`, `funding_amount`, `funding_lead_days`) are not exposed anywhere in the installments flow; always null for a leg or a refund-watch row. A one-off needing savings funding stays a plain, unsplit `PlannedExpense`.
- Installments are outflow-only. (Splitting an inflow one-off was never asked for; the plain single-leg flow still covers an inflow like a bonus.)
- "Already cleared," for every rule in this plan, means `settled_on IS NOT NULL AND actual_amount IS NOT NULL`. A row with `settled_on` set but `actual_amount` null ("settled, didn't happen") counts as unpaid.
- No `CALC_VERSION` bump and no `docs/architecture.md` calculation-changelog entry — this feature adds rows and a lifecycle path, it does not change how any existing money figure is computed. A `docs/architecture.md` Decisions log entry is still required (Task 7).
- No Alembic in this repo. New columns go through the existing idempotent list in `upgrade_schema()` (`backend/database.py:110-156`), the same way `planned_expenses.account_id` was added at `backend/database.py:129`.
- A service function in this feature never calls `db.commit()` itself — it only adds/deletes/flushes. The caller (the router) commits once, matching the existing convention (`apply_settlement`, `auto_settle_planned_expenses`).
- Direct commits to `main`. No feature branch, no worktree (this repo's standing convention).
- Use synthetic dollar figures in every test, docstring, and commit message — this repo is public.

## Review Focus

- A group where one leg is "settled, didn't happen" (`settled_on` set, `actual_amount` null) and another is still unpaid: deleting either must sweep both, with no refund-watch spawned for the "didn't happen" one. (Task 4)
- A bulk-create request with 1, 7, or 0 legs: rejected before anything is written, not silently clamped. (Task 2)
- A bulk-create request that fails partway (e.g. leg 3 of 5 names an `account_id` the caller doesn't own): the whole group is rolled back, not left half-created. (Task 2)
- Installments on the same card spanning more than one statement cycle: the combined preview must show every distinct due date's impact, not just the first or last. (Task 3)
- Deleting the refund-watch row itself: must never re-run the group-cancel cascade (it shares `installment_group_id` with real legs, but is exempt). (Task 4)

---

## Task 1: Schema — group link and refund-watch flag on `PlannedExpense`

**Files:**
- Modify: `backend/models.py:858-924` (`PlannedExpense` class)
- Modify: `backend/database.py:110-156` (`upgrade_schema()`)
- Test: `backend/tests/test_installment_schema.py`

**Interfaces:**
- Produces: `PlannedExpense.installment_group_id: int | None` (self-referencing FK to `planned_expenses.id`) and `PlannedExpense.is_refund_watch: bool` (default `False`, never null). Every later task reads/writes these two fields by these exact names.

- [ ] **Step 1: Write the failing migration test**

Mirror the existing pattern at `backend/tests/test_models_contingency.py:50-72` (build a minimal old-shape `planned_expenses` table in an in-memory SQLite engine with none of the two new columns, monkeypatch `database.engine`, run `upgrade_schema()`, assert the columns now exist):

```python
def test_upgrade_schema_adds_installment_columns(monkeypatch):
    import backend.database as database_module
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import StaticPool

    test_engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    with test_engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE planned_expenses (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                name VARCHAR(128) NOT NULL,
                amount NUMERIC(14,2) NOT NULL,
                expected_date DATE NOT NULL
            )
        """))
        conn.commit()

    monkeypatch.setattr(database_module, "engine", test_engine)
    database_module.upgrade_schema()

    with test_engine.connect() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(planned_expenses)"))}
    assert "installment_group_id" in cols
    assert "is_refund_watch" in cols
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run --locked python -m pytest tests/test_installment_schema.py -v`
Expected: FAIL — columns not found (not added yet).

- [ ] **Step 3: Add the two `ALTER TABLE` statements**

Append to the `stmts` list in `upgrade_schema()` (`backend/database.py`), after the existing `planned_expenses` entry at line 129:

```python
"ALTER TABLE planned_expenses ADD COLUMN installment_group_id INTEGER REFERENCES planned_expenses(id)",
"ALTER TABLE planned_expenses ADD COLUMN is_refund_watch BOOLEAN DEFAULT 0",
```

- [ ] **Step 4: Add the two fields to the model**

In `backend/models.py`, inside `class PlannedExpense`, add after `actual_amount` (line 913):

```python
    installment_group_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("planned_expenses.id"),
    )
    is_refund_watch: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
```

One line of docstring above the two fields explaining what they're for is appropriate here (this repo's convention); state that every leg in a group shares `installment_group_id` (the anchor leg's own id), that a refund-watch row shares it too but is excluded from the group-cancel cascade, and point at the design doc.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run --locked python -m pytest tests/test_installment_schema.py -v`
Expected: PASS

- [ ] **Step 6: Run the full backend test suite to confirm nothing else broke**

Run: `cd backend && uv run --locked python -m pytest -q`
Expected: all pass (two new nullable columns on an existing table should not change any existing test's behavior).

- [ ] **Step 7: Commit**

```bash
git add backend/models.py backend/database.py backend/tests/test_installment_schema.py
git commit -m "Add installment_group_id and is_refund_watch columns to PlannedExpense"
```

---

## Task 2: Bulk-create a group of installments

**Files:**
- Create: `backend/services/installment_plan.py`
- Modify: `backend/schemas.py` (add new schemas near `PlannedExpenseOut`, ~line 1950)
- Modify: `backend/routers/planned_expenses.py` (add one new route, near the existing `create_planned_expense`)
- Test: `backend/tests/test_installment_plan.py`

**Interfaces:**
- Consumes: `models.PlannedExpense`, `models.PlannedDirection` (Task 1); the router's existing `_require_owned()` helper (`backend/routers/planned_expenses.py:12-32`).
- Produces: `schemas.InstallmentLegIn`, `schemas.PlannedExpenseInstallmentsCreate`, `schemas.PlannedExpenseInstallmentsOut` (schemas.py); `installment_plan.MIN_INSTALLMENTS = 2`, `installment_plan.MAX_INSTALLMENTS = 6`; `installment_plan.create_installment_group(db: Session, user: models.User, body: schemas.PlannedExpenseInstallmentsCreate) -> list[models.PlannedExpense]` (adds and flushes every leg, assigns `installment_group_id`, does not commit). Task 4 and Task 6 both call this module; Task 3 mirrors its leg-construction logic for a transient (never-persisted) preview.

- [ ] **Step 1: Write the failing schema + cap tests**

```python
# backend/tests/test_installment_plan.py
import pytest
from datetime import date, timedelta
from decimal import Decimal
from pydantic import ValidationError
from backend import schemas

def _legs(n, amount="50.00"):
    return [
        {"amount": amount, "expected_date": (date.today() + timedelta(days=i)).isoformat()}
        for i in range(n)
    ]

def test_rejects_fewer_than_two_legs():
    with pytest.raises(ValidationError):
        schemas.PlannedExpenseInstallmentsCreate(name="X", legs=_legs(1))

def test_rejects_more_than_six_legs():
    with pytest.raises(ValidationError):
        schemas.PlannedExpenseInstallmentsCreate(name="X", legs=_legs(7))

def test_accepts_two_to_six_legs():
    for n in (2, 6):
        schemas.PlannedExpenseInstallmentsCreate(name="X", legs=_legs(n))

def test_rejects_a_non_positive_leg_amount():
    with pytest.raises(ValidationError):
        schemas.PlannedExpenseInstallmentsCreate(name="X", legs=_legs(2, amount="0.00"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run --locked python -m pytest tests/test_installment_plan.py -v`
Expected: FAIL with `AttributeError`/`ImportError` — `schemas.PlannedExpenseInstallmentsCreate` does not exist yet.

- [ ] **Step 3: Add the schemas**

In `backend/schemas.py`, near `PlannedExpenseOut` (~line 1950):

```python
class InstallmentLegIn(BaseModel):
    amount: Decimal
    expected_date: date

    @model_validator(mode="after")
    def _amount_is_positive(self):
        if self.amount <= 0:
            raise ValueError("each installment's amount must be greater than zero")
        return self


class PlannedExpenseInstallmentsCreate(BaseModel):
    name: str
    legs: list[InstallmentLegIn]
    notes: Optional[str] = None
    category_id: Optional[int] = None
    account_id: Optional[int] = None
    card_id: Optional[int] = None

    @model_validator(mode="after")
    def _two_to_six_legs(self):
        if not (2 <= len(self.legs) <= 6):
            raise ValueError(
                "a split one-off needs between 2 and 6 installments "
                "-- more than 6 should be a recurring item instead",
            )
        return self


class PlannedExpenseInstallmentsOut(BaseModel):
    legs: list[PlannedExpenseOut]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run --locked python -m pytest tests/test_installment_plan.py -v`
Expected: the 4 tests from Step 1 PASS.

- [ ] **Step 5: Write the failing creation + atomicity tests**

Follow `backend/tests/test_one_off_preview.py`'s fixture style (`_seed`, `_client`, `db_session`) for the DB/app setup. Add to the same test file:

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.dependencies import get_current_user, get_db
from backend.routers import planned_expenses as pe_router
from backend.services.installment_plan import create_installment_group

def _seed(db):
    user = models.User(username="inst", hashed_password="x", display_name="Inst")
    db.add(user)
    db.flush()
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("1000.00"),
    )
    db.add(account)
    db.commit()
    return user, account

def _client(db, user):
    app = FastAPI()
    app.include_router(pe_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)

def test_create_installment_group_makes_n_linked_legs_with_numbered_names(db_session):
    user, account = _seed(db_session)
    legs = create_installment_group(db_session, user, schemas.PlannedExpenseInstallmentsCreate(
        name="Leia dental", account_id=account.id, legs=[
            {"amount": "50.00", "expected_date": date.today().isoformat()},
            {"amount": "75.00", "expected_date": (date.today() + timedelta(days=30)).isoformat()},
        ],
    ))
    db_session.commit()
    assert len(legs) == 2
    assert legs[0].name == "Leia dental (1 of 2)"
    assert legs[1].name == "Leia dental (2 of 2)"
    assert legs[0].installment_group_id == legs[0].id
    assert legs[1].installment_group_id == legs[0].id
    assert all(pe.account_id == account.id for pe in legs)
    assert all(pe.direction == models.PlannedDirection.outflow for pe in legs)
    assert all(not pe.is_refund_watch for pe in legs)

def test_create_installment_group_rejects_an_account_the_caller_does_not_own(db_session):
    user, account = _seed(db_session)
    other = models.User(username="other-inst", hashed_password="x", display_name="O")
    db_session.add(other)
    db_session.commit()
    client = _client(db_session, other)
    body = {"name": "X", "account_id": account.id, "legs": [
        {"amount": "10.00", "expected_date": date.today().isoformat()},
        {"amount": "10.00", "expected_date": date.today().isoformat()},
    ]}
    before = db_session.query(models.PlannedExpense).count()
    r = client.post("/planned-expenses/installments", json=body)
    assert r.status_code == 404
    assert db_session.query(models.PlannedExpense).count() == before
```

The second test is the atomicity check: a rejected group must leave zero rows behind, not a partial set.

- [ ] **Step 6: Run tests to verify they fail**

Run: `cd backend && uv run --locked python -m pytest tests/test_installment_plan.py -v`
Expected: FAIL — `create_installment_group` and the router route don't exist yet.

- [ ] **Step 7: Implement `create_installment_group` in `backend/services/installment_plan.py`**

```python
MIN_INSTALLMENTS = 2
MAX_INSTALLMENTS = 6

def create_installment_group(
    db: Session, user: models.User, body: schemas.PlannedExpenseInstallmentsCreate,
) -> list[models.PlannedExpense]:
```

Build each leg as a `models.PlannedExpense` with `direction=models.PlannedDirection.outflow`, `name=f"{body.name} ({i} of {n})"` (1-based `i`, `n = len(body.legs)`), the shared `notes`/`category_id`/`account_id`/`card_id` from `body`, funding fields left at their defaults (null), `db.add()` each, `db.flush()` once to get the first leg's id, then set every leg's `installment_group_id` to that first leg's id (including the first leg itself) and `db.flush()` again. Returns the list of legs in order. Does not commit.

- [ ] **Step 8: Add the router route**

In `backend/routers/planned_expenses.py`, near `create_planned_expense`:

```python
@router.post("/installments", response_model=schemas.PlannedExpenseInstallmentsOut, status_code=status.HTTP_201_CREATED)
def create_planned_expense_installments(
    body: schemas.PlannedExpenseInstallmentsCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    _require_owned(
        db, user, account_id=body.account_id, card_id=body.card_id, category_id=body.category_id,
    )
    legs = create_installment_group(db, user, body)
    db.commit()
    for leg in legs:
        db.refresh(leg)
    return schemas.PlannedExpenseInstallmentsOut(legs=legs)
```

Import `create_installment_group` from `backend.services.installment_plan` at the top of the file.

- [ ] **Step 9: Run tests to verify they pass**

Run: `cd backend && uv run --locked python -m pytest tests/test_installment_plan.py -v`
Expected: PASS

- [ ] **Step 10: Run the full backend test suite**

Run: `cd backend && uv run --locked python -m pytest -q`
Expected: all pass.

- [ ] **Step 11: Commit**

```bash
git add backend/services/installment_plan.py backend/schemas.py backend/routers/planned_expenses.py backend/tests/test_installment_plan.py
git commit -m "Add bulk-create endpoint for split one-off installments"
```

---

## Task 3: Combined Safety Margin preview for a group

**Files:**
- Modify: `backend/services/installment_plan.py` (add `preview_installment_group`)
- Modify: `backend/schemas.py` (add `InstallmentsPreviewOut`)
- Modify: `backend/routers/planned_expenses.py` (add one new route)
- Test: `backend/tests/test_installment_plan.py` (same file as Task 2)

**Interfaces:**
- Consumes: `schemas.PlannedExpenseInstallmentsCreate` (Task 2); `backend.services.budget_snapshot.compute_budget_snapshot`; `backend.services.forecast_engine.ScenarioProposal`, `_card_payoff_date_for_charge` (both already used by `backend/services/one_off_preview.py`); `schemas.BeforeAfter`, `schemas.CardPaymentImpact` (both already exist, used by `OneOffPreviewOut`).
- Produces: `schemas.InstallmentsPreviewOut` (`safety_margin_weekly: BeforeAfter`, `safety_margin: BeforeAfter`, `card_payments: list[CardPaymentImpact]`); `installment_plan.preview_installment_group(db: Session, user: models.User, account_id: int, body: schemas.PlannedExpenseInstallmentsCreate) -> schemas.InstallmentsPreviewOut`. Task 6 (frontend) calls this via the new router route.

- [ ] **Step 1: Write the failing preview tests**

Add to `backend/tests/test_installment_plan.py`, reusing `_seed`/`_client` from Task 2 (extend `_seed` to also return a `CreditCard`, mirroring `backend/tests/test_one_off_preview.py:49-54`):

```python
def test_preview_installments_matches_combined_commit(db_session):
    user, account = _seed(db_session)
    client = _client(db_session, user)
    body = {"name": "Leia dental", "account_id": account.id, "legs": [
        {"amount": "50.00", "expected_date": date.today().isoformat()},
        {"amount": "75.00", "expected_date": (date.today() + timedelta(days=30)).isoformat()},
    ]}
    base = compute_budget_snapshot(db_session, user, account.id)
    r = client.post(f"/planned-expenses/installments/preview?account_id={account.id}", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert client.post("/planned-expenses/installments", json=body).status_code == 201
    after = compute_budget_snapshot(db_session, user, account.id)
    assert Decimal(out["safety_margin"]["before"]) == base.safety_margin
    assert Decimal(out["safety_margin"]["after"]) == after.safety_margin
    assert Decimal(out["safety_margin"]["after"]) < Decimal(out["safety_margin"]["before"])

def test_preview_installments_writes_nothing(db_session):
    user, account = _seed(db_session)
    client = _client(db_session, user)
    before = db_session.query(models.PlannedExpense).count()
    body = {"name": "X", "account_id": account.id, "legs": [
        {"amount": "10.00", "expected_date": date.today().isoformat()},
        {"amount": "10.00", "expected_date": (date.today() + timedelta(days=5)).isoformat()},
    ]}
    r = client.post(f"/planned-expenses/installments/preview?account_id={account.id}", json=body)
    assert r.status_code == 200, r.text
    assert db_session.query(models.PlannedExpense).count() == before

def test_preview_installments_lists_one_card_payment_per_distinct_due_date(db_session):
    user, account = _seed(db_session)
    card = models.CreditCard(
        user_id=user.id, name="Test Card", credit_limit=Decimal("5000.00"),
        statement_day=28, due_day=25, balance_due=Decimal("0.00"),
        current_balance=Decimal("0.00"),
    )
    db_session.add(card)
    db_session.commit()
    client = _client(db_session, user)
    # One leg today, one leg ~90 days out -- far enough apart to land on two
    # different statement cycles for any statement_day/due_day combination.
    body = {"name": "Spread out", "card_id": card.id, "legs": [
        {"amount": "20.00", "expected_date": date.today().isoformat()},
        {"amount": "30.00", "expected_date": (date.today() + timedelta(days=90)).isoformat()},
    ]}
    r = client.post(f"/planned-expenses/installments/preview?account_id={account.id}", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    due_dates = {cp["due"] for cp in out["card_payments"]}
    assert len(due_dates) == 2
    assert {Decimal(cp["amount"]) for cp in out["card_payments"]} == {Decimal("20.00"), Decimal("30.00")}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run --locked python -m pytest tests/test_installment_plan.py -v`
Expected: FAIL — `preview_installment_group` and the route don't exist yet.

- [ ] **Step 3: Implement `preview_installment_group`**

```python
def preview_installment_group(
    db: Session, user: models.User, account_id: int, body: schemas.PlannedExpenseInstallmentsCreate,
) -> schemas.InstallmentsPreviewOut:
```

Mirror `backend/services/one_off_preview.py`'s `preview_one_off` shape: build one transient `models.PlannedExpense` per leg with `id=-(i+1)` (negative, never colliding — see `ScenarioProposal`'s own id convention in `backend/services/forecast_engine.py:800-802`), the shared account/card/category, `direction=outflow`, no funding fields. Wrap them all in one `ScenarioProposal(expenses=tuple(legs))`. Call `compute_budget_snapshot` once with no proposal (`base`) and once with this proposal (`with_it`), exactly as `preview_one_off` does. If `body.card_id` is set, build one `schemas.CardPaymentImpact` per leg via `_card_payoff_date_for_charge(card, leg.expected_date)`, then collapse entries that land on the same `due` date into one (summing their amounts) so two legs due the same cycle show as one line, matching today's single-leg behavior when there's only one due date. Roll back and log a warning if `db.new or db.dirty` before returning, exactly like `preview_one_off` does.

- [ ] **Step 4: Add the schema**

In `backend/schemas.py`, near `OneOffPreviewOut`:

```python
class InstallmentsPreviewOut(BaseModel):
    safety_margin_weekly: BeforeAfter
    safety_margin: BeforeAfter
    card_payments: list[CardPaymentImpact] = []
```

- [ ] **Step 5: Add the router route**

```python
@router.post("/installments/preview", response_model=schemas.InstallmentsPreviewOut)
def preview_planned_expense_installments(
    body: schemas.PlannedExpenseInstallmentsCreate,
    account_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    _require_owned(
        db, user, account_id=body.account_id, card_id=body.card_id, category_id=body.category_id,
        also_account_ids=(account_id,),
    )
    return preview_installment_group(db, user, account_id, body)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && uv run --locked python -m pytest tests/test_installment_plan.py -v`
Expected: PASS

- [ ] **Step 7: Run the full backend test suite**

Run: `cd backend && uv run --locked python -m pytest -q --cov --cov-report=term:skip-covered`
Expected: all pass, coverage floor in `backend/.coveragerc` still met.

- [ ] **Step 8: Commit**

```bash
git add backend/services/installment_plan.py backend/schemas.py backend/routers/planned_expenses.py backend/tests/test_installment_plan.py
git commit -m "Add combined Safety Margin preview for split one-off installments"
```

---

## Task 4: Cancel-the-group delete, refund-watch, and its settlement

**Files:**
- Modify: `backend/services/installment_plan.py` (add `cancel_installment_group`)
- Modify: `backend/routers/planned_expenses.py:135-156` (`delete_planned_expense`)
- Test: `backend/tests/test_installment_cancellation.py`

**Interfaces:**
- Consumes: `models.PlannedExpense`, `installment_group_id`, `is_refund_watch` (Task 1); `backend.services.planned_auto_settle.auto_settle_planned_expenses` (existing, unmodified).
- Produces: `installment_plan.cancel_installment_group(db: Session, user: models.User, expense: models.PlannedExpense) -> None`. Nothing later depends on this beyond the router.

- [ ] **Step 1: Write the failing cancellation tests**

```python
# backend/tests/test_installment_cancellation.py
from datetime import date, timedelta
from decimal import Decimal
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models, schemas
from backend.dependencies import get_current_user, get_db
from backend.routers import planned_expenses as pe_router
from backend.services.installment_plan import create_installment_group
from backend.services.planned_auto_settle import auto_settle_planned_expenses

def _seed(db):
    user = models.User(username="cancel", hashed_password="x", display_name="Cancel")
    db.add(user)
    db.flush()
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("1000.00"),
    )
    db.add(account)
    db.commit()
    return user, account

def _client(db, user):
    app = FastAPI()
    app.include_router(pe_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)

def _group(db, user, account, amounts):
    legs = create_installment_group(db, user, schemas.PlannedExpenseInstallmentsCreate(
        name="Dental", account_id=account.id, legs=[
            {"amount": a, "expected_date": (date.today() + timedelta(days=i * 30)).isoformat()}
            for i, a in enumerate(amounts)
        ],
    ))
    db.commit()
    return legs

def test_deleting_an_unpaid_leg_cancels_the_whole_group(db_session):
    user, account = _seed(db_session)
    legs = _group(db_session, user, account, ["50.00", "75.00"])
    client = _client(db_session, user)
    assert client.delete(f"/planned-expenses/{legs[0].id}").status_code == 204
    remaining = db_session.query(models.PlannedExpense).filter(
        models.PlannedExpense.installment_group_id == legs[0].id,
    ).all()
    assert remaining == []

def test_deleting_a_cleared_leg_sweeps_the_unpaid_sibling_and_opens_a_refund_watch(db_session):
    user, account = _seed(db_session)
    legs = _group(db_session, user, account, ["50.00", "75.00"])
    legs[0].settled_on = date.today()
    legs[0].actual_amount = Decimal("50.00")
    db_session.commit()
    client = _client(db_session, user)
    assert client.delete(f"/planned-expenses/{legs[0].id}").status_code == 204

    group_rows = db_session.query(models.PlannedExpense).filter(
        models.PlannedExpense.installment_group_id == legs[0].id,
    ).all()
    assert {pe.id for pe in group_rows} & {legs[1].id} == set()  # unpaid sibling swept
    assert any(pe.id == legs[0].id for pe in group_rows)  # cleared leg kept as history

    refund = next(pe for pe in group_rows if pe.is_refund_watch)
    assert refund.direction == models.PlannedDirection.inflow
    assert refund.amount == Decimal("50.00")
    assert refund.account_id == account.id
    assert refund.expected_date == date.today()

def test_settled_with_no_actual_amount_counts_as_unpaid(db_session):
    user, account = _seed(db_session)
    legs = _group(db_session, user, account, ["50.00", "75.00"])
    legs[0].settled_on = date.today()  # "didn't happen" -- no actual_amount
    db_session.commit()
    client = _client(db_session, user)
    assert client.delete(f"/planned-expenses/{legs[1].id}").status_code == 204
    remaining = db_session.query(models.PlannedExpense).filter(
        models.PlannedExpense.installment_group_id == legs[0].id,
    ).all()
    assert remaining == []  # both swept, no refund-watch for the "didn't happen" leg

def test_deleting_the_refund_watch_itself_does_not_recascade(db_session):
    user, account = _seed(db_session)
    legs = _group(db_session, user, account, ["50.00", "75.00"])
    legs[0].settled_on = date.today()
    legs[0].actual_amount = Decimal("50.00")
    db_session.commit()
    client = _client(db_session, user)
    client.delete(f"/planned-expenses/{legs[0].id}")
    refund = db_session.query(models.PlannedExpense).filter(
        models.PlannedExpense.installment_group_id == legs[0].id,
        models.PlannedExpense.is_refund_watch.is_(True),
    ).one()
    assert client.delete(f"/planned-expenses/{refund.id}").status_code == 204
    remaining = db_session.query(models.PlannedExpense).filter(
        models.PlannedExpense.installment_group_id == legs[0].id,
    ).all()
    assert [pe.id for pe in remaining] == [legs[0].id]  # only the cleared leg is left, untouched

def test_deleting_history_after_the_group_already_fully_settled_does_not_spawn_a_refund(db_session):
    user, account = _seed(db_session)
    legs = _group(db_session, user, account, ["50.00", "75.00"])
    for leg, amt in zip(legs, (Decimal("50.00"), Decimal("75.00"))):
        leg.settled_on = date.today()
        leg.actual_amount = amt
    db_session.commit()
    client = _client(db_session, user)
    assert client.delete(f"/planned-expenses/{legs[0].id}").status_code == 204
    remaining = db_session.query(models.PlannedExpense).filter(
        models.PlannedExpense.installment_group_id == legs[0].id,
    ).all()
    assert [pe.id for pe in remaining] == [legs[1].id]
    assert not any(pe.is_refund_watch for pe in remaining)

def test_plain_one_off_delete_is_unaffected(db_session):
    user, account = _seed(db_session)
    pe = models.PlannedExpense(
        user_id=user.id, name="Plain", amount=Decimal("10.00"),
        expected_date=date.today(), account_id=account.id,
    )
    db_session.add(pe)
    db_session.commit()
    client = _client(db_session, user)
    assert client.delete(f"/planned-expenses/{pe.id}").status_code == 204
    assert db_session.query(models.PlannedExpense).filter(models.PlannedExpense.id == pe.id).first() is None

def test_refund_watch_settles_through_the_existing_auto_settle_matcher(db_session):
    user, account = _seed(db_session)
    legs = _group(db_session, user, account, ["50.00", "75.00"])
    legs[0].settled_on = date.today()
    legs[0].actual_amount = Decimal("50.00")
    db_session.commit()
    client = _client(db_session, user)
    client.delete(f"/planned-expenses/{legs[0].id}")
    refund = db_session.query(models.PlannedExpense).filter(
        models.PlannedExpense.installment_group_id == legs[0].id,
        models.PlannedExpense.is_refund_watch.is_(True),
    ).one()

    db_session.add(models.AccountPendingTransaction(
        user_id=user.id, account_id=account.id, external_id="refund-1", date=date.today(),
        amount=Decimal("50.00"), description="Dental refund", synced_at=datetime.utcnow(),
    ))
    db_session.commit()

    settlements = auto_settle_planned_expenses(db_session, user.id)
    db_session.commit()
    assert any(s.planned_expense_id == refund.id for s in settlements)
    db_session.refresh(refund)
    assert refund.is_settled
```

`AccountPendingTransaction`'s checking-account sign convention is "negative = money out" (`backend/models.py:637`), so a positive `amount` here is the inflow/credit side the matcher's `is_inflow = row.amount > 0` (`backend/services/planned_auto_settle.py:107`) expects to pair against the refund-watch's `direction=inflow`. Import `datetime` from the `datetime` module alongside the existing `date` import at the top of this test file.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run --locked python -m pytest tests/test_installment_cancellation.py -v`
Expected: FAIL — `cancel_installment_group` doesn't exist, and the delete endpoint doesn't call it yet.

- [ ] **Step 3: Implement `cancel_installment_group`**

```python
def cancel_installment_group(db: Session, user: models.User, expense: models.PlannedExpense) -> None:
```

Query every row sharing `expense.installment_group_id` for this user where `is_refund_watch` is false ("siblings", including `expense` itself). Define "cleared" as `settled_on is not None and actual_amount is not None`. If none of the siblings are uncleared, this group was already fully resolved earlier — detach any `TripItem` link for `expense` (mirror the existing block at `backend/routers/planned_expenses.py:139-145`) and `db.delete(expense)`; return. Otherwise, for every sibling: if cleared, `db.add()` a new `models.PlannedExpense` with `name=f"{sibling.name} — refund expected"`, `amount=sibling.actual_amount`, `expected_date=date.today()`, `direction=models.PlannedDirection.inflow`, `account_id=sibling.account_id`, `card_id=sibling.card_id`, `category_id=sibling.category_id`, `installment_group_id=expense.installment_group_id`, `is_refund_watch=True`; if not cleared, detach its `TripItem` link the same way and `db.delete(sibling)`. `db.flush()` at the end. Does not commit.

- [ ] **Step 4: Wire it into the delete endpoint**

In `backend/routers/planned_expenses.py`, `delete_planned_expense` (currently lines ~135-156): after the existing 404 check, branch:

```python
    if expense.installment_group_id is not None and not expense.is_refund_watch:
        cancel_installment_group(db, user, expense)
    else:
        for item in db.query(models.TripItem).filter(
            models.TripItem.planned_expense_id == expense.id,
            models.TripItem.user_id == user.id,
        ).all():
            item.planned_expense_id = None
        db.flush()
        db.delete(expense)
    db.commit()
```

This replaces the existing unconditional TripItem-detach-then-delete body with the branch above; the `else` arm is that same existing code, unchanged. Import `cancel_installment_group` from `backend.services.installment_plan`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run --locked python -m pytest tests/test_installment_cancellation.py -v`
Expected: PASS

- [ ] **Step 6: Run the full backend test suite with coverage**

Run: `cd backend && uv run --locked python -m pytest -q --cov --cov-report=term:skip-covered`
Expected: all pass, coverage floor in `backend/.coveragerc` still met.

- [ ] **Step 7: Commit**

```bash
git add backend/services/installment_plan.py backend/routers/planned_expenses.py backend/tests/test_installment_cancellation.py
git commit -m "Cancel an installment group on delete and open a refund-watch for any cleared leg"
```

---

## Task 5: Frontend — create a split one-off

**Files:**
- Create: `frontend/src/lib/splitEvenly.ts`
- Create: `frontend/src/lib/splitEvenly.test.ts`
- Modify: `frontend/src/api/index.ts:317-328` (`plannedExpensesApi`)
- Modify: `frontend/src/components/phone/PlanOneOffSheet.tsx`

**Interfaces:**
- Consumes: `plannedExpensesApi` shape (`frontend/src/api/index.ts:317-328`); the existing `accountsApi`/`cardsApi` queries and `options`/`effectivePay` logic already in `PlanOneOffSheet.tsx:30-45`.
- Produces: `splitEvenly(totalDollars: number, count: number): number[]` (pure, exported); `plannedExpensesApi.previewInstallments(accountId: number, data: object)`, `plannedExpensesApi.createInstallments(data: object)`. Nothing later depends on these beyond this task.

- [ ] **Step 1: Write the failing `splitEvenly` test**

```typescript
// frontend/src/lib/splitEvenly.test.ts
import { describe, expect, test } from "bun:test";
import { splitEvenly } from "./splitEvenly";

describe("splitEvenly", () => {
  test("divides evenly with no remainder", () => {
    expect(splitEvenly(90, 3)).toEqual([30, 30, 30]);
  });

  test("puts the extra cents on the first legs, summing to the exact total", () => {
    const result = splitEvenly(100, 3);
    expect(result).toEqual([33.34, 33.33, 33.33]);
    expect(result.reduce((a, b) => a + b, 0)).toBeCloseTo(100, 2);
  });

  test("single leg returns the whole total", () => {
    expect(splitEvenly(42.5, 1)).toEqual([42.5]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && bun test src/lib/splitEvenly.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `splitEvenly`**

```typescript
/** Split `totalDollars` into `count` legs that sum back to the exact total,
 *  working in integer cents so float division can't lose a penny. The first
 *  `totalCents % count` legs each get one extra cent. */
export function splitEvenly(totalDollars: number, count: number): number[] {
  const totalCents = Math.round(totalDollars * 100);
  const base = Math.floor(totalCents / count);
  const remainder = totalCents % count;
  return Array.from({ length: count }, (_, i) => (base + (i < remainder ? 1 : 0)) / 100);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && bun test src/lib/splitEvenly.test.ts`
Expected: PASS

- [ ] **Step 5: Add the two API client functions**

In `frontend/src/api/index.ts`, inside `plannedExpensesApi` (lines 317-328), add:

```typescript
  previewInstallments: (accountId: number, data: object) =>
    api.post("/planned-expenses/installments/preview", data, { params: { account_id: accountId } }).then((r) => r.data),
  createInstallments: (data: object) => api.post("/planned-expenses/installments", data).then((r) => r.data),
```

- [ ] **Step 6: Extend `PlanOneOffSheet.tsx` with a "split into payments" mode**

Add a checkbox/toggle "Split into separate payments". When on, replace the single amount+date pair with:
- A "Total" number input (local state only, never sent to the backend) and a count stepper from 2 to 6 (default 2).
- A "Split evenly" button that calls `splitEvenly(parseFloat(total), count)` and fills `count` editable amount+date inputs with the result; the user may still hand-edit any leg's amount or date afterward (this is how both of Dan's required entry modes coexist: evenly-split is a starting point, not a lock).
- When the toggle is on, the debounced preview query (replacing the existing single-leg `plannedExpensesApi.preview` call) calls `plannedExpensesApi.previewInstallments(previewAccountId, { name, account_id/card_id, legs })` instead, and renders `safety_margin_weekly`/`safety_margin` exactly as today (same before/after line), plus one line per entry in the returned `card_payments` list (reusing the existing single-line markup at `PlanOneOffSheet.tsx:146-150`, repeated).
- The "Add to plan" button calls `plannedExpensesApi.createInstallments(debounced)` instead of `.create()` when the toggle is on.
- The existing single-leg path (toggle off) is completely unchanged — same request shape, same preview call, same submit call.
- Reuse the existing `options`/`effectivePay`/`previewAccountId` logic (`PlanOneOffSheet.tsx:30-67`) unchanged; it already produces the one shared `account_id`/`card_id` both modes need.
- Reuse the existing query-invalidation list in `add`'s `onSuccess` (`PlanOneOffSheet.tsx:81-88`) for the installments mutation too.

This step has no single code block because the exact JSX layout (stepper control, per-leg rows, toggle placement) is a UI judgment call, not a determined interface; the five bullets above are the complete, unambiguous spec of what it must do.

- [ ] **Step 7: Manually verify in the running app**

Start the app per this project's own run method, open "Plan a one-off," toggle "Split into separate payments," enter a total and count, click "Split evenly," confirm the preview updates and sums match, submit, and confirm the resulting rows appear in the Forecast page's planned-expenses list named "... (1 of N)" etc.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/lib/splitEvenly.ts frontend/src/lib/splitEvenly.test.ts frontend/src/api/index.ts frontend/src/components/phone/PlanOneOffSheet.tsx
git commit -m "Add split-into-installments mode to the one-off creation sheet"
```

---

## Task 6: Frontend — delete-cascade warning

**Files:**
- Modify: `frontend/src/pages/Forecast.tsx:1414-1424` (the delete `ConfirmDialog`)

**Interfaces:**
- Consumes: `deleteExpense` state (`Forecast.tsx:103`), already holding the full `PlannedExpenseOut` row including `installment_group_id` once the API returns it (Task 1-4 add it to `schemas.PlannedExpenseOut` implicitly via `from_attributes` — confirm `installment_group_id` and `is_refund_watch` appear on `PlannedExpenseOut`; if Task 1-4 did not add them there, add both as `Optional`/`bool` fields to `schemas.PlannedExpenseOut` in this task before using them here).

- [ ] **Step 1: Add the two fields to `PlannedExpenseOut` if not already present**

Check `backend/schemas.py`'s `PlannedExpenseOut` (~line 1932). If `installment_group_id` and `is_refund_watch` are not already there, add:

```python
    installment_group_id: Optional[int] = None
    is_refund_watch: bool = False
```

- [ ] **Step 2: Update the confirm dialog's description**

In `frontend/src/pages/Forecast.tsx`, change the `description` prop of the delete `ConfirmDialog` (currently line 1419, a single template string) to vary by `deleteExpense?.installment_group_id`:

```typescript
description={
  deleteExpense?.installment_group_id && !deleteExpense?.is_refund_watch
    ? `"${deleteExpense?.name}" is one of a split payment plan. Deleting it cancels every payment in that plan that hasn't happened yet; any payment that already cleared stays as history and a refund will be watched for instead.`
    : `"${deleteExpense?.name}" will be permanently removed from your forecast.`
}
```

- [ ] **Step 3: Manually verify in the running app**

Create a split one-off (Task 5), open the Forecast page's planned-expenses list, click delete on one of the two legs, confirm the warning text above appears instead of the plain one; cancel, then confirm deleting a plain (non-split) one-off still shows the original plain text.

- [ ] **Step 4: Commit**

```bash
git add backend/schemas.py frontend/src/pages/Forecast.tsx
git commit -m "Warn before deleting a leg of a split one-off"
```

---

## Task 7: Decisions log entry

**Files:**
- Modify: `docs/architecture.md` (Decisions log, ~line 298-322)

**Interfaces:** None — documentation only.

- [ ] **Step 1: Add one bullet to the Decisions log**

In the same terse style as its neighbors, at the end of the existing list:

```
- **A one-off can be split into 2-6 dated installments.** One shared name and payment method, each leg clears on its own through the existing auto-settle matcher; deleting any leg cancels every installment that hasn't cleared yet, and opens a cancelable refund-watch for any that already did. No calculation changed -- only what a one-off can be created as and how deleting one behaves.
```

- [ ] **Step 2: Commit**

```bash
git add docs/architecture.md
git commit -m "Record the split one-off installments decision in architecture.md"
```
