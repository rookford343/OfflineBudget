# What-If Scenarios Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a forecast scenario hold proposed new recurring items and proposed one-off expenses, forecast them without persisting anything, and commit an acceptable scenario into real rows with a reversible link back.

**Architecture:** Two new child tables hang off `forecast_scenarios`. A resolver turns a scenario into a frozen `ScenarioProposal` of *transient* SQLAlchemy objects — real `RecurringItem` / `PlannedExpense` instances that are never `db.add()`ed — which `build_forecast` splices into the three lists it already walks. Because a proposal is the same object type in the same loop, `_fires_on`, the weekend pull-forward, end-date handling and card routing apply to it for free. Commit copies proposals into the real tables and records the new row ids so uncommit can reverse it.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (`Mapped` / `mapped_column`), Pydantic v2, pytest, React 18 + TypeScript + TanStack Query + Recharts.

**Spec:** `docs/superpowers/specs/2026-09-20-scenario-what-if-design.md`

## Global Constraints

- **Nothing a scenario proposes may ever persist during a forecast.** Transient objects are never `db.add()`ed. `SessionLocal` runs `autoflush=False` (`backend/database.py:20`), so nothing flushes them implicitly either. Every forecast task carries a row-count assertion.
- **Proposal ids are the negation of the proposal row's own id** (`id=-p.id`). `override_map` and `actual_by_ri` in `forecast_engine.py` are keyed by item id; a positive id would collide with a real item.
- **Card-routed expense proposals go to `card_items_by_card`, never `recurring_items`.** `build_forecast` deliberately excludes card-linked expenses from the checking walk (`forecast_engine.py:296-306`). Putting one in `recurring_items` would charge checking twice.
- **A committed scenario resolves to an EMPTY proposal.** Its items already exist as real rows; resolving them again double-counts.
- **No migration tooling exists in this repo.** New tables and columns go in `backend/database.py`'s `upgrade_schema()` statement list, which swallows "already exists" errors. New tables ALSO need their model class so `Base.metadata.create_all` covers fresh databases.
- **No `npm`/`npx` — this repo uses `bun`.**
- **Commits go straight to `main`.** No branches, no worktrees, no PRs. The `pre-push` hook in `.githooks/` runs the full backend suite.
- **Commit messages describe app behavior only** — never real balances, amounts, or account names. The repo is public.
- **Frontend bar:** no NEW `tsc` errors in touched files, measured before and after. `bun run build` does not exit 0 on this repo for unrelated pre-existing reasons, so compare counts rather than expecting success. Live visual verification is blocked (Interceptor preflight fails on this machine); do not claim it.
- Run the backend suite with `python3 -m pytest backend/tests -q` from the repo root.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/models.py` | `ScenarioProposedItem`, `ScenarioProposedExpense`; new `ForecastScenario` and `ScenarioOverride` columns |
| `backend/database.py` | `CREATE TABLE` / `ALTER TABLE` statements in `upgrade_schema()` |
| `backend/schemas.py` | Pydantic in/out models for proposals, commit result, impact |
| `backend/services/forecast_engine.py` | `ScenarioProposal` dataclass; three splice points; `proposal` kwarg on `build_forecast` / `build_quarters` |
| `backend/services/scenario_service.py` (new) | `resolve_scenario`, `commit_scenario`, `uncommit_scenario`, `scenario_impact` — everything that knows how a scenario becomes real |
| `backend/services/budget_snapshot.py` | `proposal` kwarg threaded to `compute_budget_snapshot`, `_monthly_income`, `_monthly_expenses`, `_lookahead_minimum` |
| `backend/routers/scenarios.py` | proposal CRUD, `/commit`, `/uncommit`, `/impact` |
| `backend/routers/forecast.py` | optional `scenario_id` on `POST /forecast/quarters-scenario` |
| `frontend/src/api/index.ts` | `scenariosApi` additions |
| `frontend/src/lib/navItems.ts`, `frontend/src/App.tsx` | nav entry + route |
| `frontend/src/pages/Scenarios.tsx` (new) | the tab: list, editor, impact strip, chart, commit |

`scenario_service.py` is a separate file rather than more code in `routers/scenarios.py` because commit/uncommit/impact are testable business logic with no HTTP in them, and the router is already 90 lines of CRUD.

---

## Task 1: Data model, DDL, and schemas

**Files:**
- Modify: `backend/models.py` (after `ScenarioOverride`, around line 583)
- Modify: `backend/database.py` (append to `upgrade_schema()`'s `stmts` list, before the closing `]` around line 200)
- Modify: `backend/schemas.py` (the `# ── Forecast Scenarios ──` block, lines 1076-1104)
- Test: `backend/tests/test_scenario_proposals_model.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `models.ScenarioProposedItem`, `models.ScenarioProposedExpense`; `ForecastScenario.status` / `.committed_at` / `.notes` / `.proposed_items` / `.proposed_expenses`; `ScenarioOverride.committed_previous_amount`; `schemas.ScenarioProposedItemCreate/Out`, `ScenarioProposedExpenseCreate/Out`, `ScenarioOut` carrying both lists.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_scenario_proposals_model.py`:

```python
"""The two proposal tables and the columns commit/uncommit need.

A proposal is deliberately NOT a real RecurringItem with a scenario_id flag:
every existing query in forecast_engine, budget_snapshot, summary_generator and
the spending routers would then have to filter `scenario_id IS NULL`, and one
missed filter leaks a hypothetical expense into the daily email and Safety
Margin. Separate tables make that failure impossible rather than unlikely.
"""
from datetime import date
from decimal import Decimal

from backend import models


def _scenario(db):
    user = models.User(username="prop", hashed_password="x", display_name="Prop")
    db.add(user)
    db.flush()
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("1000.00"),
    )
    db.add(account)
    db.flush()
    scenario = models.ForecastScenario(user_id=user.id, name="iPhone + AppleCare")
    db.add(scenario)
    db.commit()
    return user, account, scenario


def test_new_scenario_defaults_to_draft(db_session):
    _user, _account, scenario = _scenario(db_session)
    assert scenario.status == "draft"
    assert scenario.committed_at is None
    assert scenario.notes is None


def test_proposed_item_round_trips_every_field_the_forecast_reads(db_session):
    user, account, scenario = _scenario(db_session)
    db_session.add(models.ScenarioProposedItem(
        scenario_id=scenario.id, name="iPhone Trade-In",
        amount=Decimal("57.87"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=23,
        start_date=date(2026, 10, 23), end_date=date(2028, 10, 23),
        account_id=account.id,
    ))
    db_session.commit()
    db_session.refresh(scenario)

    item = scenario.proposed_items[0]
    assert item.amount == Decimal("57.87")
    assert item.end_date == date(2028, 10, 23)
    assert item.committed_recurring_item_id is None


def test_proposed_expense_round_trips(db_session):
    user, account, scenario = _scenario(db_session)
    db_session.add(models.ScenarioProposedExpense(
        scenario_id=scenario.id, name="New laptop",
        amount=Decimal("2400.00"), expected_date=date(2026, 12, 1),
        account_id=account.id,
    ))
    db_session.commit()
    db_session.refresh(scenario)

    expense = scenario.proposed_expenses[0]
    assert expense.direction == models.PlannedDirection.outflow
    assert expense.committed_planned_expense_id is None


def test_deleting_a_scenario_takes_its_proposals_with_it(db_session):
    user, account, scenario = _scenario(db_session)
    db_session.add_all([
        models.ScenarioProposedItem(
            scenario_id=scenario.id, name="AppleCare", amount=Decimal("199.99"),
            type=models.RecurringType.expense,
            frequency=models.RecurringFrequency.yearly, month_of_year=10,
            day_of_month=23, start_date=date(2026, 10, 23), account_id=account.id,
        ),
        models.ScenarioProposedExpense(
            scenario_id=scenario.id, name="Deposit", amount=Decimal("50.00"),
            expected_date=date(2026, 11, 1), account_id=account.id,
        ),
    ])
    db_session.commit()

    db_session.delete(scenario)
    db_session.commit()

    assert db_session.query(models.ScenarioProposedItem).count() == 0
    assert db_session.query(models.ScenarioProposedExpense).count() == 0


def test_override_can_record_the_amount_it_replaced(db_session):
    user, account, scenario = _scenario(db_session)
    item = models.RecurringItem(
        user_id=user.id, account_id=account.id, name="Dining",
        amount=Decimal("400.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=1,
        start_date=date(2026, 1, 1),
    )
    db_session.add(item)
    db_session.flush()
    override = models.ScenarioOverride(
        scenario_id=scenario.id, recurring_item_id=item.id,
        amount_delta=Decimal("-200.00"),
        committed_previous_amount=Decimal("400.00"),
    )
    db_session.add(override)
    db_session.commit()
    db_session.refresh(override)

    assert override.committed_previous_amount == Decimal("400.00")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest backend/tests/test_scenario_proposals_model.py -q`
Expected: FAIL with `AttributeError: module 'backend.models' has no attribute 'ScenarioProposedItem'`

- [ ] **Step 3: Add the columns to `ForecastScenario` and `ScenarioOverride`**

In `backend/models.py`, replace the `ForecastScenario` class body's tail so it reads:

```python
class ForecastScenario(Base):
    __tablename__ = "forecast_scenarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # "draft" until committed, "committed" after. A plain string rather than a
    # PyEnum because the value round-trips through the API as a string anyway
    # and the existing ALTER-TABLE-based schema upgrades have no enum support.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft", server_default="draft")
    committed_at: Mapped[datetime | None] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="forecast_scenarios")
    overrides: Mapped[list[ScenarioOverride]] = relationship(back_populates="scenario", cascade="all, delete-orphan")
    proposed_items: Mapped[list["ScenarioProposedItem"]] = relationship(
        back_populates="scenario", cascade="all, delete-orphan",
    )
    proposed_expenses: Mapped[list["ScenarioProposedExpense"]] = relationship(
        back_populates="scenario", cascade="all, delete-orphan",
    )
```

Add one column to `ScenarioOverride`, after `amount_delta`:

```python
    # The real item's amount at the moment this scenario was committed.
    # Committing an amount tweak EDITS the real item, so uncommit needs the
    # value it replaced -- a delta alone cannot be reversed safely if the
    # item was edited by hand in between.
    committed_previous_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
```

- [ ] **Step 4: Add the two proposal models**

In `backend/models.py`, immediately after the `ScenarioOverride` class:

```python
class ScenarioProposedItem(Base):
    """A RecurringItem that does not exist yet.

    Mirrors only the fields build_forecast actually reads, so a proposal can be
    materialized into a transient RecurringItem and walked by the same loop as
    a real one -- see forecast_engine.ScenarioProposal. `is_active` and
    `include_in_forecast` are absent on purpose: a proposal that exists is by
    definition both, and storing them would invite a proposal that silently
    does nothing.
    """
    __tablename__ = "scenario_proposed_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scenario_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("forecast_scenarios.id", ondelete="CASCADE"), nullable=False,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    type: Mapped[RecurringType] = mapped_column(SAEnum(RecurringType), nullable=False)
    frequency: Mapped[RecurringFrequency] = mapped_column(
        SAEnum(RecurringFrequency), nullable=False, default=RecurringFrequency.monthly,
    )
    day_of_month: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    month_of_year: Mapped[int | None] = mapped_column(Integer)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False)
    card_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("credit_cards.id"))
    category_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("categories.id"))
    # Set by commit; read by uncommit to find the row it created.
    committed_recurring_item_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("recurring_items.id"),
    )

    scenario: Mapped[ForecastScenario] = relationship(back_populates="proposed_items")


class ScenarioProposedExpense(Base):
    """A PlannedExpense that does not exist yet. See ScenarioProposedItem."""
    __tablename__ = "scenario_proposed_expenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scenario_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("forecast_scenarios.id", ondelete="CASCADE"), nullable=False,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    expected_date: Mapped[date] = mapped_column(Date, nullable=False)
    direction: Mapped[PlannedDirection] = mapped_column(
        SAEnum(PlannedDirection), nullable=False, default=PlannedDirection.outflow,
    )
    account_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("accounts.id"))
    card_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("credit_cards.id"))
    funding_account_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("accounts.id"))
    category_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("categories.id"))
    committed_planned_expense_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("planned_expenses.id"),
    )

    scenario: Mapped[ForecastScenario] = relationship(back_populates="proposed_expenses")
```

`ScenarioProposedItem` references `RecurringType`, `RecurringFrequency`, `SAEnum`, `Date`, and `PlannedDirection`. All five are already imported or defined earlier in `models.py` — confirm with `grep -n "SAEnum\|^class PlannedDirection\|^class RecurringFrequency" backend/models.py` before running the test, and note that `ScenarioProposedExpense` sits AFTER `PlannedDirection`'s definition only if you place these classes after it; if `PlannedDirection` is defined below `ScenarioOverride`, put both new classes at the end of the `# ── Planned Expenses ──` section instead so every name resolves at import time.

- [ ] **Step 5: Add the DDL**

In `backend/database.py`, append these to the `stmts` list in `upgrade_schema()` (immediately before the closing `]`):

```python
        # What-if scenarios: a scenario can now propose items that do not
        # exist yet, and remember what it created so it can be uncommitted.
        "ALTER TABLE forecast_scenarios ADD COLUMN status VARCHAR(16) DEFAULT 'draft'",
        "ALTER TABLE forecast_scenarios ADD COLUMN committed_at DATETIME",
        "ALTER TABLE forecast_scenarios ADD COLUMN notes TEXT",
        "ALTER TABLE scenario_overrides ADD COLUMN committed_previous_amount NUMERIC(14,2)",
        """CREATE TABLE IF NOT EXISTS scenario_proposed_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scenario_id INTEGER NOT NULL REFERENCES forecast_scenarios(id) ON DELETE CASCADE,
            name VARCHAR(128) NOT NULL,
            amount NUMERIC(14,2) NOT NULL,
            type VARCHAR(32) NOT NULL,
            frequency VARCHAR(10) NOT NULL DEFAULT 'monthly',
            day_of_month INTEGER NOT NULL DEFAULT 1,
            month_of_year INTEGER,
            start_date DATE NOT NULL,
            end_date DATE,
            account_id INTEGER NOT NULL REFERENCES accounts(id),
            card_id INTEGER REFERENCES credit_cards(id),
            category_id INTEGER REFERENCES categories(id),
            committed_recurring_item_id INTEGER REFERENCES recurring_items(id)
        )""",
        """CREATE TABLE IF NOT EXISTS scenario_proposed_expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scenario_id INTEGER NOT NULL REFERENCES forecast_scenarios(id) ON DELETE CASCADE,
            name VARCHAR(128) NOT NULL,
            amount NUMERIC(14,2) NOT NULL,
            expected_date DATE NOT NULL,
            direction VARCHAR(8) NOT NULL DEFAULT 'outflow',
            account_id INTEGER REFERENCES accounts(id),
            card_id INTEGER REFERENCES credit_cards(id),
            funding_account_id INTEGER REFERENCES accounts(id),
            category_id INTEGER REFERENCES categories(id),
            committed_planned_expense_id INTEGER REFERENCES planned_expenses(id)
        )""",
```

- [ ] **Step 6: Add the Pydantic schemas**

In `backend/schemas.py`, replace the `# ── Forecast Scenarios ──` block's `ScenarioOut` and add the new models:

```python
class ScenarioProposedItemCreate(BaseModel):
    name: str
    amount: Decimal
    type: str = "expense"
    frequency: str = "monthly"
    day_of_month: int = 1
    month_of_year: Optional[int] = None
    start_date: date
    end_date: Optional[date] = None
    account_id: int
    card_id: Optional[int] = None
    category_id: Optional[int] = None


class ScenarioProposedItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    amount: Decimal
    type: str
    frequency: str
    day_of_month: int
    month_of_year: Optional[int] = None
    start_date: date
    end_date: Optional[date] = None
    account_id: int
    card_id: Optional[int] = None
    category_id: Optional[int] = None
    committed_recurring_item_id: Optional[int] = None


class ScenarioProposedExpenseCreate(BaseModel):
    name: str
    amount: Decimal
    expected_date: date
    direction: str = "outflow"
    account_id: Optional[int] = None
    card_id: Optional[int] = None
    funding_account_id: Optional[int] = None
    category_id: Optional[int] = None


class ScenarioProposedExpenseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    amount: Decimal
    expected_date: date
    direction: str
    account_id: Optional[int] = None
    card_id: Optional[int] = None
    funding_account_id: Optional[int] = None
    category_id: Optional[int] = None
    committed_planned_expense_id: Optional[int] = None


class ScenarioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    status: str
    committed_at: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: datetime
    overrides: list[ScenarioOverrideOut] = []
    proposed_items: list[ScenarioProposedItemOut] = []
    proposed_expenses: list[ScenarioProposedExpenseOut] = []
```

Also add `committed_previous_amount: Optional[Decimal] = None` to `ScenarioOverrideOut`, and `notes: Optional[str] = None` to both `ScenarioCreate` and `ScenarioUpdate`.

`type`, `frequency` and `direction` are typed `str` rather than the enum classes because `ScenarioCreate` and the existing recurring schemas in this file already pass enum values as plain strings, and FastAPI coerces them at the model boundary.

- [ ] **Step 7: Run the test to verify it passes**

Run: `python3 -m pytest backend/tests/test_scenario_proposals_model.py -q`
Expected: 5 passed

- [ ] **Step 8: Run the full suite**

Run: `python3 -m pytest backend/tests -q`
Expected: no NEW failures versus the pre-task baseline. Record the baseline first with the same command on a clean tree.

- [ ] **Step 9: Commit**

```bash
git add backend/models.py backend/database.py backend/schemas.py backend/tests/test_scenario_proposals_model.py
git commit -m "feat: scenario proposal tables for items that do not exist yet

A scenario could previously only express an amount tweak on a recurring
item that already existed. Two new child tables let it propose a new
recurring item or a new one-off expense, each carrying a nullable FK to
whatever it creates on commit so the commit can be reversed.

Separate tables rather than a scenario_id flag on the real tables: a flag
would require every existing query to filter it out, and one missed filter
leaks a hypothetical expense into real spending figures silently."
```

---

## Task 2: `ScenarioProposal` and the checking-walk splice

**Files:**
- Modify: `backend/services/forecast_engine.py` (dataclass near the top imports; splice after the `recurring_items` comprehension at lines 296-306; `proposal` kwarg on `build_forecast` at 278-287 and `build_quarters` at 1376-1382)
- Create: `backend/services/scenario_service.py`
- Test: `backend/tests/test_scenario_proposal_forecast.py`

**Interfaces:**
- Consumes: `models.ScenarioProposedItem`, `models.ScenarioProposedExpense`, `ForecastScenario.status` (Task 1).
- Produces:
  - `forecast_engine.ScenarioProposal` — frozen dataclass, fields `items: tuple[models.RecurringItem, ...] = ()` and `expenses: tuple[models.PlannedExpense, ...] = ()`
  - `build_forecast(..., *, overrides=None, apply_buffer_transfers=True, proposal: ScenarioProposal | None = None)`
  - `build_quarters(db, user_id, account_id, year, overrides=None, precomputed_days=None, proposal: ScenarioProposal | None = None)`
  - `scenario_service.resolve_scenario(db, user_id, scenario_id) -> tuple[list[dict], forecast_engine.ScenarioProposal] | None` — returns `None` when the scenario does not exist or is not the user's

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_scenario_proposal_forecast.py`:

```python
"""A proposed item forecasts exactly as the same item created for real.

That parity is the whole justification for materializing proposals as
transient RecurringItem objects spliced into the lists build_forecast already
walks. The alternative -- a separate "project a proposed item" code path --
would be a second implementation of _fires_on, the weekend pull-forward and
end-date handling, and this repo has spent real time fixing bugs born of
exactly that kind of duplication.
"""
from datetime import date
from decimal import Decimal

from backend import models
from backend.services import scenario_service
from backend.services.forecast_engine import ScenarioProposal, build_forecast


def _seed(db):
    user = models.User(username="prop2", hashed_password="x", display_name="Prop2")
    db.add(user)
    db.flush()
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("5000.00"),
    )
    db.add(account)
    db.flush()
    scenario = models.ForecastScenario(user_id=user.id, name="Test scenario")
    db.add(scenario)
    db.commit()
    return user, account, scenario


def _trace(entries):
    """(date, balance, [(txn name, txn amount)]) per day -- everything a chart
    or an impact figure reads, so an equal trace means an equal forecast."""
    return [
        (e.date, e.projected_balance, [(t.name, t.amount) for t in e.transactions])
        for e in entries
    ]


def test_a_proposal_forecasts_identically_to_the_real_item(db_session):
    user, account, scenario = _seed(db_session)
    fields = dict(
        name="Gym", amount=Decimal("45.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=10,
        start_date=date(2026, 11, 1), account_id=account.id,
    )
    db_session.add(models.ScenarioProposedItem(scenario_id=scenario.id, **fields))
    db_session.commit()

    _overrides, proposal = scenario_service.resolve_scenario(db_session, user.id, scenario.id)
    with_proposal = build_forecast(
        db_session, user.id, account.id, date(2026, 11, 1), date(2027, 2, 28),
        proposal=proposal,
    )

    # Now make it real and forecast with no proposal at all.
    db_session.query(models.ScenarioProposedItem).delete()
    db_session.add(models.RecurringItem(user_id=user.id, **fields))
    db_session.commit()
    as_real = build_forecast(
        db_session, user.id, account.id, date(2026, 11, 1), date(2027, 2, 28),
    )

    assert _trace(with_proposal) == _trace(as_real)


def test_forecasting_a_proposal_persists_nothing(db_session):
    user, account, scenario = _seed(db_session)
    db_session.add(models.ScenarioProposedItem(
        scenario_id=scenario.id, name="Gym", amount=Decimal("45.00"),
        type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=10,
        start_date=date(2026, 11, 1), account_id=account.id,
    ))
    db_session.commit()

    before_items = db_session.query(models.RecurringItem).count()
    before_planned = db_session.query(models.PlannedExpense).count()

    _overrides, proposal = scenario_service.resolve_scenario(db_session, user.id, scenario.id)
    build_forecast(
        db_session, user.id, account.id, date(2026, 11, 1), date(2027, 2, 28),
        proposal=proposal,
    )

    assert db_session.query(models.RecurringItem).count() == before_items
    assert db_session.query(models.PlannedExpense).count() == before_planned


def test_a_proposals_end_date_stops_it(db_session):
    """A 24-month trade-in must not run forever. Occurrences are counted rather
    than date-matched because the weekend pull-forward moves a due date landing
    on a Sat/Sun back to the preceding Friday -- the count is what the end date
    governs, and it is stable regardless of which weekday each month lands on."""
    user, account, scenario = _seed(db_session)
    db_session.add(models.ScenarioProposedItem(
        scenario_id=scenario.id, name="Trade-In", amount=Decimal("57.87"),
        type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=15,
        start_date=date(2026, 11, 15), end_date=date(2027, 1, 15),
        account_id=account.id,
    ))
    db_session.commit()

    _overrides, proposal = scenario_service.resolve_scenario(db_session, user.id, scenario.id)
    entries = build_forecast(
        db_session, user.id, account.id, date(2026, 11, 1), date(2027, 3, 31),
        proposal=proposal,
    )

    hits = [e.date for e in entries for t in e.transactions if t.name == "Trade-In"]
    assert len(hits) == 3, f"Nov/Dec/Jan only, got {hits}"
    assert all(h < date(2027, 2, 1) for h in hits)


def test_a_proposals_id_cannot_collide_with_a_real_item(db_session):
    user, account, scenario = _seed(db_session)
    real = models.RecurringItem(
        user_id=user.id, account_id=account.id, name="Real", amount=Decimal("10.00"),
        type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=5,
        start_date=date(2026, 11, 1),
    )
    db_session.add(real)
    db_session.flush()
    db_session.add(models.ScenarioProposedItem(
        scenario_id=scenario.id, name="Proposed", amount=Decimal("20.00"),
        type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=5,
        start_date=date(2026, 11, 1), account_id=account.id,
    ))
    db_session.commit()

    _overrides, proposal = scenario_service.resolve_scenario(db_session, user.id, scenario.id)
    assert all(item.id < 0 for item in proposal.items)
    assert all(item.id != real.id for item in proposal.items)


def test_a_committed_scenario_resolves_to_nothing(db_session):
    """Its proposals are already real rows. Resolving them again would charge
    the same money twice on every chart that draws the scenario."""
    user, account, scenario = _seed(db_session)
    db_session.add(models.ScenarioProposedItem(
        scenario_id=scenario.id, name="Gym", amount=Decimal("45.00"),
        type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=10,
        start_date=date(2026, 11, 1), account_id=account.id,
    ))
    scenario.status = "committed"
    db_session.commit()

    overrides, proposal = scenario_service.resolve_scenario(db_session, user.id, scenario.id)
    assert proposal == ScenarioProposal()
    assert overrides == []


def test_resolving_another_users_scenario_returns_none(db_session):
    _user, _account, scenario = _seed(db_session)
    other = models.User(username="other", hashed_password="x", display_name="Other")
    db_session.add(other)
    db_session.commit()

    assert scenario_service.resolve_scenario(db_session, other.id, scenario.id) is None


def test_a_proposal_for_a_different_account_is_ignored(db_session):
    user, account, scenario = _seed(db_session)
    savings = models.Account(
        user_id=user.id, name="Savings", type=models.AccountType.savings,
        current_balance=Decimal("100.00"),
    )
    db_session.add(savings)
    db_session.flush()
    db_session.add(models.ScenarioProposedItem(
        scenario_id=scenario.id, name="Savings-only bill", amount=Decimal("99.00"),
        type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=10,
        start_date=date(2026, 11, 1), account_id=savings.id,
    ))
    db_session.commit()

    _overrides, proposal = scenario_service.resolve_scenario(db_session, user.id, scenario.id)
    entries = build_forecast(
        db_session, user.id, account.id, date(2026, 11, 1), date(2026, 11, 30),
        proposal=proposal,
    )

    names = [t.name for e in entries for t in e.transactions]
    assert "Savings-only bill" not in names
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest backend/tests/test_scenario_proposal_forecast.py -q`
Expected: FAIL with `ImportError: cannot import name 'ScenarioProposal' from 'backend.services.forecast_engine'`

- [ ] **Step 3: Add the `ScenarioProposal` dataclass**

In `backend/services/forecast_engine.py`, add `from dataclasses import dataclass` to the imports if absent, and place this just above `def build_forecast`:

```python
@dataclass(frozen=True)
class ScenarioProposal:
    """Transient, never-persisted stand-ins for what a scenario proposes.

    `items` are real RecurringItem instances and `expenses` real
    PlannedExpense instances -- constructed but never db.add()ed -- so
    build_forecast can splice them into the lists it already walks and every
    scheduling rule (_fires_on, the weekend pull-forward, end dates,
    actual-vs-projected suppression) applies to a proposal because it IS the
    same object type in the same loop.

    Each item's id is the NEGATION of its proposal row's id. override_map and
    actual_by_ri are keyed by item id; a positive id could collide with a real
    item and silently apply that item's override, or its actuals, to a
    hypothetical.

    Frozen because build_forecast is a read path -- a proposal it could mutate
    would be a proposal that leaks between the baseline and scenario walks.
    """
    items: tuple["models.RecurringItem", ...] = ()
    expenses: tuple["models.PlannedExpense", ...] = ()
```

- [ ] **Step 4: Add the `proposal` kwarg and the checking splice**

In `build_forecast`'s signature (line 278-287), add the kwarg after `apply_buffer_transfers`:

```python
    proposal: ScenarioProposal | None = None,
```

Immediately after the `recurring_items = [...]` comprehension (which currently ends at line 306 with the card-exclusion `if`), insert:

```python
    # Proposals are spliced into the same lists the real queries produced. The
    # account filter and the card exclusion below mirror the comprehension
    # above exactly: a proposal must be subject to the same routing as the real
    # item it stands in for, or the scenario line diverges from what committing
    # it would actually produce.
    proposal_items = list(proposal.items) if proposal else []
    recurring_items.extend(
        item for item in proposal_items
        if item.account_id == account_id
        and not (item.type == models.RecurringType.expense and item.card_id is not None)
    )
```

In `build_quarters` (line 1376), add `proposal: ScenarioProposal | None = None` as the last parameter and pass `proposal=proposal` to BOTH `build_forecast` calls inside it (the future-year branch around line 1405 and the `else` branch around line 1411).

- [ ] **Step 5: Create the resolver**

Create `backend/services/scenario_service.py`:

```python
"""Turning a stored scenario into something the forecast can walk, and into
real rows when it is accepted.

Kept out of routers/scenarios.py because commit, uncommit and impact are
business logic with real failure modes worth testing without HTTP in the way.
"""
from decimal import Decimal

from sqlalchemy.orm import Session

from backend import models
from backend.services.forecast_engine import ScenarioProposal


def _transient_item(p: models.ScenarioProposedItem, user_id: int) -> models.RecurringItem:
    """A RecurringItem that is never added to the session.

    is_active and include_in_forecast are forced True: _fires_on returns False
    for an inactive item, so a proposal that stored them could silently do
    nothing. A proposal that exists is by definition meant to be forecast.
    """
    return models.RecurringItem(
        id=-p.id,
        user_id=user_id,
        name=p.name,
        amount=p.amount,
        type=p.type,
        frequency=p.frequency,
        day_of_month=p.day_of_month,
        month_of_year=p.month_of_year,
        start_date=p.start_date,
        end_date=p.end_date,
        account_id=p.account_id,
        card_id=p.card_id,
        category_id=p.category_id,
        is_active=True,
        include_in_forecast=True,
    )


def _transient_expense(p: models.ScenarioProposedExpense, user_id: int) -> models.PlannedExpense:
    return models.PlannedExpense(
        id=-p.id,
        user_id=user_id,
        name=p.name,
        amount=p.amount,
        expected_date=p.expected_date,
        direction=p.direction,
        account_id=p.account_id,
        card_id=p.card_id,
        funding_account_id=p.funding_account_id,
        category_id=p.category_id,
    )


def get_scenario(db: Session, user_id: int, scenario_id: int) -> models.ForecastScenario | None:
    return db.query(models.ForecastScenario).filter(
        models.ForecastScenario.id == scenario_id,
        models.ForecastScenario.user_id == user_id,
    ).first()


def resolve_scenario(
    db: Session, user_id: int, scenario_id: int,
) -> tuple[list[dict], ScenarioProposal] | None:
    """(overrides, proposal) for build_forecast, or None if no such scenario.

    A COMMITTED scenario resolves to nothing at all. Its proposals are already
    real rows and its amount tweaks are already applied to real items, so
    resolving them again would count the same money twice on any chart that
    draws it.
    """
    scenario = get_scenario(db, user_id, scenario_id)
    if scenario is None:
        return None
    if scenario.status == "committed":
        return [], ScenarioProposal()

    overrides = [
        {"recurring_item_id": o.recurring_item_id, "amount_delta": o.amount_delta}
        for o in scenario.overrides
    ]
    proposal = ScenarioProposal(
        items=tuple(_transient_item(p, user_id) for p in scenario.proposed_items),
        expenses=tuple(_transient_expense(p, user_id) for p in scenario.proposed_expenses),
    )
    return overrides, proposal
```

`Decimal` is imported for use by the commit logic added in Task 6; leave it in place.

A transient item's `category` and `card` relationships resolve to `None` rather than lazy-loading, because SQLAlchemy does not load relationships on a transient instance. The only consequence is cosmetic — `ForecastTransaction.category_name` is `None` for a proposal (`forecast_engine.py:1053`) — and it is deliberate: assigning a persistent `Category` onto a transient object risks the session pulling that object in on the next flush, which is exactly the persistence this design forbids.

- [ ] **Step 6: Run the test to verify it passes**

Run: `python3 -m pytest backend/tests/test_scenario_proposal_forecast.py -q`
Expected: 7 passed

- [ ] **Step 7: Run the full suite**

Run: `python3 -m pytest backend/tests -q`
Expected: no new failures.

- [ ] **Step 8: Commit**

```bash
git add backend/services/forecast_engine.py backend/services/scenario_service.py backend/tests/test_scenario_proposal_forecast.py
git commit -m "feat: forecast a scenario's proposed recurring items

Proposals are materialized as transient RecurringItem objects and spliced
into the list build_forecast already walks, so end dates, the weekend
pull-forward and actual suppression apply to a proposal because it is the
same object type in the same loop -- no second scheduling implementation.

A parity test asserts a proposed item produces a byte-identical forecast
trace to the same item created for real, and a row-count test asserts
forecasting a scenario persists nothing. A committed scenario resolves to
an empty proposal, since its rows are already real."
```

---

## Task 3: Card-routed proposals

**Files:**
- Modify: `backend/services/forecast_engine.py` (splice after the `card_items_by_card` build, lines 442-445)
- Test: `backend/tests/test_scenario_proposal_card_routing.py`

**Interfaces:**
- Consumes: `ScenarioProposal`, `scenario_service.resolve_scenario` (Task 2).
- Produces: no new names. Behavior only: an expense proposal with a `card_id` lands in `card_items_by_card[card_id]`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_scenario_proposal_card_routing.py`:

```python
"""A card-routed proposal hits the card, not checking.

build_forecast deliberately excludes card-linked expenses from the checking
walk (forecast_engine.py:296-306 -- "CC charges (expense + card_id) hit the
card, not the checking account"). They reach checking through the card's
statement payoff instead. A proposal must take the same path, or a scenario
would show Dan a charge leaving checking a month before it really does.

Card shape here is Dan's real Chase: closes the 28th, due the 25th of the
FOLLOWING month. So a charge on 10/23 belongs to the statement closing 10/28
and is not paid off until 11/25.
"""
from datetime import date
from decimal import Decimal

from backend import models
from backend.services import scenario_service
from backend.services.forecast_engine import build_forecast


def _seed(db, *, monthly_spend_estimate=None):
    user = models.User(username="propcard", hashed_password="x", display_name="PropCard")
    db.add(user)
    db.flush()
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("5000.00"),
    )
    card = models.CreditCard(
        user_id=user.id, name="Apple Card", credit_limit=Decimal("10000.00"),
        statement_day=28, due_day=25,
        monthly_spend_estimate=monthly_spend_estimate,
    )
    db.add_all([account, card])
    db.flush()
    scenario = models.ForecastScenario(user_id=user.id, name="iPhone Duo")
    db.add(scenario)
    db.commit()
    return user, account, card, scenario


def _propose_trade_in(db, scenario, account, card):
    db.add(models.ScenarioProposedItem(
        scenario_id=scenario.id, name="iPhone Trade-In", amount=Decimal("57.87"),
        type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=23,
        start_date=date(2026, 10, 23), end_date=date(2028, 10, 23),
        account_id=account.id, card_id=card.id,
    ))
    db.commit()


def _txn_names(entries, d: date) -> list[str]:
    return [t.name for e in entries if e.date == d for t in e.transactions]


def _balance_on(entries, d: date) -> Decimal:
    return next(e.projected_balance for e in entries if e.date == d)


def test_a_card_routed_proposal_never_appears_in_the_checking_walk(db_session):
    user, account, card, scenario = _seed(db_session)
    _propose_trade_in(db_session, scenario, account, card)

    _overrides, proposal = scenario_service.resolve_scenario(db_session, user.id, scenario.id)
    entries = build_forecast(
        db_session, user.id, account.id, date(2026, 10, 1), date(2026, 11, 30),
        proposal=proposal,
    )

    assert _txn_names(entries, date(2026, 10, 23)) == [], "the charge date must not touch checking"
    assert "iPhone Trade-In" not in [t.name for e in entries for t in e.transactions]


def test_it_reaches_checking_on_the_cards_payoff_date(db_session):
    """Charged 10/23 -> statement closes 10/28 -> due 11/25."""
    user, account, card, scenario = _seed(db_session)
    _propose_trade_in(db_session, scenario, account, card)

    _overrides, proposal = scenario_service.resolve_scenario(db_session, user.id, scenario.id)
    entries = build_forecast(
        db_session, user.id, account.id, date(2026, 10, 1), date(2026, 11, 30),
        proposal=proposal,
    )

    assert _txn_names(entries, date(2026, 11, 25)) == ["CC Estimate: Apple Card"]
    assert _balance_on(entries, date(2026, 11, 25)) == Decimal("4942.13")


def test_a_card_with_a_manual_estimate_swallows_the_proposal_entirely(db_session):
    """A manually-set monthly_spend_estimate wins over subscriptions
    (forecast_engine.py:691-701). So the identical proposal routed to such a
    card changes NOTHING. That is correct existing behavior, but it is
    invisible -- it reads as "the scenario doesn't work" -- which is why the
    proposal form warns about it. This test pins the behavior so the warning
    cannot quietly become untrue."""
    user, account, card, scenario = _seed(db_session, monthly_spend_estimate=Decimal("5500.00"))
    _propose_trade_in(db_session, scenario, account, card)

    _overrides, proposal = scenario_service.resolve_scenario(db_session, user.id, scenario.id)
    window = (date(2026, 10, 1), date(2026, 11, 30))
    with_proposal = build_forecast(db_session, user.id, account.id, *window, proposal=proposal)
    baseline = build_forecast(db_session, user.id, account.id, *window)

    assert [(e.date, e.projected_balance) for e in with_proposal] == \
           [(e.date, e.projected_balance) for e in baseline]


def test_a_card_routed_proposal_persists_nothing(db_session):
    user, account, card, scenario = _seed(db_session)
    _propose_trade_in(db_session, scenario, account, card)
    before = db_session.query(models.RecurringItem).count()

    _overrides, proposal = scenario_service.resolve_scenario(db_session, user.id, scenario.id)
    build_forecast(
        db_session, user.id, account.id, date(2026, 10, 1), date(2026, 11, 30),
        proposal=proposal,
    )

    assert db_session.query(models.RecurringItem).count() == before
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest backend/tests/test_scenario_proposal_card_routing.py -q`
Expected: `test_it_reaches_checking_on_the_cards_payoff_date` FAILS — the payoff date carries no transaction, because nothing put the proposal on the card yet. The two "must not appear in checking" tests pass vacuously at this point; that is fine, they guard the splice you are about to write.

- [ ] **Step 3: Splice card-routed proposals into `card_items_by_card`**

In `backend/services/forecast_engine.py`, immediately after the loop that builds `card_items_by_card` (currently lines 443-445, `for item in card_expense_items: card_items_by_card.setdefault(...)`), insert:

```python
    # Card-routed proposals go HERE, not into recurring_items: the checking
    # walk excludes card-linked expenses on purpose, and this dict is what
    # feeds both the upcoming-cycle accrual and _card_subscription_charges,
    # so a proposal added here reaches checking through the card's payoff --
    # the same path the real item would take.
    for item in proposal_items:
        if (
            item.account_id == account_id
            and item.type == models.RecurringType.expense
            and item.card_id is not None
        ):
            card_items_by_card.setdefault(item.card_id, []).append(item)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m pytest backend/tests/test_scenario_proposal_card_routing.py -q`
Expected: 4 passed

- [ ] **Step 5: Re-run Task 2's tests to confirm the splice did not double-charge**

Run: `python3 -m pytest backend/tests/test_scenario_proposal_forecast.py -q`
Expected: 7 passed. The parity test is the guard here: a card-less proposal must still be spliced exactly once.

- [ ] **Step 6: Run the full suite**

Run: `python3 -m pytest backend/tests -q`
Expected: no new failures.

- [ ] **Step 7: Commit**

```bash
git add backend/services/forecast_engine.py backend/tests/test_scenario_proposal_card_routing.py
git commit -m "feat: route card-linked scenario proposals through the card

An expense proposal with a card_id goes into card_items_by_card, not the
checking walk, matching how a real card-linked recurring item is handled --
it reaches checking on the card's statement payoff date, not its own due
date.

Also pins the behavior of a card carrying a manual monthly spend estimate:
that estimate wins over subscriptions entirely, so a proposal routed to
such a card changes nothing. Correct, but invisible, so the UI warns."
```

---

## Task 4: Proposed one-off expenses

**Files:**
- Modify: `backend/services/forecast_engine.py` (splice after the `planned = db.query(...)` query, lines 381-390, BEFORE the routing loop at 403)
- Test: `backend/tests/test_scenario_proposal_one_offs.py`

**Interfaces:**
- Consumes: `ScenarioProposal.expenses` (Task 2).
- Produces: no new names. Behavior only: proposed expenses join `planned` before the routing loop, so card routing and funding legs apply.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_scenario_proposal_one_offs.py`:

```python
"""A proposed one-off expense takes the same three paths a real one does:
straight to checking, via a card's payoff, or with a funding leg out of
savings. Splicing into `planned` BEFORE build_forecast's routing loop is what
buys all three at once -- routing into planned_by_date directly would
reimplement the loop and lose funding legs silently.
"""
from datetime import date
from decimal import Decimal

from backend import models
from backend.services import scenario_service
from backend.services.forecast_engine import build_forecast


def _seed(db):
    user = models.User(username="propoff", hashed_password="x", display_name="PropOff")
    db.add(user)
    db.flush()
    checking = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("5000.00"),
    )
    savings = models.Account(
        user_id=user.id, name="Savings", type=models.AccountType.savings,
        current_balance=Decimal("20000.00"),
    )
    card = models.CreditCard(
        user_id=user.id, name="Apple Card", credit_limit=Decimal("10000.00"),
        statement_day=28, due_day=25,
    )
    db.add_all([checking, savings, card])
    db.flush()
    scenario = models.ForecastScenario(user_id=user.id, name="One-offs")
    db.add(scenario)
    db.commit()
    return user, checking, savings, card, scenario


def _resolve(db, user, scenario):
    _overrides, proposal = scenario_service.resolve_scenario(db, user.id, scenario.id)
    return proposal


def _balance_on(entries, d: date) -> Decimal:
    return next(e.projected_balance for e in entries if e.date == d)


def test_a_plain_proposed_one_off_hits_checking_on_its_own_date(db_session):
    user, checking, _savings, _card, scenario = _seed(db_session)
    db_session.add(models.ScenarioProposedExpense(
        scenario_id=scenario.id, name="New laptop", amount=Decimal("2400.00"),
        expected_date=date(2026, 11, 10), account_id=checking.id,
    ))
    db_session.commit()

    entries = build_forecast(
        db_session, user.id, checking.id, date(2026, 11, 1), date(2026, 11, 30),
        proposal=_resolve(db_session, user, scenario),
    )

    assert _balance_on(entries, date(2026, 11, 9)) == Decimal("5000.00")
    assert _balance_on(entries, date(2026, 11, 10)) == Decimal("2600.00")


def test_a_card_routed_proposed_one_off_waits_for_the_payoff(db_session):
    """Charged 11/10 -> statement closes 11/28 -> due 12/25."""
    user, checking, _savings, card, scenario = _seed(db_session)
    db_session.add(models.ScenarioProposedExpense(
        scenario_id=scenario.id, name="AppleCare up front", amount=Decimal("199.99"),
        expected_date=date(2026, 11, 10), account_id=checking.id, card_id=card.id,
    ))
    db_session.commit()

    entries = build_forecast(
        db_session, user.id, checking.id, date(2026, 11, 1), date(2026, 12, 31),
        proposal=_resolve(db_session, user, scenario),
    )

    assert _balance_on(entries, date(2026, 11, 10)) == Decimal("5000.00")
    names = [t.name for e in entries if e.date == date(2026, 12, 25) for t in e.transactions]
    assert names == ["AppleCare up front (via Apple Card)"]
    assert _balance_on(entries, date(2026, 12, 25)) == Decimal("4800.01")


def test_a_funded_proposed_one_off_brings_its_transfer_with_it(db_session):
    """funding_account_id implies money moving INTO checking before the
    purchase and OUT of savings -- derived by build_forecast from the expense
    itself, which a proposal gets for free by joining `planned`."""
    user, checking, savings, _card, scenario = _seed(db_session)
    db_session.add(models.ScenarioProposedExpense(
        scenario_id=scenario.id, name="Funded laptop", amount=Decimal("2400.00"),
        expected_date=date(2026, 11, 10), account_id=checking.id,
        funding_account_id=savings.id,
    ))
    db_session.commit()
    proposal = _resolve(db_session, user, scenario)

    checking_entries = build_forecast(
        db_session, user.id, checking.id, date(2026, 11, 1), date(2026, 11, 30),
        proposal=proposal,
    )
    savings_entries = build_forecast(
        db_session, user.id, savings.id, date(2026, 11, 1), date(2026, 11, 30),
        proposal=proposal,
    )

    # Funding arrives and the purchase leaves on the same day (lead 0), so
    # checking nets flat while savings drops.
    assert _balance_on(checking_entries, date(2026, 11, 10)) == Decimal("5000.00")
    assert _balance_on(savings_entries, date(2026, 11, 10)) == Decimal("17600.00")


def test_a_proposed_one_off_outside_the_window_is_ignored(db_session):
    """The real query filters expected_date to the window; a proposal must use
    the same filter or a scenario forecast would diverge from what committing
    it produces."""
    user, checking, _savings, _card, scenario = _seed(db_session)
    db_session.add(models.ScenarioProposedExpense(
        scenario_id=scenario.id, name="Way off", amount=Decimal("2400.00"),
        expected_date=date(2027, 6, 1), account_id=checking.id,
    ))
    db_session.commit()

    entries = build_forecast(
        db_session, user.id, checking.id, date(2026, 11, 1), date(2026, 11, 30),
        proposal=_resolve(db_session, user, scenario),
    )

    assert all(e.projected_balance == Decimal("5000.00") for e in entries)


def test_proposed_one_offs_persist_nothing(db_session):
    user, checking, _savings, _card, scenario = _seed(db_session)
    db_session.add(models.ScenarioProposedExpense(
        scenario_id=scenario.id, name="New laptop", amount=Decimal("2400.00"),
        expected_date=date(2026, 11, 10), account_id=checking.id,
    ))
    db_session.commit()
    before = db_session.query(models.PlannedExpense).count()

    build_forecast(
        db_session, user.id, checking.id, date(2026, 11, 1), date(2026, 11, 30),
        proposal=_resolve(db_session, user, scenario),
    )

    assert db_session.query(models.PlannedExpense).count() == before
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest backend/tests/test_scenario_proposal_one_offs.py -q`
Expected: the first three tests FAIL (balances unchanged from 5000 / 20000, because nothing splices proposed expenses in yet).

- [ ] **Step 3: Splice proposed expenses into `planned`**

In `backend/services/forecast_engine.py`, immediately after the `planned = db.query(models.PlannedExpense)...all()` statement (which ends around line 390) and BEFORE the `funding_by_date` declaration, insert:

```python
    # Spliced in before the routing loop below, not after it: that loop is what
    # derives funding legs and sends card-linked expenses to the card's payoff
    # date instead of their own. Joining `planned` gets a proposal all of it.
    # The window filter mirrors the query above -- without it a proposal
    # outside the window could still route a charge into it, so a scenario
    # forecast would disagree with what committing the scenario produces.
    if proposal:
        planned = planned + [
            pe for pe in proposal.expenses
            if start_date <= pe.expected_date <= end_date
        ]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m pytest backend/tests/test_scenario_proposal_one_offs.py -q`
Expected: 5 passed

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest backend/tests -q`
Expected: no new failures.

- [ ] **Step 6: Commit**

```bash
git add backend/services/forecast_engine.py backend/tests/test_scenario_proposal_one_offs.py
git commit -m "feat: forecast a scenario's proposed one-off expenses

Proposed expenses join the planned-expense list before build_forecast's
routing loop, so card routing and derived funding legs apply to them
exactly as they do to a real planned expense. The same window filter as
the real query is applied, so a scenario forecast matches what committing
the scenario would actually produce."
```

---

## Task 5: Proposal CRUD and scenario-aware forecast endpoint

**Files:**
- Modify: `backend/routers/scenarios.py`
- Modify: `backend/routers/forecast.py:192-204`
- Test: `backend/tests/test_scenario_proposal_api.py`

**Interfaces:**
- Consumes: `schemas.ScenarioProposedItemCreate/Out`, `ScenarioProposedExpenseCreate/Out`, `ScenarioOut` (Task 1); `scenario_service.get_scenario`, `resolve_scenario` (Task 2).
- Produces:
  - `POST /scenarios/{scenario_id}/items` → `ScenarioProposedItemOut` (201)
  - `DELETE /scenarios/{scenario_id}/items/{item_id}` → 204
  - `POST /scenarios/{scenario_id}/expenses` → `ScenarioProposedExpenseOut` (201)
  - `DELETE /scenarios/{scenario_id}/expenses/{expense_id}` → 204
  - `POST /forecast/quarters-scenario` accepting `scenario_id: int | None`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_scenario_proposal_api.py`:

```python
"""Proposal CRUD, and the forecast endpoint resolving a scenario server-side.

The endpoint gains scenario_id rather than making the client assemble
proposals into a request body: the client cannot express a transient
RecurringItem, and duplicating the resolution rules (a committed scenario
resolves to nothing) in TypeScript would be a second place for them to drift.
"""
from datetime import date
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import models
from backend.dependencies import get_db, get_current_user
from backend.routers import scenarios as scenarios_router
from backend.routers import forecast as forecast_router


@pytest.fixture()
def client(db_session):
    user = models.User(username="api", hashed_password="x", display_name="Api")
    db_session.add(user)
    db_session.flush()
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("5000.00"),
    )
    db_session.add(account)
    db_session.flush()
    scenario = models.ForecastScenario(user_id=user.id, name="Test")
    db_session.add(scenario)
    db_session.commit()

    app = FastAPI()
    app.include_router(scenarios_router.router)
    app.include_router(forecast_router.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app), user, account, scenario


def test_post_an_item_then_read_it_back_on_the_scenario(client):
    c, _user, account, scenario = client
    r = c.post(f"/scenarios/{scenario.id}/items", json={
        "name": "iPhone Trade-In", "amount": "57.87", "type": "expense",
        "frequency": "monthly", "day_of_month": 23,
        "start_date": "2026-10-23", "end_date": "2028-10-23",
        "account_id": account.id,
    })
    assert r.status_code == 201, r.text
    assert r.json()["committed_recurring_item_id"] is None

    listed = c.get("/scenarios").json()
    assert [i["name"] for i in listed[0]["proposed_items"]] == ["iPhone Trade-In"]
    assert listed[0]["status"] == "draft"


def test_post_an_expense_then_delete_it(client):
    c, _user, account, scenario = client
    created = c.post(f"/scenarios/{scenario.id}/expenses", json={
        "name": "New laptop", "amount": "2400.00",
        "expected_date": "2026-12-01", "account_id": account.id,
    }).json()

    assert c.delete(f"/scenarios/{scenario.id}/expenses/{created['id']}").status_code == 204
    assert c.get("/scenarios").json()[0]["proposed_expenses"] == []


def test_an_item_on_a_missing_scenario_is_404(client):
    c, _user, account, _scenario = client
    r = c.post("/scenarios/9999/items", json={
        "name": "Nope", "amount": "1.00", "type": "expense", "frequency": "monthly",
        "day_of_month": 1, "start_date": "2026-10-01", "account_id": account.id,
    })
    assert r.status_code == 404


def test_deleting_an_item_belonging_to_another_scenario_is_404(client):
    c, _user, account, scenario = client
    created = c.post(f"/scenarios/{scenario.id}/items", json={
        "name": "Mine", "amount": "1.00", "type": "expense", "frequency": "monthly",
        "day_of_month": 1, "start_date": "2026-10-01", "account_id": account.id,
    }).json()
    other_scenario = c.post("/scenarios", json={"name": "Other"}).json()

    r = c.delete(f"/scenarios/{other_scenario['id']}/items/{created['id']}")
    assert r.status_code == 404


def test_quarters_scenario_resolves_a_scenario_id_server_side(client):
    c, _user, account, scenario = client
    c.post(f"/scenarios/{scenario.id}/items", json={
        "name": "Gym", "amount": "45.00", "type": "expense", "frequency": "monthly",
        "day_of_month": 10, "start_date": "2026-01-10", "account_id": account.id,
    })

    baseline = c.post("/forecast/quarters-scenario", json={
        "account_id": account.id, "year": 2026,
    }).json()
    with_scenario = c.post("/forecast/quarters-scenario", json={
        "account_id": account.id, "year": 2026, "scenario_id": scenario.id,
    }).json()

    assert baseline[3]["close_balance"] != with_scenario[3]["close_balance"]


def test_quarters_scenario_with_an_unknown_scenario_id_is_404(client):
    c, _user, account, _scenario = client
    r = c.post("/forecast/quarters-scenario", json={
        "account_id": account.id, "year": 2026, "scenario_id": 9999,
    })
    assert r.status_code == 404
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest backend/tests/test_scenario_proposal_api.py -q`
Expected: FAIL — `POST /scenarios/{id}/items` returns 405 (no such route).

- [ ] **Step 3: Add proposal CRUD to the scenarios router**

In `backend/routers/scenarios.py`, add the import and the four routes. Replace the import block's first lines with:

```python
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from backend import models, schemas
from backend.dependencies import get_db, get_current_user
from backend.services import scenario_service
```

Then append:

```python
def _owned_scenario(db: Session, user_id: int, scenario_id: int) -> models.ForecastScenario:
    scenario = scenario_service.get_scenario(db, user_id, scenario_id)
    if not scenario:
        raise HTTPException(404, "Scenario not found")
    return scenario


@router.post(
    "/{scenario_id}/items",
    response_model=schemas.ScenarioProposedItemOut,
    status_code=status.HTTP_201_CREATED,
)
def create_proposed_item(
    scenario_id: int,
    body: schemas.ScenarioProposedItemCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    _owned_scenario(db, user.id, scenario_id)
    item = models.ScenarioProposedItem(scenario_id=scenario_id, **body.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{scenario_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_proposed_item(
    scenario_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    _owned_scenario(db, user.id, scenario_id)
    item = db.query(models.ScenarioProposedItem).filter(
        models.ScenarioProposedItem.id == item_id,
        models.ScenarioProposedItem.scenario_id == scenario_id,
    ).first()
    if not item:
        raise HTTPException(404, "Proposed item not found")
    db.delete(item)
    db.commit()


@router.post(
    "/{scenario_id}/expenses",
    response_model=schemas.ScenarioProposedExpenseOut,
    status_code=status.HTTP_201_CREATED,
)
def create_proposed_expense(
    scenario_id: int,
    body: schemas.ScenarioProposedExpenseCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    _owned_scenario(db, user.id, scenario_id)
    expense = models.ScenarioProposedExpense(scenario_id=scenario_id, **body.model_dump())
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return expense


@router.delete("/{scenario_id}/expenses/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_proposed_expense(
    scenario_id: int,
    expense_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    _owned_scenario(db, user.id, scenario_id)
    expense = db.query(models.ScenarioProposedExpense).filter(
        models.ScenarioProposedExpense.id == expense_id,
        models.ScenarioProposedExpense.scenario_id == scenario_id,
    ).first()
    if not expense:
        raise HTTPException(404, "Proposed expense not found")
    db.delete(expense)
    db.commit()
```

Also update `create_scenario` to carry notes: change its body to

```python
    scenario = models.ForecastScenario(user_id=user.id, name=body.name, notes=body.notes)
```

and `update_scenario` to add, after the name assignment:

```python
    if body.notes is not None:
        scenario.notes = body.notes
```

- [ ] **Step 4: Add `scenario_id` to the forecast endpoint**

In `backend/routers/forecast.py`, replace `ScenarioForecastRequest` and `get_quarters_with_scenario` (lines 192-204) with:

```python
class ScenarioForecastRequest(BaseModel):
    account_id: int
    year: int
    # Kept for the existing Forecast page, which assembles overrides itself
    # from the scenario it has already loaded (Forecast.tsx:343-354).
    overrides: list[dict[str, Any]] = []
    # Preferred: let the server resolve the scenario, which is the only side
    # that can build a proposal's transient objects, and the only side that
    # knows a committed scenario resolves to nothing.
    scenario_id: int | None = None


@router.post("/quarters-scenario", response_model=list[schemas.QuarterSummary])
def get_quarters_with_scenario(
    body: ScenarioForecastRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    overrides = body.overrides
    proposal = None
    if body.scenario_id is not None:
        resolved = scenario_service.resolve_scenario(db, user.id, body.scenario_id)
        if resolved is None:
            raise HTTPException(404, "Scenario not found")
        resolved_overrides, proposal = resolved
        # A scenario_id supersedes a client-supplied override list: mixing the
        # two would apply the same delta twice when the client sent both.
        overrides = resolved_overrides
    return build_quarters(
        db, user.id, body.account_id, body.year,
        overrides=overrides, proposal=proposal,
    )
```

Add `from backend.services import scenario_service` to that file's imports, and confirm `HTTPException` is already imported (`grep -n "HTTPException" backend/routers/forecast.py`); add it to the `fastapi` import if not.

- [ ] **Step 5: Run the test to verify it passes**

Run: `python3 -m pytest backend/tests/test_scenario_proposal_api.py -q`
Expected: 6 passed

- [ ] **Step 6: Run the full suite**

Run: `python3 -m pytest backend/tests -q`
Expected: no new failures. `Forecast.tsx`'s existing override-only call still works because `scenario_id` defaults to `None`.

- [ ] **Step 7: Commit**

```bash
git add backend/routers/scenarios.py backend/routers/forecast.py backend/tests/test_scenario_proposal_api.py
git commit -m "feat: proposal CRUD and a scenario-aware quarters endpoint

POST/DELETE for a scenario's proposed items and one-off expenses, and an
optional scenario_id on the quarters endpoint so the server resolves the
scenario rather than asking the client to assemble one. The client cannot
express a transient object, and duplicating the resolution rules in
TypeScript would give them a second place to drift.

The existing override-only request shape is unchanged."
```

---

## Task 6: Commit and uncommit

**Files:**
- Modify: `backend/services/scenario_service.py`
- Modify: `backend/routers/scenarios.py`
- Modify: `backend/schemas.py` (add `ScenarioCommitResult`)
- Test: `backend/tests/test_scenario_commit.py`

**Interfaces:**
- Consumes: everything from Tasks 1-2.
- Produces:
  - `scenario_service.commit_scenario(db, user_id, scenario_id) -> dict` with keys `items_created: int`, `expenses_created: int`, `overrides_applied: int`; raises `ScenarioAlreadyCommitted`
  - `scenario_service.uncommit_scenario(db, user_id, scenario_id) -> dict` with keys `items_removed: int`, `expenses_removed: int`, `overrides_restored: int`; raises `ScenarioNotCommitted`
  - `scenario_service.ScenarioAlreadyCommitted`, `ScenarioNotCommitted` — both `Exception` subclasses
  - `POST /scenarios/{id}/commit` → `schemas.ScenarioCommitResult` (409 if already committed)
  - `POST /scenarios/{id}/uncommit` → `schemas.ScenarioCommitResult` (409 if not committed)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_scenario_commit.py`:

```python
"""Committing a scenario materializes it; uncommitting reverses it.

Uncommit deletes a created row even if it was edited afterward, and those
edits are lost -- decided with Dan 2026-09-20. The alternative (refusing to
uncommit a diverged row) means fingerprinting every created row and explaining
a refusal the user cannot easily resolve. The UI names this on the confirm
dialog.
"""
from datetime import date
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import models
from backend.dependencies import get_db, get_current_user
from backend.routers import scenarios as scenarios_router
from backend.services import scenario_service


@pytest.fixture()
def seeded(db_session):
    user = models.User(username="commit", hashed_password="x", display_name="Commit")
    db_session.add(user)
    db_session.flush()
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("5000.00"),
    )
    db_session.add(account)
    db_session.flush()
    dining = models.RecurringItem(
        user_id=user.id, account_id=account.id, name="Dining",
        amount=Decimal("400.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=1,
        start_date=date(2026, 1, 1),
    )
    db_session.add(dining)
    db_session.flush()
    scenario = models.ForecastScenario(user_id=user.id, name="iPhone Duo")
    db_session.add(scenario)
    db_session.flush()
    db_session.add_all([
        models.ScenarioProposedItem(
            scenario_id=scenario.id, name="iPhone Trade-In", amount=Decimal("57.87"),
            type=models.RecurringType.expense,
            frequency=models.RecurringFrequency.monthly, day_of_month=23,
            start_date=date(2026, 10, 23), end_date=date(2028, 10, 23),
            account_id=account.id,
        ),
        models.ScenarioProposedExpense(
            scenario_id=scenario.id, name="Setup fee", amount=Decimal("35.00"),
            expected_date=date(2026, 10, 23), account_id=account.id,
        ),
        models.ScenarioOverride(
            scenario_id=scenario.id, recurring_item_id=dining.id,
            amount_delta=Decimal("-100.00"),
        ),
    ])
    db_session.commit()
    return db_session, user, account, scenario, dining


def test_commit_creates_real_rows_and_records_the_links(seeded):
    db, user, _account, scenario, _dining = seeded
    result = scenario_service.commit_scenario(db, user.id, scenario.id)

    assert result == {"items_created": 1, "expenses_created": 1, "overrides_applied": 1}

    created = db.query(models.RecurringItem).filter(
        models.RecurringItem.name == "iPhone Trade-In"
    ).one()
    assert created.end_date == date(2028, 10, 23)
    assert created.is_active is True

    proposal = db.query(models.ScenarioProposedItem).one()
    assert proposal.committed_recurring_item_id == created.id

    db.refresh(scenario)
    assert scenario.status == "committed"
    assert scenario.committed_at is not None


def test_commit_applies_an_amount_tweak_and_remembers_the_old_amount(seeded):
    db, user, _account, scenario, dining = seeded
    scenario_service.commit_scenario(db, user.id, scenario.id)

    db.refresh(dining)
    assert dining.amount == Decimal("300.00")
    override = db.query(models.ScenarioOverride).one()
    assert override.committed_previous_amount == Decimal("400.00")


def test_committing_twice_is_refused(seeded):
    db, user, _account, scenario, _dining = seeded
    scenario_service.commit_scenario(db, user.id, scenario.id)

    with pytest.raises(scenario_service.ScenarioAlreadyCommitted):
        scenario_service.commit_scenario(db, user.id, scenario.id)

    assert db.query(models.RecurringItem).filter(
        models.RecurringItem.name == "iPhone Trade-In"
    ).count() == 1


def test_uncommit_removes_exactly_what_it_created(seeded):
    db, user, _account, scenario, dining = seeded
    scenario_service.commit_scenario(db, user.id, scenario.id)

    result = scenario_service.uncommit_scenario(db, user.id, scenario.id)

    assert result == {"items_removed": 1, "expenses_removed": 1, "overrides_restored": 1}
    assert db.query(models.RecurringItem).filter(
        models.RecurringItem.name == "iPhone Trade-In"
    ).count() == 0
    assert db.query(models.PlannedExpense).count() == 0
    # The pre-existing item survives, restored to its original amount.
    db.refresh(dining)
    assert dining.amount == Decimal("400.00")
    proposal = db.query(models.ScenarioProposedItem).one()
    assert proposal.committed_recurring_item_id is None
    db.refresh(scenario)
    assert scenario.status == "draft"
    assert scenario.committed_at is None


def test_uncommit_tolerates_a_row_already_deleted_by_hand(seeded):
    db, user, _account, scenario, _dining = seeded
    scenario_service.commit_scenario(db, user.id, scenario.id)
    created = db.query(models.RecurringItem).filter(
        models.RecurringItem.name == "iPhone Trade-In"
    ).one()
    db.delete(created)
    db.commit()

    result = scenario_service.uncommit_scenario(db, user.id, scenario.id)

    assert result["items_removed"] == 0
    db.refresh(scenario)
    assert scenario.status == "draft"


def test_uncommit_discards_later_edits_to_a_created_row(seeded):
    """Named behavior, not an accident: the row goes even though it changed."""
    db, user, _account, scenario, _dining = seeded
    scenario_service.commit_scenario(db, user.id, scenario.id)
    created = db.query(models.RecurringItem).filter(
        models.RecurringItem.name == "iPhone Trade-In"
    ).one()
    created.amount = Decimal("61.00")
    db.commit()

    scenario_service.uncommit_scenario(db, user.id, scenario.id)

    assert db.query(models.RecurringItem).filter(
        models.RecurringItem.name == "iPhone Trade-In"
    ).count() == 0


def test_uncommitting_a_draft_is_refused(seeded):
    db, user, _account, scenario, _dining = seeded
    with pytest.raises(scenario_service.ScenarioNotCommitted):
        scenario_service.uncommit_scenario(db, user.id, scenario.id)


def test_commit_route_returns_409_on_a_second_call(seeded):
    db, user, _account, scenario, _dining = seeded
    app = FastAPI()
    app.include_router(scenarios_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    c = TestClient(app)

    assert c.post(f"/scenarios/{scenario.id}/commit").status_code == 200
    assert c.post(f"/scenarios/{scenario.id}/commit").status_code == 409
    assert c.post(f"/scenarios/{scenario.id}/uncommit").status_code == 200
    assert c.post(f"/scenarios/{scenario.id}/uncommit").status_code == 409
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest backend/tests/test_scenario_commit.py -q`
Expected: FAIL with `AttributeError: module 'backend.services.scenario_service' has no attribute 'commit_scenario'`

- [ ] **Step 3: Implement commit and uncommit**

Append to `backend/services/scenario_service.py`:

```python
from datetime import datetime


class ScenarioAlreadyCommitted(Exception):
    pass


class ScenarioNotCommitted(Exception):
    pass


def commit_scenario(db: Session, user_id: int, scenario_id: int) -> dict:
    """Materialize a scenario into real rows, recording what it created.

    One transaction: a half-committed scenario would leave proposals whose
    committed_* links point at rows that may or may not exist, which uncommit
    cannot reason about.
    """
    scenario = get_scenario(db, user_id, scenario_id)
    if scenario is None:
        raise LookupError("Scenario not found")
    if scenario.status == "committed":
        raise ScenarioAlreadyCommitted(scenario_id)

    items_created = 0
    for p in scenario.proposed_items:
        item = models.RecurringItem(
            user_id=user_id,
            name=p.name,
            amount=p.amount,
            type=p.type,
            frequency=p.frequency,
            day_of_month=p.day_of_month,
            month_of_year=p.month_of_year,
            start_date=p.start_date,
            end_date=p.end_date,
            account_id=p.account_id,
            card_id=p.card_id,
            category_id=p.category_id,
            is_active=True,
            include_in_forecast=True,
        )
        db.add(item)
        db.flush()
        p.committed_recurring_item_id = item.id
        items_created += 1

    expenses_created = 0
    for p in scenario.proposed_expenses:
        expense = models.PlannedExpense(
            user_id=user_id,
            name=p.name,
            amount=p.amount,
            expected_date=p.expected_date,
            direction=p.direction,
            account_id=p.account_id,
            card_id=p.card_id,
            funding_account_id=p.funding_account_id,
            category_id=p.category_id,
        )
        db.add(expense)
        db.flush()
        p.committed_planned_expense_id = expense.id
        expenses_created += 1

    overrides_applied = 0
    for o in scenario.overrides:
        item = db.query(models.RecurringItem).filter(
            models.RecurringItem.id == o.recurring_item_id,
            models.RecurringItem.user_id == user_id,
        ).first()
        if item is None:
            # The item the tweak referred to is gone. Nothing to apply, and
            # nothing for uncommit to restore -- skipped rather than failing
            # the whole commit over one stale reference.
            continue
        o.committed_previous_amount = item.amount
        item.amount = item.amount + o.amount_delta
        overrides_applied += 1

    scenario.status = "committed"
    scenario.committed_at = datetime.utcnow()
    db.commit()
    return {
        "items_created": items_created,
        "expenses_created": expenses_created,
        "overrides_applied": overrides_applied,
    }


def uncommit_scenario(db: Session, user_id: int, scenario_id: int) -> dict:
    """Reverse a commit: delete the rows it created, restore the amounts it
    changed, clear the links, return the scenario to draft.

    Idempotent about rows already gone -- a row deleted by hand is skipped,
    not an error. Edits made to a created row after commit are LOST: the row
    is deleted regardless. Refusing instead would mean fingerprinting every
    created row and surfacing a refusal the user cannot resolve.
    """
    scenario = get_scenario(db, user_id, scenario_id)
    if scenario is None:
        raise LookupError("Scenario not found")
    if scenario.status != "committed":
        raise ScenarioNotCommitted(scenario_id)

    items_removed = 0
    for p in scenario.proposed_items:
        if p.committed_recurring_item_id is None:
            continue
        item = db.query(models.RecurringItem).filter(
            models.RecurringItem.id == p.committed_recurring_item_id,
            models.RecurringItem.user_id == user_id,
        ).first()
        if item is not None:
            db.delete(item)
            items_removed += 1
        p.committed_recurring_item_id = None

    expenses_removed = 0
    for p in scenario.proposed_expenses:
        if p.committed_planned_expense_id is None:
            continue
        expense = db.query(models.PlannedExpense).filter(
            models.PlannedExpense.id == p.committed_planned_expense_id,
            models.PlannedExpense.user_id == user_id,
        ).first()
        if expense is not None:
            db.delete(expense)
            expenses_removed += 1
        p.committed_planned_expense_id = None

    overrides_restored = 0
    for o in scenario.overrides:
        if o.committed_previous_amount is None:
            continue
        item = db.query(models.RecurringItem).filter(
            models.RecurringItem.id == o.recurring_item_id,
            models.RecurringItem.user_id == user_id,
        ).first()
        if item is not None:
            item.amount = o.committed_previous_amount
            overrides_restored += 1
        o.committed_previous_amount = None

    scenario.status = "draft"
    scenario.committed_at = None
    db.commit()
    return {
        "items_removed": items_removed,
        "expenses_removed": expenses_removed,
        "overrides_restored": overrides_restored,
    }
```

Move the `from datetime import datetime` line up to the file's import block rather than leaving it mid-file.

- [ ] **Step 4: Add the result schema**

In `backend/schemas.py`, after `ScenarioOut`:

```python
class ScenarioCommitResult(BaseModel):
    """Counts only. Both directions use the same shape so the UI has one
    success message to render; the unused keys are zero."""
    items_created: int = 0
    expenses_created: int = 0
    overrides_applied: int = 0
    items_removed: int = 0
    expenses_removed: int = 0
    overrides_restored: int = 0
```

- [ ] **Step 5: Add the two routes**

Append to `backend/routers/scenarios.py`:

```python
@router.post("/{scenario_id}/commit", response_model=schemas.ScenarioCommitResult)
def commit_scenario(
    scenario_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    _owned_scenario(db, user.id, scenario_id)
    try:
        return scenario_service.commit_scenario(db, user.id, scenario_id)
    except scenario_service.ScenarioAlreadyCommitted:
        raise HTTPException(409, "Scenario is already committed")


@router.post("/{scenario_id}/uncommit", response_model=schemas.ScenarioCommitResult)
def uncommit_scenario(
    scenario_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    _owned_scenario(db, user.id, scenario_id)
    try:
        return scenario_service.uncommit_scenario(db, user.id, scenario_id)
    except scenario_service.ScenarioNotCommitted:
        raise HTTPException(409, "Scenario is not committed")
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `python3 -m pytest backend/tests/test_scenario_commit.py -q`
Expected: 8 passed

- [ ] **Step 7: Run the full suite**

Run: `python3 -m pytest backend/tests -q`
Expected: no new failures.

- [ ] **Step 8: Commit**

```bash
git add backend/services/scenario_service.py backend/routers/scenarios.py backend/schemas.py backend/tests/test_scenario_commit.py
git commit -m "feat: commit a scenario into real rows, and uncommit it back

Commit copies proposals into recurring_items and planned_expenses, applies
amount tweaks to the real items, and records both the new row ids and the
amounts it replaced -- so uncommit can delete exactly what it created and
restore exactly what it changed. A second commit is refused rather than
duplicating rows.

Uncommit tolerates a row already deleted by hand, and deliberately
discards edits made to a created row after commit; the alternative is
fingerprinting every row and refusing in a way the user cannot resolve."
```

---

## Task 7: The impact endpoint

**Files:**
- Create: `backend/services/recurring_math.py`
- Modify: `backend/routers/recurring.py:11-27` (the helper moves out)
- Modify: `backend/services/budget_snapshot.py:20-27` (`_monthly_income`), `:30-52` (`_monthly_expenses`), `:141-143` (`_lookahead_minimum`), `:258-263` (`compute_budget_snapshot`)
- Modify: `backend/services/scenario_service.py`
- Modify: `backend/routers/scenarios.py`
- Modify: `backend/schemas.py`
- Test: `backend/tests/test_scenario_impact.py`

**Interfaces:**
- Consumes: `resolve_scenario` (Task 2); the monthly-equivalent helper currently in `routers/recurring.py` (added on `main` in `89cf4b8`).
- Produces:
  - `recurring_math.monthly_equivalent(item) -> Decimal` and `recurring_math.MONTHLY_FACTOR`
  - `compute_budget_snapshot(db, user, account_id, as_of=None, *, proposal=None)`
  - `_lookahead_minimum(db, user_id, account_id, as_of, months=3, *, proposal=None)`
  - `_monthly_income(db, user_id, extra_items=None)`, `_monthly_expenses(db, user_id, as_of, extra_items=None)`
  - `scenario_service.scenario_impact(db, user, account_id, scenario_id) -> dict` with keys `baseline` and `scenario`, each `{"low": Decimal, "low_date": date | None, "safety_margin_weekly": Decimal, "monthly_burn": Decimal}`
  - `GET /scenarios/{id}/impact?account_id=` → `schemas.ScenarioImpact`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_scenario_impact.py`:

```python
"""Baseline vs scenario, in the three figures Dan uses to decide.

The proposal is threaded all the way through compute_budget_snapshot rather
than only into the forecast walk. A half-aware safety margin -- forecast-based
quarter_min responding to the proposal while the flat monthly aggregates did
not -- would print a number that is wrong in a way nobody can see.
"""
from datetime import date
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import models
from backend.dependencies import get_db, get_current_user
from backend.routers import scenarios as scenarios_router
from backend.services import scenario_service
from backend.services.budget_snapshot import compute_budget_snapshot


@pytest.fixture()
def seeded(db_session):
    user = models.User(username="impact", hashed_password="x", display_name="Impact")
    db_session.add(user)
    db_session.flush()
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("5000.00"),
    )
    db_session.add(account)
    db_session.flush()
    scenario = models.ForecastScenario(user_id=user.id, name="iPhone Duo")
    db_session.add(scenario)
    db_session.flush()
    db_session.add(models.ScenarioProposedItem(
        scenario_id=scenario.id, name="iPhone Trade-In", amount=Decimal("57.87"),
        type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=15,
        start_date=date(2026, 1, 15), account_id=account.id,
    ))
    db_session.commit()
    return db_session, user, account, scenario


def test_impact_reports_a_lower_low_and_a_higher_burn_for_the_scenario(seeded):
    db, user, account, scenario = seeded
    result = scenario_service.scenario_impact(db, user, account.id, scenario.id)

    assert result["scenario"]["low"] < result["baseline"]["low"]
    assert result["scenario"]["monthly_burn"] - result["baseline"]["monthly_burn"] \
        == Decimal("57.87")


def test_the_baseline_half_matches_compute_budget_snapshot_exactly(seeded):
    """No second derivation of Safety Margin: the baseline column IS the
    snapshot the Dashboard shows, or the two screens would disagree."""
    db, user, account, scenario = seeded
    result = scenario_service.scenario_impact(db, user, account.id, scenario.id)
    snapshot = compute_budget_snapshot(db, user, account.id)

    assert result["baseline"]["safety_margin_weekly"] == snapshot.safety_margin_weekly


def test_a_proposal_changes_the_snapshots_safety_margin(seeded):
    db, user, account, scenario = seeded
    _overrides, proposal = scenario_service.resolve_scenario(db, user.id, scenario.id)

    baseline = compute_budget_snapshot(db, user, account.id)
    with_proposal = compute_budget_snapshot(db, user, account.id, proposal=proposal)

    assert with_proposal.safety_margin < baseline.safety_margin


def test_impact_does_not_persist_the_proposal(seeded):
    db, user, account, scenario = seeded
    before = db.query(models.RecurringItem).count()
    scenario_service.scenario_impact(db, user, account.id, scenario.id)
    assert db.query(models.RecurringItem).count() == before


def test_impact_route_returns_both_columns(seeded):
    db, user, account, scenario = seeded
    app = FastAPI()
    app.include_router(scenarios_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    c = TestClient(app)

    r = c.get(f"/scenarios/{scenario.id}/impact", params={"account_id": account.id})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"baseline", "scenario"}
    assert set(body["baseline"]) == {
        "low", "low_date", "safety_margin_weekly", "monthly_burn",
    }


def test_impact_on_an_unknown_scenario_is_404(seeded):
    db, user, account, _scenario = seeded
    app = FastAPI()
    app.include_router(scenarios_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    c = TestClient(app)

    r = c.get("/scenarios/9999/impact", params={"account_id": account.id})
    assert r.status_code == 404
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest backend/tests/test_scenario_impact.py -q`
Expected: FAIL with `AttributeError: module 'backend.services.scenario_service' has no attribute 'scenario_impact'`

- [ ] **Step 3: Thread `proposal` through `budget_snapshot.py`**

Four edits in `backend/services/budget_snapshot.py`.

`_monthly_income` — add the parameter and extend the list:

```python
def _monthly_income(
    db: Session, user_id: int,
    extra_items: list[models.RecurringItem] | None = None,
) -> Decimal:
    items = db.query(models.RecurringItem).filter(
        models.RecurringItem.user_id == user_id,
        models.RecurringItem.type == models.RecurringType.income,
        models.RecurringItem.is_active == True,
        models.RecurringItem.frequency == models.RecurringFrequency.monthly,
    ).all()
    # A scenario's proposed items are RecurringItem-shaped and never persisted,
    # so the same filter is applied in Python instead of SQL.
    items = items + [
        i for i in (extra_items or [])
        if i.type == models.RecurringType.income
        and i.frequency == models.RecurringFrequency.monthly
    ]
    return sum((item.amount for item in items), Decimal("0"))
```

`_monthly_expenses` — same shape:

```python
def _monthly_expenses(
    db: Session, user_id: int, as_of: date,
    extra_items: list[models.RecurringItem] | None = None,
) -> Decimal:
```

and immediately after its own `.all()` assignment:

```python
    items = items + [
        i for i in (extra_items or [])
        if i.type == models.RecurringType.expense
    ]
```

`_lookahead_minimum` — add the kwarg and pass it to its `build_forecast` call at line 201:

```python
def _lookahead_minimum(
    db: Session, user_id: int, account_id: int, as_of: date, months: int = 3,
    *, proposal: ScenarioProposal | None = None,
) -> tuple[Decimal, date | None]:
```

```python
    days = build_forecast(db, user_id, account_id, as_of - timedelta(days=45), end, proposal=proposal)
```

Add `ScenarioProposal` to this file's existing `from backend.services.forecast_engine import build_forecast` line.

`compute_budget_snapshot` — add the kwarg and forward it to all three helpers:

```python
def compute_budget_snapshot(
    db: Session,
    user: models.User,
    account_id: int,
    as_of: date | None = None,
    *,
    proposal: ScenarioProposal | None = None,
) -> BudgetSnapshot:
    as_of = as_of or date.today()
    extra_items = list(proposal.items) if proposal else None

    monthly_income = _monthly_income(db, user.id, extra_items)
    monthly_expenses = _monthly_expenses(db, user.id, as_of, extra_items)
```

Then find the `_lookahead_minimum(...)` call in this function and add `proposal=proposal` to it.

Import placement note: `forecast_engine` does not import `budget_snapshot`, so adding `ScenarioProposal` to the existing import creates no cycle.

- [ ] **Step 4a: Move the monthly-equivalent helper out of the router**

`_monthly_equivalent` and `_MONTHLY_FACTOR` currently live in
`backend/routers/recurring.py:16-27`. A service importing from a router is
backwards, so move them into a new `backend/services/recurring_math.py`:

```python
"""What one occurrence of each recurring frequency costs per month on average.

Deliberately NOT the same treatment as budget_snapshot._monthly_expenses,
which charges a yearly bill in full in the month it lands to reconcile with
the spreadsheet's Leftover row. This is the "what does my life cost per
month" figure, so a yearly bill is a twelfth of itself.

Lives here rather than in routers/recurring.py so both the /recurring/breakdown
endpoint and the scenario impact figures read the same helper -- the two
screens then agree by construction, not because two implementations happen to
round the same way.
"""
from decimal import Decimal, ROUND_HALF_UP

from backend import models

MONTHLY_FACTOR = {
    models.RecurringFrequency.monthly: Decimal(1),
    models.RecurringFrequency.quarterly: Decimal(1) / Decimal(3),
    models.RecurringFrequency.yearly: Decimal(1) / Decimal(12),
    models.RecurringFrequency.weekly: Decimal(52) / Decimal(12),
    models.RecurringFrequency.biweekly: Decimal(26) / Decimal(12),
}


def monthly_equivalent(item) -> Decimal:
    """`item` is any object with `.amount` and `.frequency` -- a real
    RecurringItem or a transient one built from a scenario proposal."""
    factor = MONTHLY_FACTOR.get(item.frequency, Decimal(1))
    return (item.amount * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
```

In `backend/routers/recurring.py`, delete the `_MONTHLY_FACTOR` dict and the
`_monthly_equivalent` function (lines 11-27, keeping the `ROUND_HALF_UP`
import only if still used elsewhere in that file — it is not, so drop it from
the `decimal` import too) and add:

```python
from backend.services.recurring_math import monthly_equivalent as _monthly_equivalent
```

The alias keeps `get_breakdown`'s existing call site unchanged. No test imports
either name directly (verified: `grep -rn "_monthly_equivalent\|_MONTHLY_FACTOR" backend/`
matches only `routers/recurring.py`), so nothing else needs touching.

Run `python3 -m pytest backend/tests/test_recurring_breakdown.py -q` — expected: still passing.

- [ ] **Step 4b: Implement `scenario_impact`**

Append to `backend/services/scenario_service.py`:

```python
from backend.services.budget_snapshot import compute_budget_snapshot
from backend.services.recurring_math import monthly_equivalent


def _monthly_burn(db: Session, user_id: int, extra_items: list) -> Decimal:
    """Ongoing monthly cost of every active expense item, proposals included.

    Reuses recurring_math.monthly_equivalent -- the same helper
    /recurring/breakdown uses -- so this figure and the Recurring page's
    Ongoing-vs-Temporary card agree by construction rather than by two
    implementations happening to round the same way.
    """
    items = db.query(models.RecurringItem).filter(
        models.RecurringItem.user_id == user_id,
        models.RecurringItem.is_active == True,
        models.RecurringItem.type == models.RecurringType.expense,
    ).all()
    total = Decimal("0")
    for item in items + [i for i in extra_items if i.type == models.RecurringType.expense]:
        total += monthly_equivalent(item)
    return total


def _impact_column(db, user, account_id, proposal) -> dict:
    snapshot = compute_budget_snapshot(db, user, account_id, proposal=proposal)
    extra_items = list(proposal.items) if proposal else []
    return {
        "low": snapshot.lookahead_minimum,
        "low_date": snapshot.lookahead_minimum_date,
        "safety_margin_weekly": snapshot.safety_margin_weekly,
        "monthly_burn": _monthly_burn(db, user.id, extra_items),
    }


def scenario_impact(db: Session, user: models.User, account_id: int, scenario_id: int) -> dict:
    """Baseline and scenario side by side. Raises LookupError if no scenario."""
    resolved = resolve_scenario(db, user.id, scenario_id)
    if resolved is None:
        raise LookupError("Scenario not found")
    _overrides, proposal = resolved
    return {
        "baseline": _impact_column(db, user, account_id, None),
        "scenario": _impact_column(db, user, account_id, proposal),
    }
```

`snapshot.lookahead_minimum`, `snapshot.lookahead_minimum_date` and
`snapshot.safety_margin_weekly` are the real `BudgetSnapshot` field names
(`budget_snapshot.py:473-476`) — verified, not assumed.

- [ ] **Step 5: Add the impact schema and route**

In `backend/schemas.py`, after `ScenarioCommitResult`:

```python
class ScenarioImpactColumn(BaseModel):
    low: Decimal
    low_date: Optional[date] = None
    safety_margin_weekly: Decimal
    monthly_burn: Decimal


class ScenarioImpact(BaseModel):
    baseline: ScenarioImpactColumn
    scenario: ScenarioImpactColumn
```

In `backend/routers/scenarios.py`:

```python
@router.get("/{scenario_id}/impact", response_model=schemas.ScenarioImpact)
def get_scenario_impact(
    scenario_id: int,
    account_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    _owned_scenario(db, user.id, scenario_id)
    return scenario_service.scenario_impact(db, user, account_id, scenario_id)
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `python3 -m pytest backend/tests/test_scenario_impact.py -q`
Expected: 6 passed

- [ ] **Step 7: Run the full suite**

Run: `python3 -m pytest backend/tests -q`
Expected: no new failures. `compute_budget_snapshot`'s new parameter is keyword-only with a default, so every existing caller is unaffected.

- [ ] **Step 8: Commit**

```bash
git add backend/services/recurring_math.py backend/routers/recurring.py backend/services/budget_snapshot.py backend/services/scenario_service.py backend/routers/scenarios.py backend/schemas.py backend/tests/test_scenario_impact.py
git commit -m "feat: baseline-vs-scenario impact figures

GET /scenarios/{id}/impact returns the three-month low and its date, the
weekly safety margin, and ongoing monthly burn for baseline and scenario
side by side.

The proposal is threaded through compute_budget_snapshot's flat monthly
aggregates as well as its forecast walk, so the safety margin is fully
scenario-aware. A half-aware margin would print a number that is wrong in
a way nobody can see. Monthly burn reuses the recurring breakdown's
monthly-equivalent helper so the two screens agree by construction."
```

---

## Task 8: The Scenarios tab — list and editor

**Files:**
- Modify: `frontend/src/api/index.ts:259-268`
- Modify: `frontend/src/lib/navItems.ts:1-6, 40-45`
- Modify: `frontend/src/App.tsx` (import block and the route list around line 47)
- Create: `frontend/src/pages/Scenarios.tsx`
- Test: none — this repo has no frontend test suite. The bar is no new `tsc` errors in touched files.

**Interfaces:**
- Consumes: every backend route from Tasks 5-7.
- Produces: `scenariosApi.createItem/removeItem/createExpense/removeExpense/commit/uncommit/impact`; the `/scenarios` route.

- [ ] **Step 1: Record the pre-change TypeScript error baseline**

Run: `cd frontend && bunx tsc --noEmit 2>&1 | tee /tmp/tsc-before.txt | tail -3`

Note the total count. This repo does not compile clean; the bar is "no NEW errors in files this task touches", not zero.

- [ ] **Step 2: Extend the API client**

In `frontend/src/api/index.ts`, replace the `scenariosApi` object with:

```ts
export const scenariosApi = {
  list: () => api.get("/scenarios").then((r) => r.data),
  create: (data: object) => api.post("/scenarios", data).then((r) => r.data),
  update: (id: number, data: object) => api.patch(`/scenarios/${id}`, data).then((r) => r.data),
  remove: (id: number) => api.delete(`/scenarios/${id}`),
  createOverride: (scenarioId: number, data: object) =>
    api.post(`/scenarios/${scenarioId}/overrides`, data).then((r) => r.data),
  removeOverride: (scenarioId: number, overrideId: number) =>
    api.delete(`/scenarios/${scenarioId}/overrides/${overrideId}`),
  createItem: (scenarioId: number, data: object) =>
    api.post(`/scenarios/${scenarioId}/items`, data).then((r) => r.data),
  removeItem: (scenarioId: number, itemId: number) =>
    api.delete(`/scenarios/${scenarioId}/items/${itemId}`),
  createExpense: (scenarioId: number, data: object) =>
    api.post(`/scenarios/${scenarioId}/expenses`, data).then((r) => r.data),
  removeExpense: (scenarioId: number, expenseId: number) =>
    api.delete(`/scenarios/${scenarioId}/expenses/${expenseId}`),
  commit: (scenarioId: number) =>
    api.post(`/scenarios/${scenarioId}/commit`).then((r) => r.data),
  uncommit: (scenarioId: number) =>
    api.post(`/scenarios/${scenarioId}/uncommit`).then((r) => r.data),
  impact: (scenarioId: number, accountId: number) =>
    api.get(`/scenarios/${scenarioId}/impact`, { params: { account_id: accountId } })
      .then((r) => r.data),
};
```

- [ ] **Step 3: Add the nav entry and route**

In `frontend/src/lib/navItems.ts`, add `FlaskConical` to the `lucide-react` import list, and add one item to the `planning` group's `items` array, after Forecast:

```ts
      { to: "/scenarios", icon: FlaskConical, label: "Scenarios" },
```

`FlaskConical` is not already imported in this file — the spec requires an icon not already in use there.

In `frontend/src/App.tsx`, add `import Scenarios from "./pages/Scenarios";` to the import block and this route after the `forecast` route:

```tsx
          <Route path="scenarios" element={<Scenarios />} />
```

- [ ] **Step 4: Create the page with its list and editor**

Create `frontend/src/pages/Scenarios.tsx`:

```tsx
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { FlaskConical, Plus, Trash2, CalendarClock } from "lucide-react";
import { scenariosApi, accountsApi, cardsApi, recurringApi } from "../api";

type Scenario = {
  id: number;
  name: string;
  status: string;
  committed_at: string | null;
  notes: string | null;
  created_at: string;
  overrides: { id: number; recurring_item_id: number; amount_delta: string }[];
  proposed_items: {
    id: number; name: string; amount: string; type: string; frequency: string;
    day_of_month: number; month_of_year: number | null; start_date: string;
    end_date: string | null; account_id: number; card_id: number | null;
  }[];
  proposed_expenses: {
    id: number; name: string; amount: string; expected_date: string;
    direction: string; account_id: number | null; card_id: number | null;
  }[];
};

const money = (v: string | number) =>
  `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

export default function Scenarios() {
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [newName, setNewName] = useState("");

  const { data: scenarios = [] } = useQuery<Scenario[]>({
    queryKey: ["scenarios"],
    queryFn: scenariosApi.list,
  });
  const { data: accounts = [] } = useQuery<any[]>({
    queryKey: ["accounts"],
    queryFn: accountsApi.list,
  });
  const { data: cards = [] } = useQuery<any[]>({
    queryKey: ["cards"],
    queryFn: cardsApi.list,
  });
  const { data: recurring = [] } = useQuery<any[]>({
    queryKey: ["recurring"],
    queryFn: () => recurringApi.list(),
  });

  const selected = scenarios.find((s) => s.id === selectedId) ?? null;
  const committed = selected?.status === "committed";
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["scenarios"] });
    qc.invalidateQueries({ queryKey: ["scenario-impact"] });
  };

  const createScenario = useMutation({
    mutationFn: () => scenariosApi.create({ name: newName.trim() }),
    onSuccess: (s: Scenario) => { setNewName(""); setSelectedId(s.id); invalidate(); },
  });
  const removeScenario = useMutation({
    mutationFn: (id: number) => scenariosApi.remove(id),
    onSuccess: () => { setSelectedId(null); invalidate(); },
  });
  const addItem = useMutation({
    mutationFn: (data: object) => scenariosApi.createItem(selected!.id, data),
    onSuccess: invalidate,
  });
  const dropItem = useMutation({
    mutationFn: (itemId: number) => scenariosApi.removeItem(selected!.id, itemId),
    onSuccess: invalidate,
  });
  const addExpense = useMutation({
    mutationFn: (data: object) => scenariosApi.createExpense(selected!.id, data),
    onSuccess: invalidate,
  });
  const dropExpense = useMutation({
    mutationFn: (id: number) => scenariosApi.removeExpense(selected!.id, id),
    onSuccess: invalidate,
  });
  const addOverride = useMutation({
    mutationFn: (data: object) => scenariosApi.createOverride(selected!.id, data),
    onSuccess: invalidate,
  });
  const dropOverride = useMutation({
    mutationFn: (id: number) => scenariosApi.removeOverride(selected!.id, id),
    onSuccess: invalidate,
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <FlaskConical className="w-5 h-5" />
        <h1 className="text-xl font-semibold">Scenarios</h1>
      </div>

      <div className="card p-4 space-y-3">
        <h2 className="font-medium">Your scenarios</h2>
        <div className="flex flex-wrap gap-2">
          {scenarios.map((s) => (
            <button
              key={s.id}
              onClick={() => setSelectedId(s.id)}
              className={`px-3 py-1.5 rounded border text-sm ${
                s.id === selectedId ? "border-blue-500 font-medium" : "border-gray-300"
              }`}
            >
              {s.name}
              {s.status === "committed" && (
                <span className="ml-2 text-xs px-1.5 py-0.5 rounded bg-green-100 text-green-800">
                  committed
                </span>
              )}
            </button>
          ))}
          {scenarios.length === 0 && (
            <p className="text-sm text-gray-500">
              No scenarios yet. Create one to test a change before it is real.
            </p>
          )}
        </div>
        <div className="flex gap-2">
          <input
            className="input"
            placeholder="New scenario name"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
          />
          <button
            className="btn"
            disabled={!newName.trim()}
            onClick={() => createScenario.mutate()}
          >
            <Plus className="w-4 h-4" /> Create
          </button>
          {selected && (
            <button className="btn" onClick={() => removeScenario.mutate(selected.id)}>
              <Trash2 className="w-4 h-4" /> Delete
            </button>
          )}
        </div>
      </div>

      {selected && (
        <>
          <ProposedItemsSection
            scenario={selected}
            accounts={accounts}
            cards={cards}
            disabled={committed}
            onAdd={(data) => addItem.mutate(data)}
            onDrop={(id) => dropItem.mutate(id)}
          />
          <ProposedExpensesSection
            scenario={selected}
            accounts={accounts}
            cards={cards}
            disabled={committed}
            onAdd={(data) => addExpense.mutate(data)}
            onDrop={(id) => dropExpense.mutate(id)}
          />
          <OverridesSection
            scenario={selected}
            recurring={recurring}
            disabled={committed}
            onAdd={(data) => addOverride.mutate(data)}
            onDrop={(id) => dropOverride.mutate(id)}
          />
        </>
      )}
    </div>
  );
}

function ProposedItemsSection({ scenario, accounts, cards, disabled, onAdd, onDrop }: {
  scenario: Scenario; accounts: any[]; cards: any[]; disabled: boolean;
  onAdd: (data: object) => void; onDrop: (id: number) => void;
}) {
  const [form, setForm] = useState({
    name: "", amount: "", type: "expense", frequency: "monthly",
    day_of_month: "1", month_of_year: "", start_date: "", end_date: "",
    account_id: "", card_id: "",
  });
  const set = (k: string, v: string) => setForm({ ...form, [k]: v });

  // A card carrying a manual monthly spend estimate ignores its subscriptions
  // entirely, so a proposal routed to it changes nothing at all. Correct
  // existing behavior, but invisible -- it reads as "the scenario is broken".
  const chosenCard = cards.find((c) => String(c.id) === form.card_id);
  const estimateWarning =
    form.type === "expense" && chosenCard && Number(chosenCard.monthly_spend_estimate ?? 0) > 0;

  const ready = form.name.trim() && form.amount && form.start_date && form.account_id;

  return (
    <div className="card p-4 space-y-3">
      <h2 className="font-medium">Proposed recurring items</h2>
      {scenario.proposed_items.length === 0 && (
        <p className="text-sm text-gray-500">Nothing proposed yet.</p>
      )}
      <ul className="divide-y">
        {scenario.proposed_items.map((i) => (
          <li key={i.id} className="py-2 flex items-center justify-between text-sm">
            <span>
              {i.name} — {money(i.amount)} {i.frequency}
              {i.end_date && (
                <span className="ml-2 inline-flex items-center gap-1 text-xs text-amber-700">
                  <CalendarClock className="w-3 h-3" /> ends {i.end_date}
                </span>
              )}
            </span>
            {!disabled && (
              <button className="btn-sm" onClick={() => onDrop(i.id)}>
                <Trash2 className="w-4 h-4" />
              </button>
            )}
          </li>
        ))}
      </ul>

      {!disabled && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          <input className="input" placeholder="Name" value={form.name}
                 onChange={(e) => set("name", e.target.value)} />
          <input className="input" placeholder="Amount" value={form.amount}
                 onChange={(e) => set("amount", e.target.value)} />
          <select className="input" value={form.type} onChange={(e) => set("type", e.target.value)}>
            <option value="expense">Expense</option>
            <option value="income">Income</option>
          </select>
          <select className="input" value={form.frequency}
                  onChange={(e) => set("frequency", e.target.value)}>
            <option value="monthly">Monthly</option>
            <option value="yearly">Yearly</option>
            <option value="quarterly">Quarterly</option>
            <option value="weekly">Weekly</option>
            <option value="biweekly">Biweekly</option>
          </select>
          <input className="input" type="number" placeholder="Day of month"
                 value={form.day_of_month} onChange={(e) => set("day_of_month", e.target.value)} />
          <input className="input" type="number" placeholder="Month (yearly/qtr)"
                 value={form.month_of_year} onChange={(e) => set("month_of_year", e.target.value)} />
          <input className="input" type="date" value={form.start_date}
                 onChange={(e) => set("start_date", e.target.value)} />
          <input className="input" type="date" placeholder="End date"
                 value={form.end_date} onChange={(e) => set("end_date", e.target.value)} />
          <select className="input" value={form.account_id}
                  onChange={(e) => set("account_id", e.target.value)}>
            <option value="">Account…</option>
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
          <select className="input" value={form.card_id}
                  onChange={(e) => set("card_id", e.target.value)}>
            <option value="">No card (hits checking)</option>
            {cards.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <button
            className="btn col-span-2"
            disabled={!ready}
            onClick={() => onAdd({
              name: form.name.trim(),
              amount: form.amount,
              type: form.type,
              frequency: form.frequency,
              day_of_month: parseInt(form.day_of_month || "1", 10),
              month_of_year: form.month_of_year ? parseInt(form.month_of_year, 10) : null,
              start_date: form.start_date,
              end_date: form.end_date || null,
              account_id: parseInt(form.account_id, 10),
              card_id: form.card_id ? parseInt(form.card_id, 10) : null,
            })}
          >
            <Plus className="w-4 h-4" /> Add proposed item
          </button>
        </div>
      )}

      {estimateWarning && (
        <p className="text-sm text-amber-700">
          {chosenCard.name} has a manual monthly spend estimate of{" "}
          {money(chosenCard.monthly_spend_estimate)}, and that estimate governs the
          forecast instead of the card's individual charges. A proposal routed here
          will not change the forecast. Clear the card's estimate, or pick a card
          without one, to see this item's effect.
        </p>
      )}
    </div>
  );
}

function ProposedExpensesSection({ scenario, accounts, cards, disabled, onAdd, onDrop }: {
  scenario: Scenario; accounts: any[]; cards: any[]; disabled: boolean;
  onAdd: (data: object) => void; onDrop: (id: number) => void;
}) {
  const [form, setForm] = useState({
    name: "", amount: "", expected_date: "", direction: "outflow",
    account_id: "", card_id: "", funding_account_id: "",
  });
  const set = (k: string, v: string) => setForm({ ...form, [k]: v });
  const ready = form.name.trim() && form.amount && form.expected_date;

  return (
    <div className="card p-4 space-y-3">
      <h2 className="font-medium">Proposed one-off expenses</h2>
      {scenario.proposed_expenses.length === 0 && (
        <p className="text-sm text-gray-500">Nothing proposed yet.</p>
      )}
      <ul className="divide-y">
        {scenario.proposed_expenses.map((e) => (
          <li key={e.id} className="py-2 flex items-center justify-between text-sm">
            <span>{e.name} — {money(e.amount)} on {e.expected_date}</span>
            {!disabled && (
              <button className="btn-sm" onClick={() => onDrop(e.id)}>
                <Trash2 className="w-4 h-4" />
              </button>
            )}
          </li>
        ))}
      </ul>

      {!disabled && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          <input className="input" placeholder="Name" value={form.name}
                 onChange={(e) => set("name", e.target.value)} />
          <input className="input" placeholder="Amount" value={form.amount}
                 onChange={(e) => set("amount", e.target.value)} />
          <input className="input" type="date" value={form.expected_date}
                 onChange={(e) => set("expected_date", e.target.value)} />
          <select className="input" value={form.direction}
                  onChange={(e) => set("direction", e.target.value)}>
            <option value="outflow">Money out</option>
            <option value="inflow">Money in</option>
          </select>
          <select className="input" value={form.account_id}
                  onChange={(e) => set("account_id", e.target.value)}>
            <option value="">Any account</option>
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
          <select className="input" value={form.card_id}
                  onChange={(e) => set("card_id", e.target.value)}>
            <option value="">No card</option>
            {cards.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <select className="input" value={form.funding_account_id}
                  onChange={(e) => set("funding_account_id", e.target.value)}>
            <option value="">No funding transfer</option>
            {accounts.map((a) => <option key={a.id} value={a.id}>Fund from {a.name}</option>)}
          </select>
          <button
            className="btn"
            disabled={!ready}
            onClick={() => onAdd({
              name: form.name.trim(),
              amount: form.amount,
              expected_date: form.expected_date,
              direction: form.direction,
              account_id: form.account_id ? parseInt(form.account_id, 10) : null,
              card_id: form.card_id ? parseInt(form.card_id, 10) : null,
              funding_account_id: form.funding_account_id
                ? parseInt(form.funding_account_id, 10) : null,
            })}
          >
            <Plus className="w-4 h-4" /> Add one-off
          </button>
        </div>
      )}
    </div>
  );
}

function OverridesSection({ scenario, recurring, disabled, onAdd, onDrop }: {
  scenario: Scenario; recurring: any[]; disabled: boolean;
  onAdd: (data: object) => void; onDrop: (id: number) => void;
}) {
  const [itemId, setItemId] = useState("");
  const [delta, setDelta] = useState("");
  const nameOf = (id: number) => recurring.find((r) => r.id === id)?.name ?? `#${id}`;

  return (
    <div className="card p-4 space-y-3">
      <h2 className="font-medium">Amount tweaks on existing items</h2>
      {scenario.overrides.length === 0 && (
        <p className="text-sm text-gray-500">No tweaks yet.</p>
      )}
      <ul className="divide-y">
        {scenario.overrides.map((o) => (
          <li key={o.id} className="py-2 flex items-center justify-between text-sm">
            <span>{nameOf(o.recurring_item_id)} — {money(o.amount_delta)} change</span>
            {!disabled && (
              <button className="btn-sm" onClick={() => onDrop(o.id)}>
                <Trash2 className="w-4 h-4" />
              </button>
            )}
          </li>
        ))}
      </ul>
      {!disabled && (
        <div className="flex flex-wrap gap-2">
          <select className="input" value={itemId} onChange={(e) => setItemId(e.target.value)}>
            <option value="">Recurring item…</option>
            {recurring.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </select>
          <input className="input" placeholder="Change (e.g. -200)" value={delta}
                 onChange={(e) => setDelta(e.target.value)} />
          <button
            className="btn"
            disabled={!itemId || !delta}
            onClick={() => {
              onAdd({ recurring_item_id: parseInt(itemId, 10), amount_delta: delta });
              setItemId(""); setDelta("");
            }}
          >
            <Plus className="w-4 h-4" /> Add tweak
          </button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Confirm the imports this page assumes actually exist**

Run: `grep -n "export const accountsApi\|export const cardsApi\|export const recurringApi" frontend/src/api/index.ts`

All three must be present. If `recurringApi.list` takes no argument in this repo, drop the `()` argument in the query function. Also confirm the `btn`, `btn-sm`, `input` and `card` utility classes exist with `grep -rn "\.btn-sm\|\.btn\b\|\.input\b" frontend/src/index.css`; if `btn-sm` is absent, use `btn` for the delete buttons rather than inventing a class.

- [ ] **Step 6: Check for new TypeScript errors**

Run: `cd frontend && bunx tsc --noEmit 2>&1 | tee /tmp/tsc-after.txt | tail -3`
Then: `diff <(grep -oE "^[^(]+" /tmp/tsc-before.txt | sort -u) <(grep -oE "^[^(]+" /tmp/tsc-after.txt | sort -u)`

Expected: no errors attributed to `src/pages/Scenarios.tsx`, `src/api/index.ts`, `src/lib/navItems.ts`, or `src/App.tsx`. Fix any that are.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/index.ts frontend/src/lib/navItems.ts frontend/src/App.tsx frontend/src/pages/Scenarios.tsx
git commit -m "feat: Scenarios tab with proposal editor

New route under Planning. Lists scenarios with a draft/committed badge and
edits the three proposal types in one place: proposed recurring items
(including end date and card routing), proposed one-offs, and amount
tweaks on existing items.

The recurring form warns when a card-routed proposal is assigned to a card
carrying a manual monthly spend estimate, because that estimate governs
the forecast instead of the card's individual charges -- so the proposal
would silently change nothing."
```

---

## Task 9: Impact strip, chart, and commit controls

**Files:**
- Modify: `frontend/src/pages/Scenarios.tsx`
- Modify: `frontend/src/api/index.ts` (add `quartersWithScenarioId`)
- Test: none (no frontend suite); `tsc` delta only.

**Interfaces:**
- Consumes: `GET /scenarios/{id}/impact` (Task 7), `POST /forecast/quarters-scenario` with `scenario_id` (Task 5), `commit`/`uncommit` (Task 6).
- Produces: nothing other tasks depend on. This is the last task.

- [ ] **Step 1: Record the `tsc` baseline again**

Run: `cd frontend && bunx tsc --noEmit 2>&1 | tee /tmp/tsc-before9.txt | tail -3`

- [ ] **Step 2: Add the scenario-id forecast call**

In `frontend/src/api/index.ts`, inside `forecastApi`, beside the existing `quartersWithScenario`:

```ts
  quartersWithScenarioId: (accountId: number, year: number, scenarioId: number) =>
    api.post("/forecast/quarters-scenario", {
      account_id: accountId, year, scenario_id: scenarioId,
    }).then((r) => r.data),
```

- [ ] **Step 3: Add the impact strip, chart, and commit controls**

In `frontend/src/pages/Scenarios.tsx`, extend the imports:

```tsx
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, Legend } from "recharts";
import { scenariosApi, accountsApi, cardsApi, recurringApi, forecastApi } from "../api";
```

Add state for the account and the comparison set, just below `newName`:

```tsx
  const [accountId, setAccountId] = useState<number | null>(null);
  // Default is one scenario against baseline; this set adds further lines for
  // comparing options against each other, which is available but not the
  // default (Dan, 2026-09-20).
  const [compareIds, setCompareIds] = useState<number[]>([]);
  const year = new Date().getFullYear();
```

After the `accounts` query, default the account once it loads:

```tsx
  const activeAccountId =
    accountId ?? (accounts.find((a) => a.type === "checking")?.id ?? accounts[0]?.id ?? null);
```

Add the impact, baseline and scenario-line queries after the `recurring` query:

```tsx
  const { data: impact } = useQuery<any>({
    queryKey: ["scenario-impact", selectedId, activeAccountId],
    queryFn: () => scenariosApi.impact(selectedId!, activeAccountId!),
    enabled: selectedId !== null && activeAccountId !== null,
  });

  const { data: baselineQuarters = [] } = useQuery<any[]>({
    queryKey: ["scenario-baseline", activeAccountId, year],
    queryFn: () => forecastApi.quarters(activeAccountId!, year),
    enabled: activeAccountId !== null,
  });

  const lineIds = selectedId === null ? compareIds : [selectedId, ...compareIds.filter((i) => i !== selectedId)];
  const { data: scenarioLines = [] } = useQuery<{ id: number; days: any[] }[]>({
    queryKey: ["scenario-lines", activeAccountId, year, lineIds],
    queryFn: async () => Promise.all(
      lineIds.map(async (id) => ({
        id,
        days: await forecastApi.quartersWithScenarioId(activeAccountId!, year, id),
      })),
    ),
    enabled: activeAccountId !== null && lineIds.length > 0,
  });
```

Build the chart rows. Quarter summaries carry nested `days`, exactly as
`Forecast.tsx:382-392` flattens them:

```tsx
  const flatten = (quarters: any[]) => {
    const out: Record<string, number> = {};
    quarters.forEach((q: any) =>
      (q.days ?? []).forEach((d: any) => { out[d.date] = parseFloat(d.projected_balance); }),
    );
    return out;
  };
  const baselineMap = flatten(baselineQuarters);
  const lineMaps = scenarioLines.map((l) => ({ id: l.id, map: flatten(l.days) }));
  const chartRows = Object.keys(baselineMap).sort().map((dateKey) => {
    const row: Record<string, any> = { date: dateKey, baseline: baselineMap[dateKey] };
    lineMaps.forEach((l) => { row[`s${l.id}`] = l.map[dateKey]; });
    return row;
  });
  const lineColors = ["#2563eb", "#16a34a", "#c2410c", "#7c3aed"];
```

Add the commit mutations beside the others:

```tsx
  const commit = useMutation({
    mutationFn: () => scenariosApi.commit(selected!.id),
    onSuccess: () => {
      invalidate();
      qc.invalidateQueries({ queryKey: ["recurring"] });
      qc.invalidateQueries({ queryKey: ["planned-expenses"] });
    },
  });
  const uncommit = useMutation({
    mutationFn: () => scenariosApi.uncommit(selected!.id),
    onSuccess: () => {
      invalidate();
      qc.invalidateQueries({ queryKey: ["recurring"] });
      qc.invalidateQueries({ queryKey: ["planned-expenses"] });
    },
  });
```

Then render these three blocks inside the `{selected && (<>…</>)}` fragment, after the three editor sections:

```tsx
          {impact && (
            <div className="card p-4">
              <h2 className="font-medium mb-3">Impact</h2>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-gray-500">
                    <th className="py-1">Figure</th>
                    <th className="py-1">Baseline</th>
                    <th className="py-1">Scenario</th>
                    <th className="py-1">Change</th>
                  </tr>
                </thead>
                <tbody>
                  {([
                    ["3-month low", "low", true],
                    ["Weekly safety margin", "safety_margin_weekly", true],
                    ["Ongoing monthly burn", "monthly_burn", false],
                  ] as [string, string, boolean][]).map(([label, key, higherIsBetter]) => {
                    const base = Number(impact.baseline[key]);
                    const scen = Number(impact.scenario[key]);
                    const delta = scen - base;
                    const good = higherIsBetter ? delta >= 0 : delta <= 0;
                    return (
                      <tr key={key} className="border-t">
                        <td className="py-1.5">{label}</td>
                        <td className="py-1.5">{money(base)}</td>
                        <td className="py-1.5">{money(scen)}</td>
                        <td className={`py-1.5 ${good ? "text-green-700" : "text-red-700"}`}>
                          {delta >= 0 ? "+" : "−"}{money(Math.abs(delta))}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {impact.scenario.low_date && (
                <p className="text-xs text-gray-500 mt-2">
                  Scenario low lands {impact.scenario.low_date}.
                </p>
              )}
            </div>
          )}

          <div className="card p-4 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="font-medium">Projected balance</h2>
              <select
                className="input w-auto"
                value={activeAccountId ?? ""}
                onChange={(e) => setAccountId(parseInt(e.target.value, 10))}
              >
                {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
            </div>
            <div className="flex flex-wrap gap-2 text-sm">
              <span className="text-gray-500">Also compare:</span>
              {scenarios.filter((s) => s.id !== selected.id).map((s) => (
                <label key={s.id} className="inline-flex items-center gap-1">
                  <input
                    type="checkbox"
                    checked={compareIds.includes(s.id)}
                    onChange={(e) => setCompareIds(
                      e.target.checked
                        ? [...compareIds, s.id]
                        : compareIds.filter((i) => i !== s.id),
                    )}
                  />
                  {s.name}
                </label>
              ))}
            </div>
            <div style={{ height: 320 }}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartRows}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={40} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip formatter={(v: any) => money(v)} />
                  <Legend />
                  <Line type="monotone" dataKey="baseline" name="Baseline"
                        stroke="#6b7280" strokeWidth={2} dot={false} />
                  {lineMaps.map((l, idx) => (
                    <Line
                      key={l.id}
                      type="monotone"
                      dataKey={`s${l.id}`}
                      name={scenarios.find((s) => s.id === l.id)?.name ?? `Scenario ${l.id}`}
                      stroke={lineColors[idx % lineColors.length]}
                      strokeWidth={2}
                      strokeDasharray="5 3"
                      dot={false}
                    />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="card p-4 space-y-2">
            {committed ? (
              <>
                <p className="text-sm">
                  Committed{selected.committed_at ? ` ${selected.committed_at.slice(0, 10)}` : ""}.
                  Its items are now real recurring items and planned expenses.
                </p>
                <button
                  className="btn"
                  onClick={() => {
                    const ok = window.confirm(
                      "Uncommit deletes the recurring items and planned expenses this " +
                      "scenario created and restores the amounts it changed. Any edits " +
                      "you made to those rows since committing will be lost. Continue?",
                    );
                    if (ok) uncommit.mutate();
                  }}
                >
                  Uncommit
                </button>
              </>
            ) : (
              <>
                <p className="text-sm text-gray-500">
                  Committing creates real recurring items and planned expenses from
                  this scenario, and applies its amount tweaks. It can be reversed.
                </p>
                <button
                  className="btn"
                  disabled={
                    selected.proposed_items.length === 0 &&
                    selected.proposed_expenses.length === 0 &&
                    selected.overrides.length === 0
                  }
                  onClick={() => commit.mutate()}
                >
                  Commit to forecast
                </button>
              </>
            )}
          </div>
```

- [ ] **Step 4: Check for new TypeScript errors**

`forecastApi.quarters(accountId, year)` already exists with that exact signature (`api/index.ts:99-100`), and `QuarterSummary` carries `close_balance` plus `days: list[ForecastEntry]` whose entries expose `date` and `projected_balance` (`schemas.py:444-453`) — both verified, so no discovery step is needed here.

Run: `cd frontend && bunx tsc --noEmit 2>&1 | tee /tmp/tsc-after9.txt | tail -3`
Then compare against `/tmp/tsc-before9.txt` as in Task 8 Step 6.
Expected: no errors attributed to `src/pages/Scenarios.tsx` or `src/api/index.ts`.

- [ ] **Step 5: Run the backend suite one final time**

Run: `python3 -m pytest backend/tests -q`
Expected: no new failures versus the Task 1 baseline.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/Scenarios.tsx frontend/src/api/index.ts
git commit -m "feat: scenario impact strip, comparison chart, and commit controls

Impact table shows the three-month low, weekly safety margin and ongoing
monthly burn for baseline and scenario side by side, coloured by whether
the change helps. The chart draws baseline plus the selected scenario by
default; further scenarios can be checked in to compare options against
each other.

Commit is offered on a draft and replaced by Uncommit on a committed
scenario, behind a confirm dialog that names what uncommit discards."
```

---

## Notes for the executor

- **Do not claim visual verification.** Interceptor's preflight fails on this machine (no connected browser context), so Tasks 8 and 9 ship with `tsc` evidence only. Say that plainly in the task report rather than implying the page was seen working.
- **The parity test in Task 2 is the load-bearing test of this whole plan.** If it fails after a later change, the change broke the equivalence between a proposal and a real row, which is the premise the design rests on. Investigate rather than adjusting the assertion.
- **Two stray test users ("diag1", "flow") exist in the production database** from earlier debugging. They are unrelated to this work; do not clean them up as part of it.
