# "How is this calculated?" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every heavily calculated number on Dashboard, Budget, and Recurring gets an ⓘ that shows its real, replayable math.

**Architecture:** A small backend `ExplainBuilder` records steps (start / add / subtract / divide) alongside each calculation, using the calculator's own variables, and a `replay()` proves the steps reproduce the displayed value to the cent. Three calculators attach explanations to their existing responses. The response change is additive only. One React `HowCalculated` dialog renders any explanation list.

**Tech Stack:** FastAPI + Pydantic + pytest; React + TypeScript + Radix Dialog (already installed) + lucide-react.

**Spec:** `docs/superpowers/specs/2026-09-30-how-is-this-calculated-design.md`

## Global Constraints

- **No number changes.** Every existing response field keeps its exact value. Explanations are additive fields.
- **Replay rule.** Start from the `start` row's amount and apply add/subtract/divide in order, quantizing to cents (ROUND_HALF_EVEN, Decimal default `quantize(Decimal("0.01"))`) after each divide. The result must equal `Explanation.result`, which equals the displayed value.
- **Divide rows store the EXACT divisor** (e.g. `Decimal(24) / Decimal(7)`). The UI rounds it for display only.
- **Children** of a row sum exactly to that row's amount. Children carry signed amounts (a deduction is negative).
- **No new npm/pip dependencies.** Use `@radix-ui/react-dialog`, which is already used by `ConfirmDialog.tsx`.
- **Hidden balances.** All amounts in the dialog go through `maskIfHidden(useBalancesHidden(), ...)` from `frontend/src/store/balanceVisibility`.
- **The live backend auto-reloads.** The controller backs up the DB before the first backend edit. Implementers never touch `data/` or `backend/*.db`.
- **Commits** go directly on `main`, with behavior-only messages (public repo: no real names, amounts or places). End each with a blank line then `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Backend suite** `cd backend && python3 -m pytest -q` must show 0 failures.
- **Frontend tsc gate** `cd frontend && bunx tsc -b --force 2>&1 | grep -oE "^src/[^(]+" | sort | uniq -c` must stay identical to base (39 errors / 11 files; Dashboard.tsx 2, Recurring.tsx 2, Budget.tsx 2). New files must have 0 errors. Use bun, never npm.

---

### Task 1: Explanation schema, builder and replay

**Files:**
- Modify: `backend/schemas.py`. Add the three models near the top, right after the imports, **before** any model that will reference them.
- Create: `backend/services/explain.py`
- Test: `backend/tests/test_explain.py`

**Interfaces:**
- Produces:
  - `schemas.ExplainChild(label: str, amount: Decimal, note: Optional[str] = None)`
  - `schemas.ExplainRow(op: Literal["start","add","subtract","divide","result"], label: str, amount: Decimal, note: Optional[str] = None, children: list[ExplainChild] = [])`
  - `schemas.Explanation(title: str, result: Decimal, rows: list[ExplainRow])`
  - `explain.ExplainBuilder(title: str)` with the chainable methods `.start(label, amount, note=None, children=None)`, `.add(...)`, `.subtract(...)` and `.divide(label, divisor, note=None)`, plus `.build(result: Decimal) -> schemas.Explanation`
  - `explain.replay(explanation: schemas.Explanation) -> Decimal`
  - `explain.children_consistent(explanation) -> bool`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_explain.py
from decimal import Decimal
from backend import schemas
from backend.services.explain import ExplainBuilder, replay, children_consistent


def test_replay_add_subtract():
    ex = (ExplainBuilder("Left")
          .start("Leftover", Decimal("100.00"))
          .subtract("Card spend", Decimal("30.50"))
          .add("Already charged", Decimal("5.25"))
          .build(Decimal("74.75")))
    assert replay(ex) == Decimal("74.75")
    assert ex.result == Decimal("74.75")
    assert [r.op for r in ex.rows] == ["start", "subtract", "add", "result"]
    assert ex.rows[-1].amount == Decimal("74.75")


def test_divide_uses_exact_divisor_and_quantizes():
    weeks = Decimal(24) / Decimal(7)
    expected = (Decimal("1000.00") / weeks).quantize(Decimal("0.01"))
    ex = ExplainBuilder("Week").start("Month", Decimal("1000.00")).divide("Weeks left", weeks).build(expected)
    assert replay(ex) == expected
    assert ex.rows[1].amount == weeks  # exact, not rounded


def test_replay_detects_a_wrong_explanation():
    ex = ExplainBuilder("X").start("A", Decimal("10")).subtract("B", Decimal("3")).build(Decimal("8"))
    assert replay(ex) != ex.result


def test_children_must_sum_to_their_row():
    good = ExplainBuilder("X").start("Leftover", Decimal("70"), children=[
        schemas.ExplainChild(label="Income", amount=Decimal("100")),
        schemas.ExplainChild(label="Bills", amount=Decimal("-30")),
    ]).build(Decimal("70"))
    bad = ExplainBuilder("X").start("Leftover", Decimal("70"), children=[
        schemas.ExplainChild(label="Income", amount=Decimal("100")),
    ]).build(Decimal("70"))
    assert children_consistent(good)
    assert not children_consistent(bad)


def test_start_only_explanation():
    ex = ExplainBuilder("Low").start("Lowest balance", Decimal("512.34"), note="on Oct 22").build(Decimal("512.34"))
    assert replay(ex) == Decimal("512.34")
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd backend && python3 -m pytest tests/test_explain.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'backend.services.explain'`.

- [ ] **Step 3: Add the schemas**

In `backend/schemas.py`, add `Literal` to the `typing` import (`from typing import Literal, Optional`). Directly after the import block, add:

```python
# ── Calculation explanations ("How is this calculated?") ─────────────────────
# Built by services/explain.py from the same variables a calculator used, so
# the receipt a user sees can be replayed to the exact displayed value.

class ExplainChild(BaseModel):
    label: str
    amount: Decimal          # signed: a deduction inside its parent is negative
    note: Optional[str] = None


class ExplainRow(BaseModel):
    op: Literal["start", "add", "subtract", "divide", "result"]
    label: str
    amount: Decimal          # for "divide": the exact divisor, never rounded
    note: Optional[str] = None
    children: list[ExplainChild] = []


class Explanation(BaseModel):
    title: str
    result: Decimal
    rows: list[ExplainRow]
```

- [ ] **Step 4: Create the builder**

```python
# backend/services/explain.py
"""Receipts for calculated numbers.

A calculator records its steps as it goes, using its own variables, so the
explanation can't drift from the math. replay() re-runs the steps and must
land on the displayed value to the cent (tests enforce this per metric).
"""
from __future__ import annotations
from decimal import Decimal
from backend import schemas

CENTS = Decimal("0.01")


class ExplainBuilder:
    def __init__(self, title: str):
        self.title = title
        self.rows: list[schemas.ExplainRow] = []

    def _row(self, op, label, amount, note=None, children=None):
        self.rows.append(schemas.ExplainRow(
            op=op, label=label, amount=amount, note=note, children=children or [],
        ))
        return self

    def start(self, label: str, amount: Decimal, note: str | None = None, children=None):
        return self._row("start", label, amount, note, children)

    def add(self, label: str, amount: Decimal, note: str | None = None, children=None):
        return self._row("add", label, amount, note, children)

    def subtract(self, label: str, amount: Decimal, note: str | None = None, children=None):
        return self._row("subtract", label, amount, note, children)

    def divide(self, label: str, divisor: Decimal, note: str | None = None):
        return self._row("divide", label, divisor, note)

    def build(self, result: Decimal) -> schemas.Explanation:
        rows = self.rows + [schemas.ExplainRow(op="result", label=self.title, amount=result)]
        return schemas.Explanation(title=self.title, result=result, rows=rows)


def replay(explanation: schemas.Explanation) -> Decimal:
    value = Decimal("0")
    for row in explanation.rows:
        if row.op == "start":
            value = row.amount
        elif row.op == "add":
            value += row.amount
        elif row.op == "subtract":
            value -= row.amount
        elif row.op == "divide":
            value = (value / row.amount).quantize(CENTS)
    return value


def children_consistent(explanation: schemas.Explanation) -> bool:
    return all(
        sum((c.amount for c in row.children), Decimal("0")) == row.amount
        for row in explanation.rows if row.children
    )
```

- [ ] **Step 5: Run the tests and confirm they pass, then the full suite**

Run: `cd backend && python3 -m pytest tests/test_explain.py -v`, which should pass all 5.
Run: `cd backend && python3 -m pytest -q`, which should show 0 failures.

- [ ] **Step 6: Commit**

```bash
git add backend/schemas.py backend/services/explain.py backend/tests/test_explain.py
git commit -m "feat: explanation builder whose steps replay to the displayed value"
```

---

### Task 2: Dashboard explanations (budget_snapshot)

**Files:**
- Modify: `backend/schemas.py` (`BudgetSnapshot`: add a field)
- Modify: `backend/services/budget_snapshot.py` (`compute_budget_snapshot`; add `leftover_children`)
- Test: `backend/tests/test_snapshot_explain.py` (create)

**Interfaces:**
- Consumes: `ExplainBuilder`, `replay`, `children_consistent` and `schemas.Explanation`/`ExplainChild` from Task 1. The existing `leftover_parts` / `LeftoverParts(income, expenses, savings_budget, committed_savings, groceries_budget, leftover)`.
- Produces:
  - `budget_snapshot.leftover_children(parts: LeftoverParts) -> list[schemas.ExplainChild]`, which Task 3 reuses.
  - `BudgetSnapshot.explain: dict[str, schemas.Explanation] = {}` with the keys `left_to_spend`, `spendable_week`, `spendable_today`, `safety_margin`, `safety_margin_week` and `lookahead_minimum`.

Field ↔ key mapping (what each explanation must equal):

| key | equals field |
|---|---|
| left_to_spend | left_to_spend |
| spendable_week | left_to_spend_weekly |
| spendable_today | spendable_today |
| safety_margin | safety_margin |
| safety_margin_week | safety_margin_weekly |
| lookahead_minimum | lookahead_minimum |

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_snapshot_explain.py
from datetime import date
from decimal import Decimal
from unittest.mock import patch
from backend.services.budget_snapshot import compute_budget_snapshot
from backend.services.explain import replay, children_consistent
from backend.tests.test_budget_snapshot import _seed_spreadsheet_scenario, _fake_quarter_min

FIELD = {
    "left_to_spend": "left_to_spend",
    "spendable_week": "left_to_spend_weekly",
    "spendable_today": "spendable_today",
    "safety_margin": "safety_margin",
    "safety_margin_week": "safety_margin_weekly",
    "lookahead_minimum": "lookahead_minimum",
}


def _snapshot(db, as_of):
    user, checking, _card = _seed_spreadsheet_scenario(db)
    with patch("backend.services.budget_snapshot.build_forecast", return_value=_fake_quarter_min("5120.66")):
        return compute_budget_snapshot(db, user, checking.id, as_of=as_of)


def test_every_explanation_replays_to_its_displayed_value(db_session):
    snap = _snapshot(db_session, date(2026, 8, 7))
    assert set(snap.explain) == set(FIELD)
    for key, field in FIELD.items():
        ex = snap.explain[key]
        shown = getattr(snap, field)
        assert ex.result == shown, key
        assert replay(ex) == shown, key
        assert children_consistent(ex), key


def test_left_to_spend_steps(db_session):
    snap = _snapshot(db_session, date(2026, 8, 7))
    ex = snap.explain["left_to_spend"]
    assert [r.op for r in ex.rows] == ["start", "subtract", "add", "result"]
    assert ex.rows[0].amount == snap.leftover
    assert len(ex.rows[0].children) == 4          # income, bills, savings, groceries
    assert len(ex.rows[1].children) >= 1          # one per active card


def test_last_week_of_month_is_a_single_step(db_session):
    snap = _snapshot(db_session, date(2026, 8, 27))   # 5 days remain
    ex = snap.explain["spendable_week"]
    assert [r.op for r in ex.rows] == ["start", "result"]
    assert replay(ex) == snap.left_to_spend_weekly == snap.left_to_spend


def test_safety_margin_starts_at_the_lowest_point(db_session):
    snap = _snapshot(db_session, date(2026, 8, 7))
    ex = snap.explain["safety_margin"]
    assert ex.rows[0].amount == snap.lookahead_minimum
    assert [r.op for r in ex.rows] == ["start", "subtract", "add", "result"]
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd backend && python3 -m pytest tests/test_snapshot_explain.py -v`
Expected: FAIL with `AttributeError` (`explain` doesn't exist).

- [ ] **Step 3: Add the schema field**

In `BudgetSnapshot` (`backend/schemas.py`), after `lookahead_minimum_date`:

```python
    # Receipts for the headline numbers, keyed as in services/budget_snapshot.py.
    explain: dict[str, Explanation] = {}
```

- [ ] **Step 4: Build the explanations in `compute_budget_snapshot`**

At the top of `backend/services/budget_snapshot.py`, add `from backend.schemas import ExplainChild` (extend the existing `backend.schemas` import) and `from backend.services.explain import ExplainBuilder`. Add this module-level helper next to `leftover_parts`:

```python
def leftover_children(parts: LeftoverParts) -> list[ExplainChild]:
    """The four pieces of `leftover`, signed so they sum to it exactly."""
    return [
        ExplainChild(label="Income this month", amount=parts.income),
        ExplainChild(label="Recurring bills this month", amount=-parts.expenses,
                     note="Monthly bills, quarterly bills spread over 3 months, yearly bills in their month"),
        ExplainChild(label="Savings set aside", amount=-parts.committed_savings),
        ExplainChild(label="Groceries budget", amount=-parts.groceries_budget),
    ]
```

In `compute_budget_snapshot`, right before `return BudgetSnapshot(`, add:

```python
    def weekly_explanation(title: str, source_label: str, source_amount, weekly_amount):
        # Mirrors _weekly_allowance exactly: whole amount in the last week,
        # otherwise divided by the exact number of weeks left.
        builder = ExplainBuilder(title)
        if days_remaining <= 7:
            builder.start(source_label, source_amount, note="Last week of the month: the whole amount")
        else:
            builder.start(source_label, source_amount).divide(
                "Weeks left in the month", Decimal(days_remaining) / Decimal(7),
                note=f"{days_remaining} days left ÷ 7",
            )
        return builder.build(weekly_amount)

    card_children = [
        ExplainChild(
            label=c.name,
            amount=c.current_balance - c.balance_due + c.pending_charges,
            note=f"current {c.current_balance} − last statement {c.balance_due} + pending {c.pending_charges}",
        )
        for c in active_cards
    ]
    low_note = (
        f"Lowest projected checking balance in the next 3 months"
        + (f", on {quarter_min_date:%b %-d}" if quarter_min_date else "")
        + ". Excludes the already-scheduled card payoff."
    )
    explain = {
        "left_to_spend": ExplainBuilder("Left to Spend")
            .start("Leftover", leftover, note="Income after bills, savings and groceries",
                   children=leftover_children(parts))
            .subtract("New card spending", new_spending_total,
                      note="Spent on cards since each card's last statement", children=card_children)
            .add("Card bills already charged", charged_so_far,
                 note="Recurring card subscriptions already posted this month (already inside card spending)")
            .build(left_to_spend),
        "spendable_week": weekly_explanation(
            "Spendable this week", "Left to Spend", left_to_spend, left_to_spend_weekly),
        "spendable_today": ExplainBuilder("Spendable today")
            .start("Spendable this week", left_to_spend_weekly)
            .divide("Days left this week", Decimal(days_left_in_week))
            .build(spendable_today),
        "safety_margin": ExplainBuilder("Safety Margin")
            .start("3-month lowest point", quarter_min, note=low_note)
            .subtract("This month's card bills", cc_budget_total,
                      note="Every recurring subscription charged to a card this month")
            .add("Card bills already charged", charged_so_far,
                 note="Already posted, so already inside the projected balance")
            .build(safety_margin),
        "safety_margin_week": weekly_explanation(
            "Safety Margin (this week)", "Safety Margin", safety_margin, safety_margin_weekly),
        "lookahead_minimum": ExplainBuilder("3-month lowest point")
            .start("Lowest projected checking balance", quarter_min, note=low_note)
            .build(quarter_min),
    }
```

Then add `explain=explain,` to the `BudgetSnapshot(...)` call. Make sure `days_remaining` is the variable returned by `_weekly_allowance(safety_margin, as_of)`. It's the same month-days value for both weekly figures (read the code to confirm). If `left_to_spend`'s weekly call uses a different variable, reuse whichever `_weekly_allowance` actually used for each figure.

- [ ] **Step 5: Run the tests and confirm they pass, then the full suite**

Run: `cd backend && python3 -m pytest tests/test_snapshot_explain.py tests/test_budget_snapshot.py -v`, which should all pass. The pre-existing snapshot tests prove no number moved.
Run: `cd backend && python3 -m pytest -q`, which should show 0 failures.

- [ ] **Step 6: Commit**

```bash
git add backend/schemas.py backend/services/budget_snapshot.py backend/tests/test_snapshot_explain.py
git commit -m "feat: Dashboard numbers carry a replayable explanation"
```

---

### Task 3: Budget and Recurring explanations

**Files:**
- Modify: `backend/schemas.py` (`LeftToBudgetOut`, `MonthSummaryOut`: add fields)
- Modify: `backend/services/left_to_budget.py`, `backend/services/month_summary.py`
- Test: `backend/tests/test_budget_recurring_explain.py` (create)

**Interfaces:**
- Consumes: `ExplainBuilder`, `replay`, `children_consistent` (Task 1); `budget_snapshot.leftover_children(parts)` (Task 2).
- Produces:
  - `LeftToBudgetOut.explain_unassigned: Explanation | None = None`
  - `MonthSummaryOut.explain: dict[str, Explanation] = {}`, with keys `expense_total` and `left_over`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_budget_recurring_explain.py
from datetime import date
from decimal import Decimal
from backend import models
from backend.services.left_to_budget import compute_left_to_budget
from backend.services.month_summary import build_month_summary
from backend.services.explain import replay, children_consistent
from backend.tests.test_left_to_budget import _seed as seed_ltb


def test_unassigned_explanation_replays(db_session):
    user, cats = seed_ltb(db_session)
    out = compute_left_to_budget(db_session, user, 2026, 10)
    ex = out.explain_unassigned
    assert ex.result == out.unassigned
    assert replay(ex) == out.unassigned
    assert children_consistent(ex)
    assert ex.rows[0].amount == out.leftover
    subtracted = [r for r in ex.rows if r.op == "subtract"]
    assert sum((r.amount for r in subtracted), Decimal("0")) == out.assigned_total


def _month_seed(db):
    user = models.User(username="mx", hashed_password="x", display_name="MX")
    db.add(user); db.flush()
    acct = models.Account(user_id=user.id, name="Chk", type=models.AccountType.checking)
    db.add(acct); db.flush()

    def item(name, amount, typ, freq, day, moy=None):
        db.add(models.RecurringItem(
            user_id=user.id, account_id=acct.id, name=name, amount=Decimal(amount),
            type=typ, frequency=freq, day_of_month=day, month_of_year=moy,
            start_date=date(2026, 1, 1),
        ))

    E, I = models.RecurringType.expense, models.RecurringType.income
    M, Y = models.RecurringFrequency.monthly, models.RecurringFrequency.yearly
    item("Pay", "3000.00", I, M, 15)
    item("Rent", "1200.00", E, M, 1)
    item("Power Co", "90.00", E, M, 8)
    item("Annual plan", "120.00", E, Y, 10, moy=10)
    db.add(models.PlannedExpense(
        user_id=user.id, account_id=acct.id, name="Couch", amount=Decimal("400.00"),
        expected_date=date(2026, 10, 20),
    ))
    db.commit()
    return user


def test_month_summary_explanations_replay(db_session):
    user = _month_seed(db_session)
    out = build_month_summary(db_session, user.id, 2026, 10)
    for key, field in {"expense_total": "expense_total", "left_over": "left_over"}.items():
        ex = out.explain[key]
        shown = getattr(out, field)
        assert ex.result == shown, key
        assert replay(ex) == shown, key
        assert children_consistent(ex), key
    assert any(r.label.startswith("Annual plan") for r in out.explain["expense_total"].rows)
    assert any(r.label.startswith("Couch") and r.op == "subtract" for r in out.explain["left_over"].rows)
```

If `PlannedExpense` requires more fields than given (check `models.PlannedExpense`, e.g. `direction`, whose default may already be outflow), add the minimum required with an outflow direction.

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd backend && python3 -m pytest tests/test_budget_recurring_explain.py -v`
Expected: FAIL (`explain_unassigned` / `explain` missing).

- [ ] **Step 3: Add the schema fields**

In `LeftToBudgetOut`, add `explain_unassigned: Optional[Explanation] = None`. In `MonthSummaryOut`, add `explain: dict[str, Explanation] = {}`.

- [ ] **Step 4: Build them**

`backend/services/left_to_budget.py`: import `from backend.services.explain import ExplainBuilder` and `leftover_children` from `budget_snapshot`, alongside the existing `leftover_parts` import. Before the `return`:

```python
    unassigned_builder = ExplainBuilder("Left to budget").start(
        "Leftover", parts.leftover,
        note="Income after bills, savings and groceries",
        children=leftover_children(parts),
    )
    for row in assignable:
        if row.assigned:
            unassigned_builder.subtract(row.category_name, row.assigned, note="Assigned this month")
    explain_unassigned = unassigned_builder.build(parts.leftover - assigned_total)
```

Pass `explain_unassigned=explain_unassigned` to `LeftToBudgetOut(...)`.

`backend/services/month_summary.py`: import `from backend.schemas import ExplainChild` and `from backend.services.explain import ExplainBuilder`. Before the `return`:

```python
    expense_builder = ExplainBuilder("Expenses this month").start(
        "Monthly bills", monthly_bills_total,
        note="Every weekly, biweekly and monthly bill charged this month",
        children=[ExplainChild(label=f"{b.name} ({b.date:%b %-d})", amount=b.amount,
                               note="actual statement amount" if b.overridden else None)
                  for b in monthly_bills],
    )
    for p in periodic_due:
        expense_builder.add(f"{p.name} ({p.date:%b %-d})", p.amount,
                            note=f"{p.frequency.value if hasattr(p.frequency, 'value') else p.frequency} bill due this month")
    left_builder = ExplainBuilder("Left over").start(
        "Income", income_total,
        children=[ExplainChild(label=f"{i.name} ({i.date:%b %-d})", amount=i.amount) for i in income_items],
    ).subtract("Expenses this month", expense_total)
    for o in one_offs:
        direction = o.direction.value if hasattr(o.direction, "value") else str(o.direction)
        label = f"{o.name} ({o.date:%b %-d})"
        note = "one-off, settled" if o.settled else "planned one-off"
        if direction == "inflow":
            left_builder.add(label, o.amount, note=note)
        else:
            left_builder.subtract(label, o.amount, note=note)
    explain = {
        "expense_total": expense_builder.build(expense_total),
        "left_over": left_builder.build(left_over),
    }
```

Pass `explain=explain` to `MonthSummaryOut(...)`. **Check** the actual `PlannedDirection` enum values in `models.py` and the names of the local lists and fields in `build_month_summary` (`monthly_bills`, `periodic_due`, `income_items`, `one_offs`, and their `.name/.date/.amount/.overridden/.settled/.direction` attributes) against the code, and use the real ones. The rule is: inflows add, everything else subtracts, exactly as `left_over` is computed.

- [ ] **Step 5: Run the tests and confirm they pass, then the full suite**

Run: `cd backend && python3 -m pytest tests/test_budget_recurring_explain.py tests/test_left_to_budget.py tests/test_month_summary.py -v`, which should all pass.
Run: `cd backend && python3 -m pytest -q`, which should show 0 failures.

- [ ] **Step 6: Commit**

```bash
git add backend/schemas.py backend/services/left_to_budget.py backend/services/month_summary.py backend/tests/test_budget_recurring_explain.py
git commit -m "feat: Left to budget and the Recurring month totals carry explanations"
```

---

### Task 4: `HowCalculated` component and mounting

**Files:**
- Create: `frontend/src/components/HowCalculated.tsx`
- Modify: `frontend/src/pages/Dashboard.tsx`, `frontend/src/components/LeftToBudgetPanel.tsx`, `frontend/src/components/RecurringSummaryStrip.tsx`

**Interfaces:**
- Consumes: `snapshot.explain[...]` (Task 2), `data.explain_unassigned` (Task 3), and the month summary's `explain.expense_total` / `explain.left_over` (Task 3). Decimals arrive as strings.
- Produces: `<HowCalculated title explanations={[...]} helpText? />`

- [ ] **Step 1: Create the component**

```tsx
// frontend/src/components/HowCalculated.tsx
import { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Info, X, ChevronRight, ChevronDown } from "lucide-react";
import { fmt } from "../lib/utils";
import { useBalancesHidden, maskIfHidden } from "../store/balanceVisibility";

export interface ExplainChild { label: string; amount: string; note?: string | null }
export interface ExplainRow {
  op: "start" | "add" | "subtract" | "divide" | "result";
  label: string; amount: string; note?: string | null; children?: ExplainChild[];
}
export interface Explanation { title: string; result: string; rows: ExplainRow[] }

const SYMBOL: Record<ExplainRow["op"], string> = { start: "", add: "+", subtract: "−", divide: "÷", result: "=" };

/**
 * The receipt behind a calculated number. Each explanation is built by the
 * backend from the same variables as the number and replays to it exactly,
 * so this never re-derives any math, it only displays the steps.
 */
export default function HowCalculated(
  { title, explanations, helpText }:
  { title: string; explanations: (Explanation | null | undefined)[]; helpText?: string },
) {
  const hidden = useBalancesHidden();
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [showHelp, setShowHelp] = useState(false);
  const list = explanations.filter((e): e is Explanation => !!e);
  if (list.length === 0) return null;

  const money = (v: string) => maskIfHidden(hidden, fmt(Math.abs(parseFloat(v))));
  const signed = (v: string) => `${parseFloat(v) < 0 ? "−" : ""}${money(v)}`;
  const toggle = (k: string) => setExpanded(s => { const n = new Set(s); n.has(k) ? n.delete(k) : n.add(k); return n; });

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <button type="button" aria-label={`How is ${title} calculated?`} title="How is this calculated?"
          className="text-gray-300 hover:text-indigo-500 dark:text-gray-400 dark:hover:text-indigo-400">
          <Info size={12} />
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/40 z-50" />
        <Dialog.Content className="fixed inset-0 z-50 flex items-center justify-center p-4 focus:outline-none"
          onOpenAutoFocus={(e) => e.preventDefault()}>
          <div className="card w-full max-w-md max-h-[85vh] overflow-y-auto text-left">
            <div className="flex items-start justify-between mb-3">
              <Dialog.Title className="font-bold text-gray-900 dark:text-gray-100">How {title} is calculated</Dialog.Title>
              <Dialog.Close asChild>
                <button aria-label="Close" className="btn-ghost p-1 text-gray-400"><X size={16} /></button>
              </Dialog.Close>
            </div>
            <Dialog.Description className="sr-only">Step-by-step calculation with your current numbers</Dialog.Description>
            {list.map((ex, ei) => (
              <div key={ei} className={ei > 0 ? "mt-4 pt-4 border-t border-gray-100 dark:border-gray-700" : ""}>
                {list.length > 1 && <p className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">{ex.title}</p>}
                {ex.rows.map((r, ri) => {
                  const key = `${ei}-${ri}`;
                  const hasKids = (r.children?.length ?? 0) > 0;
                  const isResult = r.op === "result";
                  return (
                    <div key={key} className={`py-1 ${isResult ? "border-t border-gray-200 dark:border-gray-600 mt-1 pt-2" : ""}`}>
                      <button type="button" disabled={!hasKids} onClick={() => hasKids && toggle(key)}
                        aria-expanded={hasKids ? expanded.has(key) : undefined}
                        className="w-full flex items-center gap-2 text-sm text-left disabled:cursor-default">
                        <span className="w-4 text-gray-400 tabular-nums">{SYMBOL[r.op]}</span>
                        <span className={`flex-1 flex items-center gap-1 ${isResult ? "font-bold" : ""}`}>
                          {r.label}
                          {hasKids && (expanded.has(key) ? <ChevronDown size={12} /> : <ChevronRight size={12} />)}
                        </span>
                        <span className={`tabular-nums ${isResult ? "font-bold" : ""}`}>
                          {r.op === "divide" ? parseFloat(r.amount).toFixed(2) : isResult || r.op === "start" ? signed(r.amount) : money(r.amount)}
                        </span>
                      </button>
                      {r.note && <p className="ml-6 text-xs text-gray-400">{r.note}</p>}
                      {hasKids && expanded.has(key) && (
                        <div className="ml-6 mt-1 space-y-0.5">
                          {r.children!.map((c, ci) => (
                            <div key={ci} className="flex justify-between text-xs text-gray-500">
                              <span>{c.label}{c.note ? <span className="text-gray-400"> · {c.note}</span> : null}</span>
                              <span className="tabular-nums">{signed(c.amount)}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            ))}
            {helpText && (
              <div className="mt-4 pt-3 border-t border-gray-100 dark:border-gray-700">
                <button type="button" className="text-xs text-indigo-500 hover:underline" aria-expanded={showHelp}
                  onClick={() => setShowHelp(v => !v)}>What does this mean?</button>
                {showHelp && <p className="mt-2 text-xs text-gray-500 whitespace-pre-line">{helpText}</p>}
              </div>
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
```

- [ ] **Step 2: Mount it on the Dashboard** (`frontend/src/pages/Dashboard.tsx`)

- Import `HowCalculated from "../components/HowCalculated"`.
- **"Spendable this week" box:** replace the `<button onClick={() => setSnapshotHelp("spendable")} …><HelpCircle …/></button>` with:
  ```tsx
  <HowCalculated title="Spendable this week"
    explanations={[snapshot.explain?.left_to_spend, snapshot.explain?.spendable_week, snapshot.explain?.spendable_today]}
    helpText={SPENDABLE_HELP} />
  ```
- **"Safety Margin (this week)" box:** replace its `setSnapshotHelp("margin")` button with:
  ```tsx
  <HowCalculated title="Safety Margin"
    explanations={[snapshot.explain?.safety_margin, snapshot.explain?.safety_margin_week]}
    helpText={MARGIN_HELP} />
  ```
- Move the two existing `HelpPanel` body strings (the `snapshotHelp === "spendable"` and `"margin"` blocks near the end of the file) into module-level constants `SPENDABLE_HELP` and `MARGIN_HELP`. Then delete those two `HelpPanel` blocks and the now-unused `snapshotHelp` state. Remove `HelpCircle` from the import **only** if nothing else in the file uses it.
- **3-month lowest point:** find where `snapshot.lookahead_minimum` is rendered, and add `<HowCalculated title="3-month lowest point" explanations={[snapshot.explain?.lookahead_minimum]} />` next to its label.

- [ ] **Step 3: Mount it on Budget and Recurring**

- **`LeftToBudgetPanel.tsx`:** next to the "Left to budget" heading, `<HowCalculated title="Left to budget" explanations={[data.explain_unassigned]} />`.
- **`RecurringSummaryStrip.tsx`:** next to the Expenses tile label, `<HowCalculated title="Expenses this month" explanations={[summary.explain?.expense_total]} />`. Next to the Left over tile label, `<HowCalculated title="Left over" explanations={[summary.explain?.left_over]} />`. Use the component's actual variable name for the month-summary data.

- [ ] **Step 4: Type-check**

Run: `cd frontend && bunx tsc -b --force 2>&1 | grep -oE "^src/[^(]+" | sort | uniq -c`
Expected: identical to base, with `HowCalculated.tsx` absent (0 errors).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/HowCalculated.tsx frontend/src/pages/Dashboard.tsx frontend/src/components/LeftToBudgetPanel.tsx frontend/src/components/RecurringSummaryStrip.tsx
git commit -m "feat: info icon shows how Dashboard, Budget and Recurring numbers are calculated"
```

---

### Task 5: Verification (controller)

- [ ] Full backend suite shows 0 failures, and the tsc gate is unchanged.
- [ ] `graphify update .`
- [ ] Interceptor (test profile), using `eval --main` against the live API and the DOM: every ⓘ (Dashboard ×3, Budget ×1, Recurring ×2) opens a dialog, and its final "=" amount equals the box's number. Also confirm there are no console errors.
- [ ] Final whole-branch review on the most capable model, then push only after Dan approves.
