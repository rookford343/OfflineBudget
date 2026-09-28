# Subscription Rollups, Triage Inbox & Left to Budget Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Roll recurring bills up into Home and Subscriptions, give unknown recurring charges a one-click triage inbox that learns merchant rules, and show a zero-based "Left to budget" bar with an opt-in carry-forward setting.

**Architecture:** Keep the two-level category tree (rename Utilities → Home). Three new focused backend services: `budget_buckets` (which lines are assignable + carry-forward filtering), `left_to_budget` (committed/assignable breakdown over the existing `leftover`), and `recurring_triage` (inbox rows, best guess, classify/dismiss/duplicate). `leftover` math is refactored into reusable parts but never changed. Two new React components mount on existing pages.

**Tech Stack:** FastAPI + SQLAlchemy 2 (SQLite) + pytest backend; React + TypeScript + TanStack Query + Tailwind frontend.

**Spec:** `docs/superpowers/specs/2026-09-27-subscription-rollups-and-left-to-budget-design.md`

## Global Constraints

- `leftover`, `left_to_spend`, `safety_margin` and the forecast must be byte-identical before and after this work for the same data.
- Backfill never overwrites a non-NULL `category_id`.
- Nothing is ever deleted: duplicates are deactivated (`is_active = False`), month=0 allocations are kept when ignored.
- `User.budget_carry_forward` defaults to `False`.
- Assignable bucket = expense type AND `is_discretionary` AND leaf (no children) AND no active expense recurring items AND name not in {Savings, Groceries}.
- Commits go directly to `main`. Commit messages describe app behavior only — no real balances, amounts, dates or merchant names from the live database (repo is public).
- Backend tests run from `backend/`: `cd backend && python3 -m pytest <path> -v`. Test files live in `backend/tests/` and import as `from backend import models`.
- Frontend check: `cd frontend && bun run build` (runs `tsc -b`). Use `bun`, never npm.
- Routes under `/recurring/triage...` must be declared **before** `/{item_id}` routes in `backend/routers/recurring.py`.

---

### Task 1: Rename Utilities → Home; seed and keyword updates

**Files:**
- Modify: `backend/database.py` (`upgrade_categories`, ~line 31)
- Modify: `backend/seed.py:13`
- Modify: `backend/services/auto_categorizer.py` (Utilities block, ~lines 45-56)
- Test: `backend/tests/test_home_category_rollup.py` (create)

**Interfaces:**
- Produces: `database.rename_utilities_to_home(conn) -> None` (idempotent; takes a SQLAlchemy `Connection`). `auto_categorizer.KEYWORD_RULES` targets `"Home"` instead of `"Utilities"`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_home_category_rollup.py
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool
from backend import models
from backend.database import Base, rename_utilities_to_home
from backend.services.auto_categorizer import categorize


def _engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return engine


def _insert(conn, cid, name, parent_id=None):
    conn.execute(text(
        "INSERT INTO categories (id, user_id, parent_id, name, type, color, sort_order, rollover_enabled, rollover_balance, tax_deductible, is_discretionary) "
        "VALUES (:id, 1, :pid, :name, 'expense', '#000000', 0, 0, 0, 0, 0)"
    ), {"id": cid, "pid": parent_id, "name": name})


def _names(conn):
    return {r[0]: r[1] for r in conn.execute(text("SELECT id, name FROM categories"))}


def test_utilities_under_necessities_becomes_home_keeping_its_id():
    with _engine().connect() as conn:
        conn.execute(text("INSERT INTO users (id, username, hashed_password, display_name) VALUES (1, 'u', 'x', 'U')"))
        _insert(conn, 10, "Necessities")
        _insert(conn, 11, "Utilities", 10)
        conn.commit()
        rename_utilities_to_home(conn)
        assert _names(conn)[11] == "Home"


def test_rename_is_idempotent_and_skips_when_home_exists():
    with _engine().connect() as conn:
        conn.execute(text("INSERT INTO users (id, username, hashed_password, display_name) VALUES (1, 'u', 'x', 'U')"))
        _insert(conn, 10, "Necessities")
        _insert(conn, 11, "Utilities", 10)
        _insert(conn, 12, "Home", 10)
        conn.commit()
        rename_utilities_to_home(conn)
        rename_utilities_to_home(conn)
        names = _names(conn)
        assert names[11] == "Utilities"
        assert names[12] == "Home"


def test_utilities_elsewhere_is_untouched():
    with _engine().connect() as conn:
        conn.execute(text("INSERT INTO users (id, username, hashed_password, display_name) VALUES (1, 'u', 'x', 'U')"))
        _insert(conn, 20, "Business")
        _insert(conn, 21, "Utilities", 20)
        conn.commit()
        rename_utilities_to_home(conn)
        assert _names(conn)[21] == "Utilities"


def _cats():
    return [
        models.Category(id=1, user_id=1, name="Home", type=models.CategoryType.expense),
        models.Category(id=2, user_id=1, name="Subscriptions", type=models.CategoryType.expense),
        models.Category(id=3, user_id=1, name="Transportation", type=models.CategoryType.expense),
    ]


def test_energy_and_home_service_keywords_land_in_home():
    for desc in ["DUKE ENERGY PAYMENT", "WASTE MANAGEMENT 8812", "CITY STORMWATER FEE", "GREENIX PEST CONTROL", "METRONET"]:
        assert categorize(desc, _cats()).name == "Home", desc


def test_gas_station_and_hoagie_are_not_home():
    assert categorize("SHELL GAS STATION 443", _cats()) is None
    assert categorize("JERSEY MIKES HOAGIE", _cats()) is None


def test_streaming_still_lands_in_subscriptions():
    assert categorize("NETFLIX.COM", _cats()).name == "Subscriptions"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_home_category_rollup.py -v`
Expected: FAIL — `ImportError: cannot import name 'rename_utilities_to_home'`.

- [ ] **Step 3: Implement the migration**

In `backend/database.py`, add above `upgrade_categories` and call it from inside it:

```python
def rename_utilities_to_home(conn) -> None:
    """Utilities → Home, in place, so every link to the row keeps working.

    Only the Utilities that sits under a top-level Necessities, and only when
    that parent has no Home child already -- running twice, or on a database
    where someone already made Home by hand, must be a no-op rather than
    producing two Homes.
    """
    conn.execute(text("""
        UPDATE categories SET name = 'Home'
        WHERE name = 'Utilities'
          AND parent_id IN (
              SELECT id FROM categories WHERE name = 'Necessities' AND parent_id IS NULL
          )
          AND NOT EXISTS (
              SELECT 1 FROM categories AS sib
              WHERE sib.parent_id = categories.parent_id AND sib.name = 'Home'
          )
    """))
```

(No commit inside — the caller owns the transaction, which lets tests run it on a Session's connection.)

Inside `upgrade_categories`'s `try:` block, after the existing Charity statements and before `except`, add:

```python
            rename_utilities_to_home(conn)
            conn.commit()
```

- [ ] **Step 4: Update seed**

In `backend/seed.py` line 13 replace:

```python
        ("Utilities", "expense", "#2563eb", "zap"),
```
with
```python
        ("Home", "expense", "#2563eb", "home"),
```

- [ ] **Step 5: Update keyword rules**

In `backend/services/auto_categorizer.py` replace the whole `# Utilities` block with:

```python
    # Home -- house bills. Deliberately specific: this table categorizes every
    # imported transaction, so bare "gas"/"water"/"hoa" would catch gas
    # stations and sandwich shops.
    ("duke energy", "Home"),
    ("duke electric", "Home"),
    ("electric", "Home"),
    ("natural gas", "Home"),
    ("citizens energy", "Home"),
    ("water & sewer", "Home"),
    ("stormwater", "Home"),
    ("waste management", "Home"),
    ("republic services", "Home"),
    ("hoa fee", "Home"),
    ("hoa dues", "Home"),
    ("homeowners assoc", "Home"),
    ("metronet", "Home"),
    ("xfinity", "Home"),
    ("comcast", "Home"),
    ("at&t", "Home"),
    ("verizon", "Home"),
    ("t-mobile", "Home"),
    ("spectrum", "Home"),
    ("google fi", "Home"),
    ("piedmont natural gas", "Home"),
    ("dominion", "Home"),
    ("lawn", "Home"),
    ("landscap", "Home"),
    ("pest", "Home"),
    ("greenix", "Home"),
    ("terminix", "Home"),
```

- [ ] **Step 6: Run tests to verify they pass, then the full suite**

Run: `cd backend && python3 -m pytest tests/test_home_category_rollup.py -v` → all PASS.
Run: `cd backend && python3 -m pytest -q` → all PASS. If an existing test asserted a transaction auto-categorized to `"Utilities"`, update its fixture category name to `"Home"` (the rename is the intended behavior); do not change any other assertion.

- [ ] **Step 7: Commit**

```bash
git add backend/database.py backend/seed.py backend/services/auto_categorizer.py backend/tests/test_home_category_rollup.py
git commit -m "feat: rename Utilities to Home and route house-bill keywords there"
```

---

### Task 2: Carry-forward setting and assignable-bucket rule

**Files:**
- Create: `backend/services/budget_buckets.py`
- Modify: `backend/models.py` (User, after `savings_strategy` ~line 128)
- Modify: `backend/database.py` (`upgrade_schema` ALTER list)
- Modify: `backend/schemas.py` (`UserOut` ~line 42, `UserUpdate` ~line 67)
- Modify: `backend/services/budget_calculator.py:25-33`
- Modify: `backend/routers/spending.py:319-327`
- Test: `backend/tests/test_budget_buckets.py` (create)

**Interfaces:**
- Produces:
  - `budget_buckets.LEFTOVER_COMMITTED_NAMES: frozenset[str]` = `{"Savings", "Groceries"}`
  - `budget_buckets.assignable_category_ids(db: Session, user_id: int) -> set[int]`
  - `budget_buckets.drop_uncarried_defaults(allocations: list[models.BudgetAllocation], user: models.User, assignable_ids: set[int]) -> list[models.BudgetAllocation]`
  - `models.User.budget_carry_forward: bool`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_budget_buckets.py
from datetime import date
from decimal import Decimal
from backend import models
from backend.services.budget_buckets import assignable_category_ids, drop_uncarried_defaults
from backend.services.budget_calculator import compute_overview


def _seed(db, carry_forward=False):
    user = models.User(username="b", hashed_password="x", display_name="B", budget_carry_forward=carry_forward)
    db.add(user); db.flush()
    acct = models.Account(user_id=user.id, name="Chk", type=models.AccountType.checking)
    wants = models.Category(user_id=user.id, name="Wants", type=models.CategoryType.expense, is_discretionary=True)
    db.add_all([acct, wants]); db.flush()
    E = models.CategoryType.expense
    cats = {
        "Shopping": models.Category(user_id=user.id, parent_id=wants.id, name="Shopping", type=E, is_discretionary=True),
        "Subscriptions": models.Category(user_id=user.id, parent_id=wants.id, name="Subscriptions", type=E, is_discretionary=True),
        "Groceries": models.Category(user_id=user.id, name="Groceries", type=E, is_discretionary=True),
        "Home": models.Category(user_id=user.id, name="Home", type=E, is_discretionary=False),
    }
    db.add_all(cats.values()); db.flush()
    cats["Wants"] = wants
    db.add(models.RecurringItem(
        user_id=user.id, account_id=acct.id, category_id=cats["Subscriptions"].id, name="Streamer",
        amount=Decimal("15.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=3, start_date=date(2026, 1, 1),
    ))
    db.add_all([
        models.BudgetAllocation(user_id=user.id, category_id=cats["Shopping"].id, year=2026, month=0, budgeted_amount=Decimal("500.00")),
        models.BudgetAllocation(user_id=user.id, category_id=cats["Groceries"].id, year=2026, month=0, budgeted_amount=Decimal("400.00")),
        models.BudgetAllocation(user_id=user.id, category_id=cats["Home"].id, year=2026, month=0, budgeted_amount=Decimal("300.00")),
    ])
    db.commit()
    return user, cats


def test_only_leaf_discretionary_unbilled_non_committed_lines_are_assignable(db_session):
    user, cats = _seed(db_session)
    assert assignable_category_ids(db_session, user.id) == {cats["Shopping"].id}


def test_carry_forward_off_drops_month0_rows_for_assignable_only(db_session):
    user, cats = _seed(db_session)
    rows = db_session.query(models.BudgetAllocation).all()
    kept = drop_uncarried_defaults(rows, user, assignable_category_ids(db_session, user.id))
    kept_cats = {a.category_id for a in kept}
    assert cats["Shopping"].id not in kept_cats
    assert cats["Groceries"].id in kept_cats
    assert cats["Home"].id in kept_cats


def test_carry_forward_on_keeps_everything(db_session):
    user, _ = _seed(db_session, carry_forward=True)
    rows = db_session.query(models.BudgetAllocation).all()
    assert len(drop_uncarried_defaults(rows, user, assignable_category_ids(db_session, user.id))) == 3


def test_month_specific_row_survives_carry_forward_off(db_session):
    user, cats = _seed(db_session)
    db_session.add(models.BudgetAllocation(user_id=user.id, category_id=cats["Shopping"].id, year=2026, month=10, budgeted_amount=Decimal("450.00")))
    db_session.commit()
    rows = db_session.query(models.BudgetAllocation).all()
    kept = drop_uncarried_defaults(rows, user, assignable_category_ids(db_session, user.id))
    assert [a.budgeted_amount for a in kept if a.category_id == cats["Shopping"].id] == [Decimal("450.00")]


def test_overview_shows_unassigned_bucket_as_zero_when_carry_forward_off(db_session):
    user, cats = _seed(db_session)
    rows = {r.category_id: r for r in compute_overview(db_session, user.id, 2026, 10)}
    assert rows[cats["Shopping"].id].budgeted == Decimal("0")
    assert rows[cats["Groceries"].id].budgeted == Decimal("400.00")


def test_overview_carries_forward_when_enabled(db_session):
    user, cats = _seed(db_session, carry_forward=True)
    rows = {r.category_id: r for r in compute_overview(db_session, user.id, 2026, 10)}
    assert rows[cats["Shopping"].id].budgeted == Decimal("500.00")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_budget_buckets.py -v`
Expected: FAIL — `TypeError: 'budget_carry_forward' is an invalid keyword argument for User` / `ModuleNotFoundError: backend.services.budget_buckets`.

- [ ] **Step 3: Add the column**

In `backend/models.py`, directly after the `savings_strategy` line in `User`:

```python
    # Whether an unset month inherits the all-months (month=0) budget for
    # assignable buckets (Food, Shopping...). Off by default: zero-based
    # budgeting starts each month unassigned and you assign it on purpose.
    # Committed lines (bills, Savings, Groceries) never depend on this.
    budget_carry_forward: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
```

In `backend/database.py` `upgrade_schema`, append to the ALTER statement list:

```python
        "ALTER TABLE users ADD COLUMN budget_carry_forward BOOLEAN NOT NULL DEFAULT 0",
```

In `backend/schemas.py`, add to **both** `UserOut` (after `savings_strategy: Optional[str] = None`, ~line 42) and `UserUpdate` (after its `savings_strategy`, ~line 67):

```python
    budget_carry_forward: Optional[bool] = None
```

- [ ] **Step 4: Create the service**

```python
# backend/services/budget_buckets.py
"""Which budget lines are assigned out of the leftover, and how their
allocations resolve under the per-user carry-forward setting.

One place for the rule so the Budget page, the Spending page and the weekly
email can't disagree about whether a bucket is "not assigned yet".
"""
from __future__ import annotations
from sqlalchemy.orm import Session
from backend import models

# Already subtracted inside budget_snapshot's `leftover`. Letting them be
# assigned from the leftover again would count them twice.
LEFTOVER_COMMITTED_NAMES = frozenset({"Savings", "Groceries"})


def assignable_category_ids(db: Session, user_id: int) -> set[int]:
    """Leaf, discretionary expense categories with no active bills.

    A category with active recurring items is committed -- its amount is the
    sum of its bills. Giving it a manual budget too is how Subscriptions
    ended up counted twice (once inside leftover, once as an allocation).
    """
    cats = db.query(models.Category).filter(
        models.Category.user_id == user_id,
        models.Category.type == models.CategoryType.expense,
        models.Category.is_discretionary == True,
    ).all()
    parent_ids = {
        pid for (pid,) in db.query(models.Category.parent_id).filter(
            models.Category.user_id == user_id,
            models.Category.parent_id.isnot(None),
        ).all()
    }
    billed_ids = {
        cid for (cid,) in db.query(models.RecurringItem.category_id).filter(
            models.RecurringItem.user_id == user_id,
            models.RecurringItem.type == models.RecurringType.expense,
            models.RecurringItem.is_active == True,
            models.RecurringItem.category_id.isnot(None),
        ).all()
    }
    return {
        c.id for c in cats
        if c.id not in parent_ids
        and c.id not in billed_ids
        and c.name not in LEFTOVER_COMMITTED_NAMES
    }


def drop_uncarried_defaults(
    allocations: list[models.BudgetAllocation],
    user: models.User,
    assignable_ids: set[int],
) -> list[models.BudgetAllocation]:
    """With carry-forward off, an assignable bucket's month=0 row does not
    stand in for a month nobody assigned. The row is ignored, not deleted,
    so turning the setting back on restores it."""
    if user.budget_carry_forward:
        return list(allocations)
    return [a for a in allocations if not (a.month == 0 and a.category_id in assignable_ids)]
```

- [ ] **Step 5: Apply it in the two allocation readers**

`backend/services/budget_calculator.py` — add import at top:

```python
from backend.services.budget_buckets import assignable_category_ids, drop_uncarried_defaults
```

and immediately after the `allocations = db.query(...).all()` statement (before `budget_by_cat` is built):

```python
    user = db.get(models.User, user_id)
    allocations = drop_uncarried_defaults(allocations, user, assignable_category_ids(db, user_id))
```

`backend/routers/spending.py` — add the same import at the top, and immediately after the `budgets = db.query(models.BudgetAllocation)...all()` statement in `spending_by_category`:

```python
    budgets = drop_uncarried_defaults(budgets, user, assignable_category_ids(db, user.id))
```

- [ ] **Step 6: Run tests**

Run: `cd backend && python3 -m pytest tests/test_budget_buckets.py -v` → PASS.
Run: `cd backend && python3 -m pytest -q` → PASS. If a pre-existing test fails because its fixture has a **discretionary** category with a month=0 allocation and expects that budget, set `budget_carry_forward=True` on that fixture's `User(...)` — that preserves what the test was written to check. Do not change assertions.

- [ ] **Step 7: Commit**

```bash
git add backend/services/budget_buckets.py backend/models.py backend/database.py backend/schemas.py backend/services/budget_calculator.py backend/routers/spending.py backend/tests/
git commit -m "feat: per-user budget carry-forward setting, off by default, for assignable buckets"
```

---

### Task 3: Left-to-budget service and endpoint

**Files:**
- Modify: `backend/services/budget_snapshot.py` (`_monthly_expenses` ~line 40, `compute_budget_snapshot` ~lines 313-331)
- Create: `backend/services/left_to_budget.py`
- Modify: `backend/schemas.py` (append new models)
- Modify: `backend/routers/budget.py` (new GET route)
- Test: `backend/tests/test_left_to_budget.py` (create)

**Interfaces:**
- Consumes: `budget_buckets.assignable_category_ids`, `budget_buckets.drop_uncarried_defaults` (Task 2).
- Produces:
  - `budget_snapshot.leftover_share(item, as_of: date) -> Decimal`
  - `budget_snapshot.LeftoverParts` (NamedTuple: `income, expenses, savings_budget, committed_savings, groceries_budget, leftover`, all `Decimal`)
  - `budget_snapshot.leftover_parts(db, user, as_of, extra_items=None) -> LeftoverParts`
  - `left_to_budget.compute_left_to_budget(db, user, year: int, month: int) -> schemas.LeftToBudgetOut`
  - `GET /budget/left-to-budget?year=&month=` → `LeftToBudgetOut`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_left_to_budget.py
from datetime import date
from decimal import Decimal
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.dependencies import get_db, get_current_user
from backend.routers import budget as budget_router_module
from backend.services.budget_snapshot import compute_budget_snapshot, leftover_parts
from backend.services.left_to_budget import compute_left_to_budget
from backend.tests.test_budget_snapshot import _seed_spreadsheet_scenario, _fake_quarter_min

E = models.CategoryType.expense


def _seed(db):
    user = models.User(username="t", hashed_password="x", display_name="T", savings_strategy="save_monthly")
    db.add(user); db.flush()
    acct = models.Account(user_id=user.id, name="Chk", type=models.AccountType.checking)
    db.add(acct); db.flush()
    home = models.Category(user_id=user.id, name="Home", type=E)
    subs = models.Category(user_id=user.id, name="Subscriptions", type=E, is_discretionary=True)
    shopping = models.Category(user_id=user.id, name="Shopping", type=E, is_discretionary=True)
    food = models.Category(user_id=user.id, name="Food & Drinks", type=E, is_discretionary=True)
    groceries = models.Category(user_id=user.id, name="Groceries", type=E, is_discretionary=True)
    savings = models.Category(user_id=user.id, name="Savings", type=models.CategoryType.savings)
    db.add_all([home, subs, shopping, food, groceries, savings]); db.flush()

    def item(name, amount, cat, freq=models.RecurringFrequency.monthly, moy=None, typ=models.RecurringType.expense):
        db.add(models.RecurringItem(
            user_id=user.id, account_id=acct.id, category_id=cat.id if cat else None, name=name,
            amount=Decimal(amount), type=typ, frequency=freq, day_of_month=5, month_of_year=moy,
            start_date=date(2026, 1, 1),
        ))

    item("Pay", "5000.00", None, typ=models.RecurringType.income)
    item("Electric", "150.00", home)
    item("Stormwater", "30.00", home, freq=models.RecurringFrequency.quarterly)
    item("Streamer", "20.00", subs)
    item("Mystery", "12.00", None)
    item("Annual app", "120.00", None, freq=models.RecurringFrequency.yearly, moy=3)
    db.add_all([
        models.BudgetAllocation(user_id=user.id, category_id=savings.id, year=2026, month=0, budgeted_amount=Decimal("1000.00")),
        models.BudgetAllocation(user_id=user.id, category_id=groceries.id, year=2026, month=0, budgeted_amount=Decimal("600.00")),
        models.BudgetAllocation(user_id=user.id, category_id=shopping.id, year=2026, month=0, budgeted_amount=Decimal("700.00")),
        models.BudgetAllocation(user_id=user.id, category_id=food.id, year=2026, month=10, budgeted_amount=Decimal("800.00")),
        models.BudgetAllocation(user_id=user.id, category_id=subs.id, year=2026, month=0, budgeted_amount=Decimal("300.00")),
    ])
    db.commit()
    return user, {"home": home, "subs": subs, "shopping": shopping, "food": food}


def test_committed_rows_and_leftover_reconcile_to_income(db_session):
    user, _ = _seed(db_session)
    out = compute_left_to_budget(db_session, user, 2026, 10)
    committed_total = sum((r.amount for r in out.committed), Decimal("0"))
    assert out.leftover + committed_total == Decimal("5000.00")


def test_committed_rows_break_down_by_category_with_bills(db_session):
    user, _ = _seed(db_session)
    rows = {r.category_name: r for r in compute_left_to_budget(db_session, user, 2026, 10).committed}
    assert rows["Home"].amount == Decimal("160.00")          # 150 + 30/3
    assert {b.name for b in rows["Home"].items} == {"Electric", "Stormwater"}
    assert rows["Subscriptions"].amount == Decimal("20.00")  # from bills, NOT the 300 allocation
    assert rows["Unclassified"].amount == Decimal("12.00")   # yearly item not due in October
    assert rows["Savings"].amount == Decimal("1000.00")
    assert rows["Groceries"].amount == Decimal("600.00")


def test_unclassified_badge_counts_every_uncategorized_bill_smoothed(db_session):
    user, _ = _seed(db_session)
    out = compute_left_to_budget(db_session, user, 2026, 10)
    assert out.unclassified_count == 2
    assert out.unclassified_amount == Decimal("22.00")       # 12 + 120/12


def test_assignable_uses_month_row_only_when_carry_forward_off(db_session):
    user, cats = _seed(db_session)
    out = compute_left_to_budget(db_session, user, 2026, 10)
    assigned = {r.category_name: r for r in out.assignable}
    assert set(assigned) == {"Shopping", "Food & Drinks"}
    assert assigned["Shopping"].assigned == Decimal("0") and assigned["Shopping"].is_set is False
    assert assigned["Food & Drinks"].assigned == Decimal("800.00") and assigned["Food & Drinks"].is_set is True
    assert out.assigned_total == Decimal("800.00")
    assert out.unassigned == out.leftover - Decimal("800.00")
    assert out.carry_forward is False


def test_assignable_falls_back_to_month0_when_carry_forward_on(db_session):
    user, _ = _seed(db_session)
    user.budget_carry_forward = True
    db_session.commit()
    out = compute_left_to_budget(db_session, user, 2026, 10)
    assert {r.category_name: r.assigned for r in out.assignable}["Shopping"] == Decimal("700.00")


def test_endpoint_returns_payload(db_session):
    user, _ = _seed(db_session)
    app = FastAPI()
    app.include_router(budget_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    r = TestClient(app).get("/budget/left-to-budget", params={"year": 2026, "month": 10})
    assert r.status_code == 200
    assert r.json()["unclassified_count"] == 2


def test_guard_leftover_and_left_to_spend_unchanged_by_classification_and_setting(db_session):
    user, checking, _card = _seed_spreadsheet_scenario(db_session)
    as_of = date(2026, 8, 7)
    with patch("backend.services.budget_snapshot.build_forecast", return_value=_fake_quarter_min("5120.66")):
        before = compute_budget_snapshot(db_session, user, checking.id, as_of=as_of)

    home = models.Category(user_id=user.id, name="Home", type=E)
    db_session.add(home); db_session.flush()
    for item in db_session.query(models.RecurringItem).filter(models.RecurringItem.type == models.RecurringType.expense):
        item.category_id = home.id
    user.budget_carry_forward = True
    db_session.commit()
    compute_left_to_budget(db_session, user, 2026, 8)

    with patch("backend.services.budget_snapshot.build_forecast", return_value=_fake_quarter_min("5120.66")):
        after = compute_budget_snapshot(db_session, user, checking.id, as_of=as_of)
    assert after.leftover == before.leftover
    assert after.left_to_spend == before.left_to_spend
    assert after.safety_margin == before.safety_margin
    assert leftover_parts(db_session, user, as_of).leftover == before.leftover
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_left_to_budget.py -v`
Expected: FAIL — `ImportError: cannot import name 'leftover_parts'`.

- [ ] **Step 3: Refactor `budget_snapshot` (behavior-preserving)**

Add `from typing import NamedTuple` to the imports. Replace the loop at the end of `_monthly_expenses` (from `total = Decimal("0")` through `return total`) with:

```python
    return sum((leftover_share(item, as_of) for item in items), Decimal("0"))
```

Add above `_monthly_expenses` (move the existing quarterly comment into it verbatim):

```python
def leftover_share(item, as_of: date) -> Decimal:
    """What one expense recurring item contributes to `_monthly_expenses` for
    as_of's month. Shared with the Budget page's committed list so committed
    + leftover reconcile to income to the cent.

    Weekly/biweekly items contribute nothing here, matching the long-standing
    behavior of `_monthly_expenses`.
    """
    if item.frequency == models.RecurringFrequency.monthly:
        return item.amount
    if item.frequency == models.RecurringFrequency.quarterly:
        # Accrued, not charged: a quarterly bill spreads across the three
        # months it covers, exactly as the sheet does -- Budget!B15 carries
        # Stormwater at $4.94/mo while the forecast charges the full $14.82
        # once a quarter. Counting the whole bill in its own month would
        # make Leftover lurch every third month.
        return (item.amount / 3).quantize(Decimal("0.01"))
    if item.frequency == models.RecurringFrequency.yearly and item.month_of_year == as_of.month:
        return item.amount
    return Decimal("0")
```

Add after `_budget_allocation_total`:

```python
class LeftoverParts(NamedTuple):
    income: Decimal
    expenses: Decimal
    savings_budget: Decimal
    committed_savings: Decimal
    groceries_budget: Decimal
    leftover: Decimal


def leftover_parts(
    db: Session, user: models.User, as_of: date,
    extra_items: list[models.RecurringItem] | None = None,
) -> LeftoverParts:
    """The pieces of `leftover`, computed once so the snapshot and the
    Budget page's Left to budget read the same number by construction."""
    income = _monthly_income(db, user.id, extra_items)
    expenses = _monthly_expenses(db, user.id, as_of, extra_items)
    savings_budget = _budget_allocation_total(db, user.id, "Savings", as_of.year, as_of.month)
    groceries_budget = _budget_allocation_total(db, user.id, "Groceries", as_of.year, as_of.month)
    committed_savings = (
        Decimal("0.00") if user.savings_strategy == "pull_from_savings" else savings_budget
    )
    leftover = income - expenses - committed_savings - groceries_budget
    return LeftoverParts(income, expenses, savings_budget, committed_savings, groceries_budget, leftover)
```

In `compute_budget_snapshot`, replace the lines from `monthly_income = _monthly_income(...)` through `leftover = monthly_income - monthly_expenses - committed_savings - groceries_budget` with the following, **keeping the existing Groceries and savings-strategy comment blocks above the call**:

```python
    parts = leftover_parts(db, user, as_of, extra_items)
    monthly_income = parts.income
    monthly_expenses = parts.expenses
    savings_budget = parts.savings_budget
    groceries_budget = parts.groceries_budget
    committed_savings = parts.committed_savings
    leftover = parts.leftover
```

Run: `cd backend && python3 -m pytest tests/test_budget_snapshot.py tests/test_spending_budget_snapshot_endpoint.py -q` → PASS (proves the refactor is neutral).

- [ ] **Step 4: Add schemas**

Append to `backend/schemas.py`:

```python
# ── Left to Budget ────────────────────────────────────────────────────────────

class CommittedBill(BaseModel):
    recurring_item_id: int
    name: str
    amount: Decimal


class CommittedRow(BaseModel):
    category_id: Optional[int] = None
    category_name: str
    amount: Decimal
    items: list[CommittedBill] = []


class AssignableRow(BaseModel):
    category_id: int
    category_name: str
    assigned: Decimal
    is_set: bool


class LeftToBudgetOut(BaseModel):
    year: int
    month: int
    leftover: Decimal
    committed: list[CommittedRow]
    unclassified_count: int
    unclassified_amount: Decimal
    assignable: list[AssignableRow]
    assigned_total: Decimal
    unassigned: Decimal
    carry_forward: bool
```

- [ ] **Step 5: Create the service**

```python
# backend/services/left_to_budget.py
"""Zero-based view of the month: what is already committed (bills, Savings,
Groceries) and how much of the rest has been assigned to buckets.

Reads `leftover` from budget_snapshot and never changes it -- classifying a
bill only moves it between committed rows, so the total is fixed.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import date
from decimal import Decimal
from sqlalchemy.orm import Session
from backend import models, schemas
from backend.services.budget_buckets import assignable_category_ids, drop_uncarried_defaults
from backend.services.budget_snapshot import leftover_parts, leftover_share
from backend.services.recurring_math import monthly_equivalent

ZERO = Decimal("0")


def compute_left_to_budget(db: Session, user: models.User, year: int, month: int) -> schemas.LeftToBudgetOut:
    as_of = date(year, month, 1)
    parts = leftover_parts(db, user, as_of)

    categories = db.query(models.Category).filter(models.Category.user_id == user.id).all()
    cat_by_id = {c.id: c for c in categories}
    cat_id_by_name = {c.name: c.id for c in categories}

    items = db.query(models.RecurringItem).filter(
        models.RecurringItem.user_id == user.id,
        models.RecurringItem.type == models.RecurringType.expense,
        models.RecurringItem.is_active == True,
    ).all()

    bills_by_cat: dict[int | None, list[schemas.CommittedBill]] = defaultdict(list)
    for item in items:
        share = leftover_share(item, as_of)
        if share == ZERO:
            continue
        bills_by_cat[item.category_id].append(
            schemas.CommittedBill(recurring_item_id=item.id, name=item.name, amount=share)
        )

    def row(cid: int | None, name: str, bills: list[schemas.CommittedBill]) -> schemas.CommittedRow:
        bills = sorted(bills, key=lambda b: b.amount, reverse=True)
        return schemas.CommittedRow(
            category_id=cid, category_name=name,
            amount=sum((b.amount for b in bills), ZERO), items=bills,
        )

    committed = [
        row(cid, cat_by_id[cid].name, bills)
        for cid, bills in bills_by_cat.items()
        if cid is not None and cid in cat_by_id
    ]
    committed.sort(key=lambda r: r.amount, reverse=True)
    # A bill pointing at a category that no longer exists is as unclassified
    # as one with no category at all.
    orphaned = [b for cid, bills in bills_by_cat.items() if cid is None or cid not in cat_by_id for b in bills]
    if orphaned:
        committed.append(row(None, "Unclassified", orphaned))
    if parts.committed_savings:
        committed.append(schemas.CommittedRow(
            category_id=cat_id_by_name.get("Savings"), category_name="Savings", amount=parts.committed_savings,
        ))
    if parts.groceries_budget:
        committed.append(schemas.CommittedRow(
            category_id=cat_id_by_name.get("Groceries"), category_name="Groceries", amount=parts.groceries_budget,
        ))

    uncategorized = [i for i in items if i.category_id is None or i.category_id not in cat_by_id]

    assignable_ids = assignable_category_ids(db, user.id)
    allocations = db.query(models.BudgetAllocation).filter(
        models.BudgetAllocation.user_id == user.id,
        models.BudgetAllocation.year == year,
        models.BudgetAllocation.month.in_([0, month]),
        models.BudgetAllocation.category_id.in_(list(assignable_ids)),
    ).all() if assignable_ids else []
    allocations = drop_uncarried_defaults(allocations, user, assignable_ids)
    budget_by_cat: dict[int, Decimal] = {}
    for a in sorted(allocations, key=lambda x: x.month):  # month-specific wins
        budget_by_cat[a.category_id] = a.budgeted_amount

    assignable = [
        schemas.AssignableRow(
            category_id=c.id, category_name=c.name,
            assigned=budget_by_cat.get(c.id, ZERO), is_set=c.id in budget_by_cat,
        )
        for c in sorted((cat_by_id[i] for i in assignable_ids), key=lambda c: (c.sort_order, c.name))
    ]
    assigned_total = sum((r.assigned for r in assignable), ZERO)

    return schemas.LeftToBudgetOut(
        year=year, month=month,
        leftover=parts.leftover,
        committed=committed,
        unclassified_count=len(uncategorized),
        unclassified_amount=sum((monthly_equivalent(i) for i in uncategorized), ZERO),
        assignable=assignable,
        assigned_total=assigned_total,
        unassigned=parts.leftover - assigned_total,
        carry_forward=bool(user.budget_carry_forward),
    )
```

- [ ] **Step 6: Add the route**

In `backend/routers/budget.py`, after the `/overview` route:

```python
@router.get("/left-to-budget", response_model=schemas.LeftToBudgetOut)
def left_to_budget(
    year: int,
    month: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    if not 1 <= month <= 12:
        raise HTTPException(status_code=400, detail="month must be 1-12")
    from backend.services.left_to_budget import compute_left_to_budget
    return compute_left_to_budget(db, user, year, month)
```

(Add `HTTPException` to the `fastapi` import in that file if it is not already imported.)

- [ ] **Step 7: Run tests**

Run: `cd backend && python3 -m pytest tests/test_left_to_budget.py -v` → PASS.
Run: `cd backend && python3 -m pytest -q` → PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/services/budget_snapshot.py backend/services/left_to_budget.py backend/schemas.py backend/routers/budget.py backend/tests/test_left_to_budget.py
git commit -m "feat: left-to-budget endpoint with committed bills and assignable buckets"
```

---

### Task 4: Dismissals model, detector keys, and triage listing

**Files:**
- Modify: `backend/models.py` (add `RecurringDismissal` after `MerchantAlias`)
- Modify: `backend/schemas.py` (`RecurringSuggestion` ~line 537; append triage models)
- Modify: `backend/services/recurring_detector.py`
- Create: `backend/services/recurring_triage.py`
- Modify: `backend/routers/recurring.py` (GET `/triage`, placed right after `/suggestions`)
- Test: `backend/tests/test_recurring_triage.py` (create)

**Interfaces:**
- Consumes: `rules_engine.apply_rules`, `auto_categorizer.categorize`, `merchant_normalizer.normalize_merchant`, `recurring_math.monthly_equivalent`.
- Produces:
  - `models.RecurringDismissal(user_id, pattern_key)`
  - `RecurringSuggestion.pattern_key: str`
  - `recurring_detector.transactions_for_pattern(db, user_id, pattern_key) -> list[models.Transaction]`
  - `recurring_triage.guess_category(text: str, categories: list[models.Category], rules: list[models.TransactionRule]) -> models.Category | None`
  - `recurring_triage.duplicate_pair_key(a_id: int, b_id: int) -> str` → `"dup:<low>:<high>"`
  - `recurring_triage.build_triage(db, user_id) -> schemas.TriageOut`
  - `GET /recurring/triage` → `TriageOut`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_recurring_triage.py
from datetime import date, timedelta
from decimal import Decimal
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.dependencies import get_db, get_current_user
from backend.routers import recurring as recurring_router_module
from backend.services.recurring_detector import detect_patterns
from backend.services.recurring_triage import build_triage, duplicate_pair_key

E = models.CategoryType.expense
M = models.RecurringFrequency.monthly


def _client(db, user):
    app = FastAPI()
    app.include_router(recurring_router_module.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _seed(db):
    user = models.User(username="tr", hashed_password="x", display_name="TR")
    db.add(user); db.flush()
    acct = models.Account(user_id=user.id, name="Chk", type=models.AccountType.checking)
    home = models.Category(user_id=user.id, name="Home", type=E)
    subs = models.Category(user_id=user.id, name="Subscriptions", type=E)
    pets = models.Category(user_id=user.id, name="Pets", type=E)
    db.add_all([acct, home, subs, pets]); db.flush()

    def item(name, amount, cat=None, freq=M):
        i = models.RecurringItem(
            user_id=user.id, account_id=acct.id, category_id=cat.id if cat else None, name=name,
            amount=Decimal(amount), type=models.RecurringType.expense, frequency=freq,
            day_of_month=5, start_date=date(2026, 1, 1),
        )
        db.add(i); db.flush()
        return i

    items = {
        "hulu": item("Hulu", "18.00"),
        "trash": item("Trash service", "25.00"),
        "vet": item("Vet Plan", "40.00"),
        "netflix": item("Netflix", "15.49", subs),
        "netflix2": item("Netflix Standard", "15.49", subs),
        "electric": item("Electric", "150.00", home),
    }
    db.add(models.TransactionRule(
        user_id=user.id, name="Auto: vet", field=models.RuleField.description,
        pattern_type=models.RulePatternType.contains, pattern="vet plan",
        action=models.RuleAction.set_category, category_id=pets.id,
    ))
    today = date.today()
    for n in range(3):
        db.add(models.Transaction(
            user_id=user.id, account_id=acct.id, date=today - timedelta(days=30 * n + 1),
            amount=Decimal("-9.99"), description="ACME CLOUD STORAGE", is_actual=True,
        ))
    db.commit()
    return user, acct, {"home": home, "subs": subs, "pets": pets}, items


def test_uncategorized_items_listed_with_best_guess(db_session):
    user, _, cats, items = _seed(db_session)
    out = build_triage(db_session, user.id)
    by_name = {u.name: u for u in out.uncategorized}
    assert set(by_name) == {"Hulu", "Trash service", "Vet Plan"}
    assert by_name["Hulu"].guess_category_name == "Subscriptions"   # keyword
    assert by_name["Vet Plan"].guess_category_name == "Pets"        # rule beats keyword
    assert by_name["Trash service"].guess_category_id is None       # no weak guess


def test_badge_totals(db_session):
    user, *_ = _seed(db_session)
    out = build_triage(db_session, user.id)
    assert out.unclassified_count == 3
    assert out.unclassified_monthly_total == Decimal("83.00")


def test_untracked_patterns_carry_a_pattern_key(db_session):
    user, *_ = _seed(db_session)
    out = build_triage(db_session, user.id)
    assert [s.pattern_key for s in out.untracked] == ["acme cloud storage"]


def test_dismissed_pattern_is_hidden_from_detector(db_session):
    user, *_ = _seed(db_session)
    db_session.add(models.RecurringDismissal(user_id=user.id, pattern_key="acme cloud storage"))
    db_session.commit()
    assert detect_patterns(db_session, user.id) == []


def test_duplicates_flagged_and_dismissable(db_session):
    user, _, _, items = _seed(db_session)
    out = build_triage(db_session, user.id)
    key = duplicate_pair_key(items["netflix"].id, items["netflix2"].id)
    assert [d.pair_key for d in out.duplicates] == [key]

    db_session.add(models.RecurringDismissal(user_id=user.id, pattern_key=key))
    db_session.commit()
    assert build_triage(db_session, user.id).duplicates == []


def test_triage_route_is_not_swallowed_by_item_id_route(db_session):
    user, *_ = _seed(db_session)
    r = _client(db_session, user).get("/recurring/triage")
    assert r.status_code == 200
    assert r.json()["unclassified_count"] == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_recurring_triage.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_triage'` (module missing).

- [ ] **Step 3: Add the model**

In `backend/models.py`, after the `MerchantAlias` class:

```python
class RecurringDismissal(Base):
    """A triage suggestion the user said to stop showing.

    `pattern_key` is either a detector key (the normalized descriptor of a
    repeating charge the user marked "not recurring") or a duplicate pair key
    "dup:<low_id>:<high_id>" for two items the user said are distinct. Without
    this the inbox would re-offer the same answered question forever.
    """
    __tablename__ = "recurring_dismissals"
    __table_args__ = (UniqueConstraint("user_id", "pattern_key", name="uq_recurring_dismissal_user_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    pattern_key: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
```

(`create_tables()` at startup creates the new table; no ALTER needed.)

- [ ] **Step 4: Update detector**

In `backend/schemas.py`, `RecurringSuggestion` gets a new last field:

```python
    pattern_key: str = ""
```

In `backend/services/recurring_detector.py`:

1. Extract the transaction query into a helper and reuse it:

```python
def _candidate_transactions(db: Session, user_id: int) -> list[models.Transaction]:
    cutoff = date.today() - timedelta(days=395)  # ~13 months — enough for reliable pattern detection
    return (
        db.query(models.Transaction)
        .filter(
            models.Transaction.user_id == user_id,
            models.Transaction.is_actual == True,
            models.Transaction.amount < 0,
            models.Transaction.date >= cutoff,
            # (keep the existing recurring_item_id comment here verbatim)
            models.Transaction.recurring_item_id.is_(None),
        )
        .order_by(models.Transaction.date)
        .all()
    )


def transactions_for_pattern(db: Session, user_id: int, pattern_key: str) -> list[models.Transaction]:
    """The untracked transactions a detector suggestion was built from."""
    return [t for t in _candidate_transactions(db, user_id) if _normalize(t.description) == pattern_key]
```

2. In `detect_patterns`, replace the inline `cutoff`/`transactions = (...)` block with `transactions = _candidate_transactions(db, user_id)`.

3. After the `existing = {...}` set, add:

```python
    dismissed = {
        k for (k,) in db.query(models.RecurringDismissal.pattern_key)
        .filter(models.RecurringDismissal.user_id == user_id).all()
    }
```

and change `if key in existing:` to `if key in existing or key in dismissed:`.

4. Pass `pattern_key=key` in the `RecurringSuggestion(...)` constructor.

Run: `cd backend && python3 -m pytest tests/ -q -k "recurring or suggestion"` → PASS.

- [ ] **Step 5: Add triage schemas**

Append to `backend/schemas.py`:

```python
# ── Recurring Triage ──────────────────────────────────────────────────────────

class TriageItem(BaseModel):
    recurring_item_id: int
    name: str
    amount: Decimal
    frequency: RecurringFrequency
    monthly_amount: Decimal
    card_id: Optional[int] = None
    guess_category_id: Optional[int] = None
    guess_category_name: Optional[str] = None


class TriageSuggestion(BaseModel):
    pattern_key: str
    description: str
    median_amount: Decimal
    frequency: RecurringFrequency
    occurrences: int
    guess_category_id: Optional[int] = None
    guess_category_name: Optional[str] = None


class TriageDuplicate(BaseModel):
    pair_key: str
    a: TriageItem
    b: TriageItem


class TriageOut(BaseModel):
    uncategorized: list[TriageItem]
    untracked: list[TriageSuggestion]
    duplicates: list[TriageDuplicate]
    unclassified_count: int
    unclassified_monthly_total: Decimal
```

- [ ] **Step 6: Create the triage service (listing half)**

```python
# backend/services/recurring_triage.py
"""The "Needs a home" inbox: recurring charges that are uncategorized,
repeating but untracked, or probably entered twice -- plus the actions that
resolve them. Classification feeds reporting, so an unknown here is an
unknown in every rollup until it is answered.
"""
from __future__ import annotations
import re
from decimal import Decimal
from sqlalchemy.orm import Session
from backend import models, schemas
from backend.services.auto_categorizer import categorize
from backend.services.merchant_normalizer import normalize_merchant
from backend.services.recurring_detector import detect_patterns
from backend.services.recurring_math import monthly_equivalent
from backend.services.rules_engine import apply_rules

_WORD = re.compile(r"[a-z]{4,}")
DUPLICATE_AMOUNT_TOLERANCE = Decimal("0.10")


def guess_category(
    text: str,
    categories: list[models.Category],
    rules: list[models.TransactionRule],
) -> models.Category | None:
    """User rules first (they encode a decision already made), then the
    keyword table. No match returns None: a blank picker beats a wrong guess
    someone clicks through."""
    if not text:
        return None
    match = apply_rules(text, rules)
    if match and match.category_id and not match.is_transfer:
        hit = next((c for c in categories if c.id == match.category_id), None)
        if hit:
            return hit
    return categorize(text, categories)


def duplicate_pair_key(a_id: int, b_id: int) -> str:
    lo, hi = sorted((a_id, b_id))
    return f"dup:{lo}:{hi}"


def _first_word(name: str) -> str | None:
    m = _WORD.search(normalize_merchant(name).lower())
    return m.group(0) if m else None


def _expense_categories(db: Session, user_id: int) -> list[models.Category]:
    return db.query(models.Category).filter(
        models.Category.user_id == user_id,
        models.Category.type == models.CategoryType.expense,
    ).all()


def _rules(db: Session, user_id: int) -> list[models.TransactionRule]:
    return db.query(models.TransactionRule).filter(
        models.TransactionRule.user_id == user_id,
        models.TransactionRule.is_active == True,
    ).all()


def _latest_linked(db: Session, item_id: int) -> models.Transaction | None:
    return (
        db.query(models.Transaction)
        .filter(models.Transaction.recurring_item_id == item_id)
        .order_by(models.Transaction.date.desc())
        .first()
    )


def _item_out(db, item, categories, rules, with_guess: bool) -> schemas.TriageItem:
    guess = None
    if with_guess:
        guess = guess_category(item.name, categories, rules)
        if guess is None:
            latest = _latest_linked(db, item.id)
            guess = guess_category(latest.description, categories, rules) if latest else None
    return schemas.TriageItem(
        recurring_item_id=item.id, name=item.name, amount=item.amount,
        frequency=item.frequency, monthly_amount=monthly_equivalent(item),
        card_id=item.card_id,
        guess_category_id=guess.id if guess else None,
        guess_category_name=guess.name if guess else None,
    )


def _dismissed_keys(db: Session, user_id: int) -> set[str]:
    return {
        k for (k,) in db.query(models.RecurringDismissal.pattern_key)
        .filter(models.RecurringDismissal.user_id == user_id).all()
    }


def _find_duplicates(items: list[models.RecurringItem], dismissed: set[str]):
    """Heuristic flag only -- same frequency, amounts within 10%, same first
    significant word. The user decides; nothing is merged automatically."""
    pairs = []
    for i, a in enumerate(items):
        for b in items[i + 1:]:
            if a.frequency != b.frequency:
                continue
            wa, wb = _first_word(a.name), _first_word(b.name)
            if not wa or wa != wb:
                continue
            hi, lo = max(a.amount, b.amount), min(a.amount, b.amount)
            if hi <= 0 or (hi - lo) / hi > DUPLICATE_AMOUNT_TOLERANCE:
                continue
            key = duplicate_pair_key(a.id, b.id)
            if key not in dismissed:
                pairs.append((key, a, b))
    return pairs


def build_triage(db: Session, user_id: int) -> schemas.TriageOut:
    categories = _expense_categories(db, user_id)
    cat_ids = {c.id for c in categories}
    rules = _rules(db, user_id)
    dismissed = _dismissed_keys(db, user_id)

    items = db.query(models.RecurringItem).filter(
        models.RecurringItem.user_id == user_id,
        models.RecurringItem.type == models.RecurringType.expense,
        models.RecurringItem.is_active == True,
    ).order_by(models.RecurringItem.id).all()

    uncategorized = [i for i in items if i.category_id is None or i.category_id not in cat_ids]
    uncategorized_out = [_item_out(db, i, categories, rules, with_guess=True) for i in uncategorized]

    untracked = []
    for s in detect_patterns(db, user_id):
        guess = guess_category(s.description, categories, rules)
        untracked.append(schemas.TriageSuggestion(
            pattern_key=s.pattern_key, description=s.description,
            median_amount=s.median_amount, frequency=s.frequency, occurrences=s.occurrences,
            guess_category_id=guess.id if guess else None,
            guess_category_name=guess.name if guess else None,
        ))

    duplicates = [
        schemas.TriageDuplicate(
            pair_key=key,
            a=_item_out(db, a, categories, rules, with_guess=False),
            b=_item_out(db, b, categories, rules, with_guess=False),
        )
        for key, a, b in _find_duplicates(items, dismissed)
    ]

    return schemas.TriageOut(
        uncategorized=uncategorized_out,
        untracked=untracked,
        duplicates=duplicates,
        unclassified_count=len(uncategorized),
        unclassified_monthly_total=sum((o.monthly_amount for o in uncategorized_out), Decimal("0")),
    )
```

- [ ] **Step 7: Add the route**

In `backend/routers/recurring.py`, directly after the `get_suggestions` route (so it is before every `/{item_id}` route):

```python
@router.get("/triage", response_model=schemas.TriageOut)
def get_triage(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    from backend.services.recurring_triage import build_triage
    return build_triage(db, user.id)
```

- [ ] **Step 8: Run tests**

Run: `cd backend && python3 -m pytest tests/test_recurring_triage.py -v` → PASS.
Run: `cd backend && python3 -m pytest -q` → PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/models.py backend/schemas.py backend/services/recurring_detector.py backend/services/recurring_triage.py backend/routers/recurring.py backend/tests/test_recurring_triage.py
git commit -m "feat: recurring triage inbox listing with best-guess categories and duplicate flags"
```

---

### Task 5: Triage actions — classify, dismiss, duplicate

**Files:**
- Modify: `backend/services/recurring_triage.py` (append)
- Modify: `backend/schemas.py` (append action models)
- Modify: `backend/routers/recurring.py` (three POST routes right after `get_triage`)
- Test: `backend/tests/test_recurring_triage_actions.py` (create)

**Interfaces:**
- Consumes: Task 4's `guess_category`, `_latest_linked`, `duplicate_pair_key`, `transactions_for_pattern`, `detect_patterns`.
- Produces:
  - `recurring_triage.TriageError(Exception)` (→ 400), `recurring_triage.TriageNotFound(Exception)` (→ 404)
  - `classify(db, user_id, body: schemas.TriageClassify) -> schemas.TriageClassifyResult`
  - `dismiss(db, user_id, pattern_key: str) -> None`
  - `mark_duplicate(db, user_id, keep_id: int, deactivate_id: int) -> schemas.TriageDuplicateResult`
  - `POST /recurring/triage/classify`, `POST /recurring/triage/dismiss`, `POST /recurring/triage/duplicate`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_recurring_triage_actions.py
from datetime import date, timedelta
from decimal import Decimal
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.dependencies import get_db, get_current_user
from backend.routers import recurring as recurring_router_module

E = models.CategoryType.expense
DESC = "ACME CLOUD STORAGE"


def _client(db, user):
    app = FastAPI()
    app.include_router(recurring_router_module.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _seed(db):
    user = models.User(username="ta", hashed_password="x", display_name="TA")
    other = models.User(username="tb", hashed_password="x", display_name="TB")
    db.add_all([user, other]); db.flush()
    acct = models.Account(user_id=user.id, name="Chk", type=models.AccountType.checking)
    card = models.CreditCard(user_id=user.id, name="Card", credit_limit=Decimal("1000"), statement_day=1, due_day=20)
    home = models.Category(user_id=user.id, name="Home", type=E)
    subs = models.Category(user_id=user.id, name="Subscriptions", type=E)
    manual = models.Category(user_id=user.id, name="Manual pick", type=E)
    income = models.Category(user_id=user.id, name="Income", type=models.CategoryType.income)
    foreign = models.Category(user_id=other.id, name="Theirs", type=E)
    db.add_all([acct, card, home, subs, manual, income, foreign]); db.flush()

    trash = models.RecurringItem(
        user_id=user.id, account_id=acct.id, name="Trash service", amount=Decimal("25.00"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=5, start_date=date(2026, 1, 1),
    )
    hulu = models.RecurringItem(
        user_id=user.id, account_id=acct.id, card_id=card.id, name="Hulu", amount=Decimal("18.00"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=9, start_date=date(2026, 1, 1),
    )
    db.add_all([trash, hulu]); db.flush()
    db.add_all([
        models.Transaction(user_id=user.id, account_id=acct.id, recurring_item_id=trash.id, date=date(2026, 8, 5),
                           amount=Decimal("-25.00"), description="CITY TRASH 8812", is_actual=True),
        models.Transaction(user_id=user.id, account_id=acct.id, recurring_item_id=trash.id, date=date(2026, 9, 5),
                           amount=Decimal("-25.00"), description="CITY TRASH 8812", is_actual=True, category_id=manual.id),
        models.CreditCardTransaction(user_id=user.id, card_id=card.id, date=date(2026, 9, 9),
                                     amount=Decimal("18.00"), merchant="HULU 877-8244858"),
    ])
    today = date.today()
    for n in range(3):
        db.add(models.Transaction(
            user_id=user.id, account_id=acct.id, date=today - timedelta(days=30 * n + 1),
            amount=Decimal("-9.99"), description=DESC, is_actual=True,
        ))
    db.commit()
    return user, acct, {"home": home, "subs": subs, "manual": manual, "income": income, "foreign": foreign}, {"trash": trash, "hulu": hulu}


def test_classify_item_sets_category_creates_rule_and_backfills_only_null(db_session):
    user, _, cats, items = _seed(db_session)
    c = _client(db_session, user)
    r = c.post("/recurring/triage/classify", json={"recurring_item_id": items["trash"].id, "category_id": cats["home"].id})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rule_created"] is True
    assert body["backfilled"] == 1
    db_session.expire_all()
    assert db_session.get(models.RecurringItem, items["trash"].id).category_id == cats["home"].id
    txns = db_session.query(models.Transaction).filter(models.Transaction.recurring_item_id == items["trash"].id).all()
    assert sorted(t.category_id for t in txns) == sorted([cats["home"].id, cats["manual"].id])  # manual kept
    rule = db_session.get(models.TransactionRule, body["rule_id"])
    assert rule.pattern == "CITY TRASH 8812" and rule.category_id == cats["home"].id


def test_classify_twice_does_not_duplicate_rule(db_session):
    user, _, cats, items = _seed(db_session)
    c = _client(db_session, user)
    payload = {"recurring_item_id": items["trash"].id, "category_id": cats["home"].id}
    c.post("/recurring/triage/classify", json=payload)
    second = c.post("/recurring/triage/classify", json=payload).json()
    assert second["rule_created"] is False
    assert db_session.query(models.TransactionRule).count() == 1


def test_classify_card_item_backfills_matching_uncategorized_card_rows(db_session):
    user, _, cats, items = _seed(db_session)
    r = _client(db_session, user).post("/recurring/triage/classify", json={"recurring_item_id": items["hulu"].id, "category_id": cats["subs"].id}).json()
    assert r["backfilled"] == 1
    row = db_session.query(models.CreditCardTransaction).one()
    db_session.refresh(row)
    assert row.category_id == cats["subs"].id


def test_classify_untracked_pattern_creates_linked_item(db_session):
    user, acct, cats, _ = _seed(db_session)
    r = _client(db_session, user).post("/recurring/triage/classify", json={"pattern_key": "acme cloud storage", "category_id": cats["subs"].id})
    assert r.status_code == 200, r.text
    item = db_session.get(models.RecurringItem, r.json()["recurring_item_id"])
    assert item.category_id == cats["subs"].id
    assert item.amount == Decimal("9.99")
    assert item.account_id == acct.id
    linked = db_session.query(models.Transaction).filter(models.Transaction.recurring_item_id == item.id).count()
    assert linked == 3


def test_classify_rejects_bad_category_and_bad_body(db_session):
    user, _, cats, items = _seed(db_session)
    c = _client(db_session, user)
    for cat in ("income", "foreign"):
        r = c.post("/recurring/triage/classify", json={"recurring_item_id": items["trash"].id, "category_id": cats[cat].id})
        assert r.status_code == 400, cat
    assert c.post("/recurring/triage/classify", json={"category_id": cats["home"].id}).status_code == 422
    assert c.post("/recurring/triage/classify", json={"recurring_item_id": 999999, "category_id": cats["home"].id}).status_code == 404
    assert c.post("/recurring/triage/classify", json={"pattern_key": "nope", "category_id": cats["home"].id}).status_code == 404


def test_dismiss_is_idempotent(db_session):
    user, *_ = _seed(db_session)
    c = _client(db_session, user)
    assert c.post("/recurring/triage/dismiss", json={"pattern_key": "acme cloud storage"}).status_code == 200
    assert c.post("/recurring/triage/dismiss", json={"pattern_key": "acme cloud storage"}).status_code == 200
    assert db_session.query(models.RecurringDismissal).count() == 1


def test_duplicate_deactivates_and_relinks_never_deletes(db_session):
    user, _, _, items = _seed(db_session)
    c = _client(db_session, user)
    r = c.post("/recurring/triage/duplicate", json={"keep_id": items["hulu"].id, "deactivate_id": items["trash"].id})
    assert r.status_code == 200
    assert r.json()["relinked"] == 2
    db_session.expire_all()
    gone = db_session.get(models.RecurringItem, items["trash"].id)
    assert gone is not None and gone.is_active is False
    assert db_session.query(models.Transaction).filter(models.Transaction.recurring_item_id == items["hulu"].id).count() == 2


def test_duplicate_rejects_same_or_inactive(db_session):
    user, _, _, items = _seed(db_session)
    c = _client(db_session, user)
    assert c.post("/recurring/triage/duplicate", json={"keep_id": items["hulu"].id, "deactivate_id": items["hulu"].id}).status_code == 400
    items["trash"].is_active = False
    db_session.commit()
    assert c.post("/recurring/triage/duplicate", json={"keep_id": items["hulu"].id, "deactivate_id": items["trash"].id}).status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_recurring_triage_actions.py -v`
Expected: FAIL — 404/405 on `/recurring/triage/classify` (route missing).

- [ ] **Step 3: Add action schemas**

Append to `backend/schemas.py` (and add `model_validator` to the existing `from pydantic import ...` line):

```python
class TriageClassify(BaseModel):
    category_id: int
    recurring_item_id: Optional[int] = None
    pattern_key: Optional[str] = None

    @model_validator(mode="after")
    def _exactly_one_target(self):
        if (self.recurring_item_id is None) == (self.pattern_key is None):
            raise ValueError("provide exactly one of recurring_item_id or pattern_key")
        return self


class TriageClassifyResult(BaseModel):
    recurring_item_id: int
    category_id: int
    rule_id: Optional[int] = None
    rule_created: bool = False
    backfilled: int = 0


class TriageDismiss(BaseModel):
    pattern_key: str


class TriageDuplicateAction(BaseModel):
    keep_id: int
    deactivate_id: int


class TriageDuplicateResult(BaseModel):
    deactivated_id: int
    relinked: int
```

- [ ] **Step 4: Implement the actions**

Append to `backend/services/recurring_triage.py` (add `from backend.services.recurring_detector import transactions_for_pattern` to its imports):

```python
class TriageError(Exception):
    """Request is well-formed but not allowed (-> 400)."""


class TriageNotFound(Exception):
    """Target item or pattern doesn't exist for this user (-> 404)."""


def _expense_category_or_error(db: Session, user_id: int, category_id: int) -> models.Category:
    cat = db.query(models.Category).filter(
        models.Category.id == category_id,
        models.Category.user_id == user_id,
    ).first()
    if cat is None or cat.type != models.CategoryType.expense:
        raise TriageError("category must be one of your expense categories")
    return cat


def _ensure_rule(db: Session, user_id: int, label: str, pattern: str, category_id: int) -> tuple[int, bool]:
    existing = db.query(models.TransactionRule).filter(
        models.TransactionRule.user_id == user_id,
        models.TransactionRule.pattern == pattern,
        models.TransactionRule.category_id == category_id,
    ).first()
    if existing:
        return existing.id, False
    rule = models.TransactionRule(
        user_id=user_id, name=f"Auto: {label}"[:128],
        field=models.RuleField.merchant, pattern_type=models.RulePatternType.contains,
        pattern=pattern[:256], action=models.RuleAction.set_category, category_id=category_id,
    )
    db.add(rule)
    db.flush()
    return rule.id, True


def _classify_item(db, user_id, item_id, cat) -> schemas.TriageClassifyResult:
    item = db.query(models.RecurringItem).filter(
        models.RecurringItem.id == item_id,
        models.RecurringItem.user_id == user_id,
    ).first()
    if item is None:
        raise TriageNotFound("recurring item not found")
    item.category_id = cat.id

    latest = _latest_linked(db, item.id)
    pattern = latest.description if latest else item.name
    rule_id, created = _ensure_rule(db, user_id, item.name, pattern, cat.id)

    # Only rows nobody has categorized yet -- a category set by hand or by an
    # earlier rule is a decision, and this must never overwrite it.
    backfilled = 0
    for t in db.query(models.Transaction).filter(
        models.Transaction.recurring_item_id == item.id,
        models.Transaction.category_id.is_(None),
    ).all():
        t.category_id = cat.id
        backfilled += 1
    # Card rows have no recurring_item_id, so match them on merchant within
    # the item's own card.
    if item.card_id:
        for t in db.query(models.CreditCardTransaction).filter(
            models.CreditCardTransaction.user_id == user_id,
            models.CreditCardTransaction.card_id == item.card_id,
            models.CreditCardTransaction.category_id.is_(None),
            models.CreditCardTransaction.merchant.ilike(f"%{pattern}%"),
        ).all():
            t.category_id = cat.id
            backfilled += 1

    db.commit()
    return schemas.TriageClassifyResult(
        recurring_item_id=item.id, category_id=cat.id,
        rule_id=rule_id, rule_created=created, backfilled=backfilled,
    )


def _classify_pattern(db, user_id, pattern_key, cat) -> schemas.TriageClassifyResult:
    suggestion = next((s for s in detect_patterns(db, user_id) if s.pattern_key == pattern_key), None)
    txns = transactions_for_pattern(db, user_id, pattern_key)
    if suggestion is None or not txns:
        raise TriageNotFound("pattern not found")
    latest = max(txns, key=lambda t: t.date)

    item = models.RecurringItem(
        user_id=user_id, account_id=latest.account_id, category_id=cat.id,
        name=normalize_merchant(latest.description)[:128],
        amount=suggestion.median_amount, type=models.RecurringType.expense,
        frequency=models.RecurringFrequency(suggestion.frequency),
        day_of_month=latest.date.day, start_date=latest.date, is_active=True,
    )
    db.add(item)
    db.flush()

    backfilled = 0
    for t in txns:
        t.recurring_item_id = item.id
        if t.category_id is None:
            t.category_id = cat.id
            backfilled += 1
    rule_id, created = _ensure_rule(db, user_id, item.name, latest.description, cat.id)
    db.commit()
    return schemas.TriageClassifyResult(
        recurring_item_id=item.id, category_id=cat.id,
        rule_id=rule_id, rule_created=created, backfilled=backfilled,
    )


def classify(db: Session, user_id: int, body: schemas.TriageClassify) -> schemas.TriageClassifyResult:
    cat = _expense_category_or_error(db, user_id, body.category_id)
    if body.recurring_item_id is not None:
        return _classify_item(db, user_id, body.recurring_item_id, cat)
    return _classify_pattern(db, user_id, body.pattern_key, cat)


def dismiss(db: Session, user_id: int, pattern_key: str) -> None:
    exists = db.query(models.RecurringDismissal).filter(
        models.RecurringDismissal.user_id == user_id,
        models.RecurringDismissal.pattern_key == pattern_key,
    ).first()
    if exists is None:
        db.add(models.RecurringDismissal(user_id=user_id, pattern_key=pattern_key[:256]))
        db.commit()


def mark_duplicate(db: Session, user_id: int, keep_id: int, deactivate_id: int) -> schemas.TriageDuplicateResult:
    if keep_id == deactivate_id:
        raise TriageError("keep_id and deactivate_id must differ")
    found = {
        i.id: i for i in db.query(models.RecurringItem).filter(
            models.RecurringItem.user_id == user_id,
            models.RecurringItem.id.in_([keep_id, deactivate_id]),
        ).all()
    }
    if len(found) != 2:
        raise TriageNotFound("recurring item not found")
    if not (found[keep_id].is_active and found[deactivate_id].is_active):
        raise TriageError("both items must be active")

    found[deactivate_id].is_active = False
    relinked = 0
    for t in db.query(models.Transaction).filter(models.Transaction.recurring_item_id == deactivate_id).all():
        t.recurring_item_id = keep_id
        relinked += 1
    db.commit()
    return schemas.TriageDuplicateResult(deactivated_id=deactivate_id, relinked=relinked)
```

- [ ] **Step 5: Add the routes**

In `backend/routers/recurring.py`, directly after `get_triage`:

```python
def _triage_call(fn, *args):
    from backend.services.recurring_triage import TriageError, TriageNotFound
    try:
        return fn(*args)
    except TriageNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except TriageError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/triage/classify", response_model=schemas.TriageClassifyResult)
def triage_classify(
    body: schemas.TriageClassify,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    from backend.services.recurring_triage import classify
    return _triage_call(classify, db, user.id, body)


@router.post("/triage/dismiss")
def triage_dismiss(
    body: schemas.TriageDismiss,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    from backend.services.recurring_triage import dismiss
    _triage_call(dismiss, db, user.id, body.pattern_key)
    return {"ok": True}


@router.post("/triage/duplicate", response_model=schemas.TriageDuplicateResult)
def triage_duplicate(
    body: schemas.TriageDuplicateAction,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    from backend.services.recurring_triage import mark_duplicate
    return _triage_call(mark_duplicate, db, user.id, body.keep_id, body.deactivate_id)
```

- [ ] **Step 6: Run tests**

Run: `cd backend && python3 -m pytest tests/test_recurring_triage_actions.py tests/test_recurring_triage.py -v` → PASS.
Run: `cd backend && python3 -m pytest -q` → PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/services/recurring_triage.py backend/schemas.py backend/routers/recurring.py backend/tests/test_recurring_triage_actions.py
git commit -m "feat: triage actions to classify, dismiss, and mark duplicate recurring charges"
```

---

### Task 6: Frontend — triage inbox on Recurring page + nav badge

**Files:**
- Modify: `frontend/src/api/index.ts` (`recurringApi`, ~line 83)
- Create: `frontend/src/components/TriageInbox.tsx`
- Modify: `frontend/src/pages/Recurring.tsx` (mount above the item list in the main `return (` at ~line 258)
- Modify: `frontend/src/lib/navItems.ts` (`NavItem` gets `badgeKey?`)
- Modify: `frontend/src/components/Layout.tsx` (render badge at lines ~144 and ~157)

**Interfaces:**
- Consumes: `GET /recurring/triage`, `POST /recurring/triage/{classify,dismiss,duplicate}` (Tasks 4-5); `categoriesApi.list`; `CategoryOptions` from `lib/selectOptions`.
- Produces: `recurringApi.triage()`, `recurringApi.triageClassify(data)`, `recurringApi.triageDismiss(patternKey)`, `recurringApi.triageDuplicate(keepId, deactivateId)`; React Query key `["recurring-triage"]`.

- [ ] **Step 1: API client**

Add inside `recurringApi` in `frontend/src/api/index.ts`:

```ts
  triage: () => api.get("/recurring/triage").then((r) => r.data),
  triageClassify: (data: { category_id: number; recurring_item_id?: number; pattern_key?: string }) =>
    api.post("/recurring/triage/classify", data).then((r) => r.data),
  triageDismiss: (patternKey: string) =>
    api.post("/recurring/triage/dismiss", { pattern_key: patternKey }).then((r) => r.data),
  triageDuplicate: (keepId: number, deactivateId: number) =>
    api.post("/recurring/triage/duplicate", { keep_id: keepId, deactivate_id: deactivateId }).then((r) => r.data),
```

- [ ] **Step 2: Create the component**

```tsx
// frontend/src/components/TriageInbox.tsx
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { recurringApi, categoriesApi } from "../api";
import { fmt } from "../lib/utils";
import { CategoryOptions } from "../lib/selectOptions";
import { Inbox, Check, X, Copy } from "lucide-react";

/**
 * "Needs a home": recurring charges with no category, repeating charges
 * nobody is tracking yet, and probable duplicates. Each answer also teaches
 * a merchant rule server-side, so the same charge never lands here twice.
 */
export default function TriageInbox() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["recurring-triage"], queryFn: recurringApi.triage });
  const { data: categories = [] } = useQuery({ queryKey: ["categories"], queryFn: categoriesApi.list });
  const [picks, setPicks] = useState<Record<string, string>>({});
  const [open, setOpen] = useState(true);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["recurring-triage"] });
    qc.invalidateQueries({ queryKey: ["recurring"] });
    qc.invalidateQueries({ queryKey: ["left-to-budget"] });
  };
  const classify = useMutation({ mutationFn: recurringApi.triageClassify, onSuccess: refresh });
  const dismiss = useMutation({ mutationFn: recurringApi.triageDismiss, onSuccess: refresh });
  const duplicate = useMutation({
    mutationFn: ({ keep, drop }: { keep: number; drop: number }) => recurringApi.triageDuplicate(keep, drop),
    onSuccess: refresh,
  });

  if (!data) return null;
  const total = data.uncategorized.length + data.untracked.length + data.duplicates.length;
  if (total === 0) return null;

  const pickFor = (key: string, guess: number | null) => picks[key] ?? (guess ? String(guess) : "");

  function CategoryPicker({ rowKey, guess }: { rowKey: string; guess: number | null }) {
    return (
      <select
        className="input text-sm w-48"
        value={pickFor(rowKey, guess)}
        onChange={(e) => setPicks((p) => ({ ...p, [rowKey]: e.target.value }))}
      >
        <option value="">Choose a category…</option>
        <CategoryOptions categories={categories} type="expense" />
      </select>
    );
  }

  return (
    <div className="card border-amber-200 dark:border-amber-800">
      <button className="flex w-full items-center justify-between" onClick={() => setOpen(!open)}>
        <span className="flex items-center gap-2 font-semibold text-gray-800 dark:text-gray-100">
          <Inbox size={18} className="text-amber-500" /> Needs a home
        </span>
        <span className="text-sm text-amber-600 dark:text-amber-400">
          {data.unclassified_count} unclassified · {fmt(data.unclassified_monthly_total)}/mo
        </span>
      </button>

      {open && (
        <div className="mt-3 divide-y divide-gray-100 dark:divide-gray-700">
          {data.uncategorized.map((u: any) => {
            const key = `item:${u.recurring_item_id}`;
            const chosen = pickFor(key, u.guess_category_id);
            return (
              <div key={key} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <div>
                  <p className="text-sm font-medium">{u.name}</p>
                  <p className="text-xs text-gray-400">
                    {fmt(u.amount)} {u.frequency}
                    {u.guess_category_name && <> · best guess: {u.guess_category_name}</>}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <CategoryPicker rowKey={key} guess={u.guess_category_id} />
                  <button
                    className="btn-primary text-xs px-2 py-1"
                    disabled={!chosen || classify.isPending}
                    onClick={() => classify.mutate({ recurring_item_id: u.recurring_item_id, category_id: Number(chosen) })}
                  >
                    <Check size={14} />
                  </button>
                </div>
              </div>
            );
          })}

          {data.untracked.map((s: any) => {
            const key = `pattern:${s.pattern_key}`;
            const chosen = pickFor(key, s.guess_category_id);
            return (
              <div key={key} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <div>
                  <p className="text-sm font-medium">{s.description}</p>
                  <p className="text-xs text-gray-400">
                    Repeats {s.frequency} · {fmt(s.median_amount)} · seen {s.occurrences}×
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <CategoryPicker rowKey={key} guess={s.guess_category_id} />
                  <button
                    className="btn-primary text-xs px-2 py-1"
                    disabled={!chosen || classify.isPending}
                    onClick={() => classify.mutate({ pattern_key: s.pattern_key, category_id: Number(chosen) })}
                  >
                    <Check size={14} />
                  </button>
                  <button className="btn-secondary py-1 px-2 text-xs" onClick={() => dismiss.mutate(s.pattern_key)}>
                    Not recurring
                  </button>
                </div>
              </div>
            );
          })}

          {data.duplicates.map((d: any) => (
            <div key={d.pair_key} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <p className="flex items-center gap-2 text-sm">
                <Copy size={14} className="text-gray-400" />
                <span className="font-medium">{d.a.name}</span> and <span className="font-medium">{d.b.name}</span>
                <span className="text-xs text-gray-400">look like the same bill</span>
              </p>
              <div className="flex items-center gap-2">
                <button className="btn-secondary py-1 px-2 text-xs"
                  onClick={() => duplicate.mutate({ keep: d.a.recurring_item_id, drop: d.b.recurring_item_id })}>
                  Keep {d.a.name}
                </button>
                <button className="btn-secondary py-1 px-2 text-xs"
                  onClick={() => duplicate.mutate({ keep: d.b.recurring_item_id, drop: d.a.recurring_item_id })}>
                  Keep {d.b.name}
                </button>
                <button className="btn-ghost p-1" title="Not a duplicate" onClick={() => dismiss.mutate(d.pair_key)}>
                  <X size={14} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

If `CategoryOptions` requires the `exclude` prop or the categories query uses a different key elsewhere on the Recurring page, match what `Recurring.tsx` already uses (read its `useQuery` for categories and reuse the same `queryKey`).

- [ ] **Step 3: Mount it**

In `frontend/src/pages/Recurring.tsx`: `import TriageInbox from "../components/TriageInbox";` and render `<TriageInbox />` as the first child after the page header inside the main `return (` (~line 258). Also confirm the page's recurring list query key; if it is not `["recurring"]`, change the `invalidateQueries` key in `TriageInbox.refresh` to match.

- [ ] **Step 4: Nav badge**

`frontend/src/lib/navItems.ts`: add `badgeKey?: "triage";` to `NavItem`, and set it on the Recurring item: `{ to: "/recurring", icon: Repeat, label: "Recurring", badgeKey: "triage" }`.

`frontend/src/components/Layout.tsx`: import `recurringApi` alongside the existing api imports, then near the other `useQuery` calls:

```tsx
  const { data: triage } = useQuery({ queryKey: ["recurring-triage"], queryFn: recurringApi.triage, staleTime: 60_000 });
  const triageCount = triage?.unclassified_count ?? 0;
  const badgeFor = (item: { badgeKey?: string }) =>
    item.badgeKey === "triage" && triageCount > 0 ? (
      <span className="ml-auto rounded-full bg-amber-100 px-1.5 text-[11px] font-semibold text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">
        {triageCount}
      </span>
    ) : null;
```

and add `{badgeFor(item)}` immediately after `{item.label}` at both desktop render sites (~lines 144 and 157).

- [ ] **Step 5: Type-check**

Run: `cd frontend && bun run build` → exits 0.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/index.ts frontend/src/components/TriageInbox.tsx frontend/src/pages/Recurring.tsx frontend/src/lib/navItems.ts frontend/src/components/Layout.tsx
git commit -m "feat: Needs-a-home triage inbox on Recurring page with nav badge"
```

---

### Task 7: Frontend — Left to budget panel + carry-forward setting

**Files:**
- Modify: `frontend/src/api/index.ts` (`budgetApi`, ~line 130)
- Create: `frontend/src/components/LeftToBudgetPanel.tsx`
- Modify: `frontend/src/pages/Budget.tsx` (mount above the Track/Set tabs)
- Modify: `frontend/src/pages/settings/PreferencesTab.tsx` (toggle next to Savings Strategy, ~line 140)

**Interfaces:**
- Consumes: `GET /budget/left-to-budget` (Task 3); existing `POST /budget` upsert (`{category_id, year, month, budgeted_amount}`); `authApi.me` / `authApi.updateMe` with `budget_carry_forward` (Task 2).
- Produces: `budgetApi.leftToBudget(year, month)`; React Query key `["left-to-budget", year, month]`.

- [ ] **Step 1: API client**

Add inside `budgetApi`:

```ts
  leftToBudget: (year: number, month: number) =>
    api.get("/budget/left-to-budget", { params: { year, month } }).then((r) => r.data),
```

- [ ] **Step 2: Create the component**

```tsx
// frontend/src/components/LeftToBudgetPanel.tsx
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { budgetApi } from "../api";
import { fmt, cx } from "../lib/utils";
import { ChevronDown, ChevronRight } from "lucide-react";

/**
 * Zero-based view of the month. Committed lines come from recurring bills
 * (plus Savings and Groceries) and are read-only here; the rest of the
 * leftover is assigned to a few buckets until "unassigned" reaches $0.
 */
export default function LeftToBudgetPanel({ year, month }: { year: number; month: number }) {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["left-to-budget", year, month],
    queryFn: () => budgetApi.leftToBudget(year, month),
  });
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [drafts, setDrafts] = useState<Record<number, string>>({});

  const save = useMutation({
    mutationFn: ({ category_id, amount }: { category_id: number; amount: string }) =>
      budgetApi.upsert({ category_id, year, month, budgeted_amount: amount }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["left-to-budget", year, month] });
      qc.invalidateQueries({ queryKey: ["budget"] });
    },
  });

  if (!data) return null;
  const unassigned = Number(data.unassigned);
  const tone = unassigned === 0 ? "text-emerald-600" : unassigned > 0 ? "text-amber-600" : "text-red-600";
  const barTone = unassigned === 0 ? "bg-emerald-500" : unassigned > 0 ? "bg-amber-500" : "bg-red-500";
  const leftover = Number(data.leftover);
  const pct = leftover > 0 ? Math.min(100, (Number(data.assigned_total) / leftover) * 100) : 100;

  const toggle = (k: string) =>
    setExpanded((s) => { const n = new Set(s); n.has(k) ? n.delete(k) : n.add(k); return n; });

  return (
    <div className="card space-y-4">
      <div>
        <div className="flex items-baseline justify-between">
          <h2 className="font-semibold">Left to budget</h2>
          <span className={cx("text-lg font-semibold", tone)}>
            {fmt(data.unassigned)} {unassigned < 0 ? "over-assigned" : "unassigned"}
          </span>
        </div>
        <p className="text-xs text-gray-400">
          {fmt(data.leftover)} left after committed · {fmt(data.assigned_total)} assigned
        </p>
        <div className="mt-2 h-2 w-full rounded bg-gray-100 dark:bg-gray-700">
          <div className={cx("h-2 rounded", barTone)} style={{ width: `${pct}%` }} />
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-400">Committed</h3>
          {data.committed.map((r: any) => {
            const k = `${r.category_id ?? "none"}:${r.category_name}`;
            const isOpen = expanded.has(k);
            return (
              <div key={k} className="py-1">
                <button className="flex w-full items-center justify-between text-sm" onClick={() => r.items.length && toggle(k)}>
                  <span className="flex items-center gap-1">
                    {r.items.length > 0 && (isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />)}
                    {r.category_name === "Unclassified"
                      ? <Link to="/recurring" className="text-amber-600 underline">Unclassified</Link>
                      : r.category_name}
                  </span>
                  <span>{fmt(r.amount)}</span>
                </button>
                {isOpen && r.items.map((b: any) => (
                  <div key={b.recurring_item_id} className="flex justify-between pl-5 text-xs text-gray-500">
                    <span>{b.name}</span><span>{fmt(b.amount)}</span>
                  </div>
                ))}
              </div>
            );
          })}
        </div>

        <div>
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-400">Assign</h3>
          {data.assignable.map((a: any) => (
            <div key={a.category_id} className="flex items-center justify-between gap-2 py-1 text-sm">
              <span>
                {a.category_name}
                {!a.is_set && <span className="ml-2 text-xs text-gray-400">not assigned yet</span>}
              </span>
              <input
                type="number" step="0.01" min="0"
                className="input w-28 text-right text-sm"
                value={drafts[a.category_id] ?? (a.is_set ? a.assigned : "")}
                placeholder="0.00"
                onChange={(e) => setDrafts((d) => ({ ...d, [a.category_id]: e.target.value }))}
                onBlur={(e) => {
                  const v = e.target.value;
                  if (v !== "" && v !== String(a.assigned)) save.mutate({ category_id: a.category_id, amount: v });
                }}
              />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
```

Before writing, confirm the Budget page's own allocation query key (search `useQuery` in `Budget.tsx`); if it is not `["budget"]`-prefixed, invalidate that key instead in `onSuccess`.

- [ ] **Step 3: Mount on Budget page**

In `frontend/src/pages/Budget.tsx`: `import LeftToBudgetPanel from "../components/LeftToBudgetPanel";` and render `<LeftToBudgetPanel year={year} month={month} />` directly above the Track/Set tab switcher in the returned JSX (uses the page's existing `year`/`month` state from the month picker).

- [ ] **Step 4: Settings toggle**

In `frontend/src/pages/settings/PreferencesTab.tsx`, directly after the Savings Strategy block (the `<div className="pt-3 border-t ...">` that ends after its `</select>`), add:

```tsx
      {/* Zero-based by default: a new month's buckets start unassigned. On,
          an unset month inherits the all-months amount instead. */}
      <div className="pt-3 border-t border-gray-100 dark:border-gray-700">
        <div className="flex items-center justify-between gap-3">
          <div>
            <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Carry budget amounts into the next month</span>
            <p className="text-xs text-gray-400">
              {me?.budget_carry_forward
                ? "On — a month you haven't assigned uses your all-months amounts."
                : "Off — each month starts unassigned until you assign it on the Budget page."}
            </p>
          </div>
          <input
            type="checkbox"
            className="h-4 w-4"
            checked={!!me?.budget_carry_forward}
            onChange={() => taxMut.mutate(
              { budget_carry_forward: !me?.budget_carry_forward },
              { onSuccess: () => { qc.invalidateQueries({ queryKey: ["me"] }); qc.invalidateQueries({ queryKey: ["left-to-budget"] }); } },
            )}
          />
        </div>
      </div>
```

If `PreferencesTab` has no `qc` in scope, add `const qc = useQueryClient();` (import `useQueryClient` from `@tanstack/react-query`).

- [ ] **Step 5: Type-check**

Run: `cd frontend && bun run build` → exits 0.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/index.ts frontend/src/components/LeftToBudgetPanel.tsx frontend/src/pages/Budget.tsx frontend/src/pages/settings/PreferencesTab.tsx
git commit -m "feat: Left to budget panel on Budget page and carry-forward setting"
```

---

### Task 8: Verification and graph refresh

**Files:** none new (verification only; fixes found here go in their own commits).

- [ ] **Step 1: Full backend suite**

Run: `cd backend && python3 -m pytest -q` → all PASS.

- [ ] **Step 2: Frontend build**

Run: `cd frontend && bun run build` → exits 0.

- [ ] **Step 3: Back up the live DB before first run of the new migration**

Use the app's `backup_database()` (never `cp budget.db` — WAL makes that stale). Then restart the stack so `upgrade_schema()` and `upgrade_categories()` run.

- [ ] **Step 4: Real-Chrome verification with Interceptor**

With the app running, verify each and capture console errors / failed requests:
1. Sidebar shows the Recurring badge with the unclassified count.
2. Recurring page: "Needs a home" lists uncategorized items with best guesses; confirming one removes it, the badge decrements, and the item shows its category.
3. "Not recurring" and "Not a duplicate" remove their rows and they stay gone after reload.
4. Budget page: Left to budget bar shows; committed Home row expands into bills; Unclassified links to /recurring; assigning a bucket updates unassigned and the bar colour (green at $0, amber above, red below).
5. Settings → Preferences toggle flips carry-forward; Budget page buckets switch between "not assigned yet" and all-months amounts.
6. Dashboard Left to Spend and Safety Margin show the same values as before deploy.

- [ ] **Step 5: Refresh the knowledge graph**

Run: `graphify update .`

- [ ] **Step 6: Final whole-branch review**

Dispatch one final review over all commits from this plan (per-task reviews can't see cross-task interactions such as the carry-forward rule and the committed-list math disagreeing). If it surfaces a design-level issue, stop and raise it with Dan before pushing.
