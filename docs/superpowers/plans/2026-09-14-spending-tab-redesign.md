# Spending Tab Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Spending tab worth using: bake an always-visible checking-vs-card split into the Overview, consolidate Trends' two redundant charts into one, fix Flow's visual noise, and move Tax Export to its own nav spot.

**Architecture:** Almost entirely frontend. Two small backend additions (rolling-monthly gets a checking/cards split mirroring `/spending/monthly`'s existing pattern exactly; the Sankey endpoint gets the same small-category "Other" grouping the stacked monthly-by-category chart already uses). Everything else reads fields (`breakdown_by_source`, `MonthlySpendingEntry.checking`/`.cards`) that already exist and are already returned by the API today.

**Tech Stack:** FastAPI + SQLAlchemy + Pydantic (backend), React + TypeScript + TanStack Query + Recharts + Tailwind (frontend), pytest (backend tests only — this repo has no frontend test suite; frontend tasks verify with Interceptor instead).

**Spec:** `docs/superpowers/specs/2026-09-13-spending-tab-redesign-design.md`

## Global Constraints

- No schema/migration changes anywhere in this plan (per spec's Testing section).
- Any field added to `/spending/rolling-monthly`'s response must be additive only — `Dashboard.tsx` calls `analyticsApi.rollingMonthly(6)` and reads only `month`/`total`; do not change or remove those.
- `bun`/`bunx` and TypeScript are this repo's frontend conventions where applicable, but this is a Python/FastAPI backend + Vite/React frontend project — use the existing `.venv` Python environment for backend work (`source .venv/bin/activate`) and the existing `frontend/` npm/vite toolchain for frontend work (follow whatever `frontend/package.json` already uses — do not introduce a different package manager mid-project).
- Every frontend task ends with an Interceptor pass in both light and dark mode (`OPERATIONAL_RULES.md`'s verification rule) — this repo has no frontend automated tests to substitute.
- Commit after every task, directly to `main` (this repo's established convention — no feature branches).
- Full backend suite (`pytest backend/tests/ -q`) must stay green before any backend-touching commit.

---

## Task 1: Backend — checking/cards split on `/spending/rolling-monthly`

**Files:**
- Modify: `backend/schemas.py` (`RollingMonthEntry`, ~line 934)
- Modify: `backend/routers/spending.py` (`spending_rolling_monthly`, ~line 638-685)
- Test: `backend/tests/test_spending_rolling_monthly.py` (new)

**Interfaces:**
- Produces: `RollingMonthEntry` gains `checking: Decimal` and `cards: Decimal` fields (both required, always populated — mirrors `MonthlySpendingEntry` exactly). `GET /spending/rolling-monthly` response shape becomes `{month, total, checking, cards}` per entry.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_spending_rolling_monthly.py`:

```python
from datetime import date
from decimal import Decimal
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.routers import spending as spending_router_module
from backend.dependencies import get_db, get_current_user


def _make_user(db):
    user = models.User(username="roller", hashed_password="x", display_name="Roller")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _client(db, user):
    app = FastAPI()
    app.include_router(spending_router_module.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_rolling_monthly_splits_checking_and_cards(db_session):
    user = _make_user(db_session)
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("1000.00"),
    )
    db_session.add(account)
    db_session.flush()
    card = models.CreditCard(
        user_id=user.id, name="Visa", credit_limit=Decimal("5000.00"),
        statement_day=1, due_day=15, current_balance=Decimal("0.00"),
    )
    db_session.add(card)
    db_session.flush()
    db_session.add(models.Transaction(
        user_id=user.id, account_id=account.id, date=date(2026, 8, 5),
        amount=Decimal("-100.00"), description="Mortgage", is_actual=True,
    ))
    db_session.add(models.CreditCardTransaction(
        card_id=card.id, user_id=user.id, date=date(2026, 8, 6),
        amount=Decimal("40.00"), merchant="Coffee Shop",
    ))
    db_session.commit()

    c = _client(db_session, user)
    resp = c.get("/spending/rolling-monthly", params={"months": 2})

    assert resp.status_code == 200
    rows = {r["month"]: r for r in resp.json()}
    row = rows["2026-08"]
    assert Decimal(row["checking"]) == Decimal("100.00")
    assert Decimal(row["cards"]) == Decimal("40.00")
    assert Decimal(row["total"]) == Decimal("140.00")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/danford/Programming/Dev/OfflineBudget && source .venv/bin/activate && python -m pytest backend/tests/test_spending_rolling_monthly.py -q`
Expected: FAIL — `KeyError: 'checking'` (the field doesn't exist on the response yet).

- [ ] **Step 3: Add the fields to the schema**

In `backend/schemas.py`, find `class RollingMonthEntry(BaseModel):` (~line 934) and change it from:

```python
class RollingMonthEntry(BaseModel):
    month: str  # "YYYY-MM"
    total: Decimal
```

to:

```python
class RollingMonthEntry(BaseModel):
    month: str  # "YYYY-MM"
    total: Decimal
    checking: Decimal
    cards: Decimal
```

- [ ] **Step 4: Track checking/cards separately in the endpoint**

In `backend/routers/spending.py`, replace the body of `spending_rolling_monthly` (~line 638-685) from:

```python
    results: dict[str, Decimal] = {}
    txns = (
        db.query(models.Transaction)
        .outerjoin(models.Category, models.Transaction.category_id == models.Category.id)
        .filter(
            models.Transaction.user_id == user.id,
            models.Transaction.is_actual == True,
            models.Transaction.date >= start,
            models.Transaction.date <= today,
            models.Transaction.amount < 0,
            NOT_SAVINGS,
        )
    ).all()
    txns = filter_real_spend(db, user.id, txns)
    for t in txns:
        key = t.date.strftime("%Y-%m")
        results[key] = results.get(key, Decimal("0")) + abs(t.amount)
    card_txns = db.query(models.CreditCardTransaction).filter(
        models.CreditCardTransaction.user_id == user.id,
        models.CreditCardTransaction.date >= start,
        models.CreditCardTransaction.date <= today,
        models.CreditCardTransaction.amount > 0,
    ).all()
    for t in card_txns:
        if is_card_payment(t.merchant):
            continue
        key = t.date.strftime("%Y-%m")
        results[key] = results.get(key, Decimal("0")) + t.amount

    return [
        schemas.RollingMonthEntry(month=m, total=results.get(m, Decimal("0")))
        for m in sorted(results.keys())
    ]
```

to:

```python
    results: dict[str, dict[str, Decimal]] = {}
    txns = (
        db.query(models.Transaction)
        .outerjoin(models.Category, models.Transaction.category_id == models.Category.id)
        .filter(
            models.Transaction.user_id == user.id,
            models.Transaction.is_actual == True,
            models.Transaction.date >= start,
            models.Transaction.date <= today,
            models.Transaction.amount < 0,
            NOT_SAVINGS,
        )
    ).all()
    txns = filter_real_spend(db, user.id, txns)
    for t in txns:
        key = t.date.strftime("%Y-%m")
        results.setdefault(key, {"checking": Decimal("0"), "cards": Decimal("0")})
        results[key]["checking"] += abs(t.amount)
    card_txns = db.query(models.CreditCardTransaction).filter(
        models.CreditCardTransaction.user_id == user.id,
        models.CreditCardTransaction.date >= start,
        models.CreditCardTransaction.date <= today,
        models.CreditCardTransaction.amount > 0,
    ).all()
    for t in card_txns:
        if is_card_payment(t.merchant):
            continue
        key = t.date.strftime("%Y-%m")
        results.setdefault(key, {"checking": Decimal("0"), "cards": Decimal("0")})
        results[key]["cards"] += t.amount

    return [
        schemas.RollingMonthEntry(
            month=m,
            total=results[m]["checking"] + results[m]["cards"],
            checking=results[m]["checking"],
            cards=results[m]["cards"],
        )
        for m in sorted(results.keys())
    ]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_spending_rolling_monthly.py -q`
Expected: PASS

- [ ] **Step 6: Run the full backend suite**

Run: `python -m pytest backend/tests/ -q`
Expected: all pass, including the pre-existing `Dashboard`-adjacent tests untouched (this change is additive-only).

- [ ] **Step 7: Commit**

```bash
git add backend/schemas.py backend/routers/spending.py backend/tests/test_spending_rolling_monthly.py
git commit -m "Add checking/cards split to /spending/rolling-monthly

Mirrors the split /spending/monthly already returns. Additive only --
Dashboard.tsx's existing rollingMonthly(6) call reads month/total and
is unaffected.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 2: Backend — collapse small Sankey categories into "Other"

**Files:**
- Modify: `backend/routers/spending.py` (`spending_sankey`, ~line 740-807)
- Test: `backend/tests/test_spending_sankey_other_grouping.py` (new)

**Interfaces:**
- Consumes: `_MAX_STACK_CATEGORIES` (existing module constant, `backend/routers/spending.py:16`) — reused, not redefined.
- Produces: no change to `SankeyResponse`/`SankeyNode`/`SankeyLink` shape — same schema, fewer/larger expense nodes when there are more than `_MAX_STACK_CATEGORIES` distinct expense categories in the month. "Uncategorized" is never folded into "Other".

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_spending_sankey_other_grouping.py`:

```python
from datetime import date
from decimal import Decimal
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.routers import spending as spending_router_module
from backend.routers.spending import _MAX_STACK_CATEGORIES
from backend.dependencies import get_db, get_current_user


def _make_user(db):
    user = models.User(username="flow", hashed_password="x", display_name="Flow")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _client(db, user):
    app = FastAPI()
    app.include_router(spending_router_module.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_small_categories_collapse_into_other_uncategorized_stays_separate(db_session):
    user = _make_user(db_session)
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("1000.00"),
    )
    db_session.add(account)
    db_session.flush()

    # More distinct expense categories than _MAX_STACK_CATEGORIES, each a
    # small, uniquely-named amount so ranking is deterministic.
    num_categories = _MAX_STACK_CATEGORIES + 3
    for i in range(num_categories):
        cat = models.Category(
            user_id=user.id, name=f"Small Cat {i}", type=models.CategoryType.expense,
            color="#888888", sort_order=i,
        )
        db_session.add(cat)
        db_session.flush()
        # Later categories get a larger amount so ranking is unambiguous:
        # the first `_MAX_STACK_CATEGORIES` by descending amount survive named.
        amount = Decimal("10.00") * (num_categories - i)
        db_session.add(models.Transaction(
            user_id=user.id, account_id=account.id, date=date(2026, 8, 10),
            amount=-amount, description=f"Purchase {i}", is_actual=True,
            category_id=cat.id,
        ))

    # One uncategorized transaction, smaller than everything above -- must
    # still get its own node, never merged into "Other".
    db_session.add(models.Transaction(
        user_id=user.id, account_id=account.id, date=date(2026, 8, 11),
        amount=Decimal("-1.00"), description="Mystery charge", is_actual=True,
    ))
    db_session.commit()

    c = _client(db_session, user)
    resp = c.get("/spending/sankey", params={"year": 2026, "month": 8})

    assert resp.status_code == 200
    body = resp.json()
    expense_names = {n["name"] for n in body["nodes"] if n["type"] == "expense"}

    assert "Uncategorized" in expense_names, "Uncategorized must never collapse into Other"
    assert "Other" in expense_names, "categories beyond the cap must collapse into Other"
    # named categories + Other + Uncategorized, not one node per category
    assert len(expense_names) == _MAX_STACK_CATEGORIES + 2

    other_link = next(l for l in body["links"] if l["target"] == "expense:Other")
    expected_other_total = sum(
        Decimal("10.00") * (num_categories - i)
        for i in range(_MAX_STACK_CATEGORIES, num_categories)
    )
    assert Decimal(other_link["value"]) == expected_other_total
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_spending_sankey_other_grouping.py -q`
Expected: FAIL — `assert "Other" in expense_names` fails (every category currently gets its own node).

- [ ] **Step 3: Add the grouping**

In `backend/routers/spending.py`, inside `spending_sankey` (~line 740-807), find:

```python
    nodes: list[schemas.SankeyNode] = []
    links: list[schemas.SankeyLink] = []

    for name in income_totals:
        nodes.append(schemas.SankeyNode(id=f"income:{name}", name=name, type="income"))
    for name in expense_totals:
        nodes.append(schemas.SankeyNode(id=f"expense:{name}", name=name, type="expense"))
```

Replace with:

```python
    # More than _MAX_STACK_CATEGORIES distinct expense categories makes the
    # diagram unreadable -- collapse the tail into "Other", same pattern the
    # stacked monthly-by-category chart already uses. "Uncategorized" is
    # diagnostic (it's the signal Dan needs to notice he should categorize
    # more), so it's exempt from collapsing regardless of its size.
    ranked_expenses = sorted(
        (kv for kv in expense_totals.items() if kv[0] != "Uncategorized"),
        key=lambda kv: kv[1], reverse=True,
    )
    named_expense_names = {name for name, _ in ranked_expenses[:_MAX_STACK_CATEGORIES]}
    other_total = sum(
        (amt for name, amt in ranked_expenses[_MAX_STACK_CATEGORIES:]),
        Decimal("0"),
    )
    grouped_expense_totals: dict[str, Decimal] = {
        name: amt for name, amt in expense_totals.items()
        if name == "Uncategorized" or name in named_expense_names
    }
    if other_total > 0:
        grouped_expense_totals["Other"] = other_total
    expense_totals = grouped_expense_totals

    nodes: list[schemas.SankeyNode] = []
    links: list[schemas.SankeyLink] = []

    for name in income_totals:
        nodes.append(schemas.SankeyNode(id=f"income:{name}", name=name, type="income"))
    for name in expense_totals:
        nodes.append(schemas.SankeyNode(id=f"expense:{name}", name=name, type="expense"))
```

(The rest of the function already loops over `expense_totals` to build the `income:__total__` links — no further change needed there since it now iterates the grouped dict.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_spending_sankey_other_grouping.py -q`
Expected: PASS

- [ ] **Step 5: Run the full backend suite**

Run: `python -m pytest backend/tests/ -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/routers/spending.py backend/tests/test_spending_sankey_other_grouping.py
git commit -m "Collapse small Sankey categories into Other, keep Uncategorized separate

Same grouping technique the stacked monthly-by-category chart already
uses (_MAX_STACK_CATEGORIES). Fixes Flow looking noisy/incomplete with
many thin category nodes -- confirmed not a logic bug, Uncategorized
was always its own node already.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 3: Frontend — stacked Checking/Cards monthly bar chart

**Files:**
- Modify: `frontend/src/pages/Spending.tsx` (`barData`, ~line 131-134; the Monthly Spending `BarChart`, ~line 496-517)

**Interfaces:**
- Consumes: `spendingApi.monthly(...)` response rows already carry `checking`/`cards` (existing, `MonthlySpendingEntry` schema) — no API client change needed, `frontend/src/api/index.ts:161` already returns the raw response.
- Consumes: `StackedTooltip` component (existing, `Spending.tsx` ~line 265-271) — reused as-is, not modified.

- [ ] **Step 1: Change `barData` to carry both series**

Find (~line 130-135):

```tsx
  // Recharts data for total monthly bars
  const barData = monthly.map((m: any) => ({
    month: m.month,
    total: parseFloat(m.total),
  }));
  const avg = barData.length > 1 ? barData.reduce((s: number, d: any) => s + d.total, 0) / barData.length : 0;
```

Replace with:

```tsx
  // Recharts data for total monthly bars, split checking/cards for the
  // stacked chart -- both fields already come back from /spending/monthly.
  const barData = monthly.map((m: any) => ({
    month: m.month,
    total: parseFloat(m.total),
    checking: parseFloat(m.checking),
    cards: parseFloat(m.cards),
  }));
  const avg = barData.length > 1 ? barData.reduce((s: number, d: any) => s + d.total, 0) / barData.length : 0;
```

- [ ] **Step 2: Stack the bars and reuse `StackedTooltip`**

Find (~line 496-517):

```tsx
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={barData} margin={{ top: 16, right: 12, left: 0, bottom: 0 }}
                  onClick={(state: any) => {
                    const month = state?.activeLabel;
                    if (month) setDrillMonth(m => (m === month ? null : month));
                  }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={ct.grid} />
                  <XAxis dataKey="month" tick={{ fontSize: 11, fill: ct.tick }} axisLine={{ stroke: ct.grid }} tickLine={false} />
                  <YAxis tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 11, fill: ct.tick }} axisLine={false} tickLine={false} />
                  <Tooltip content={<TotalBarTooltip />} cursor={{ fill: isDarkMode() ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.04)" }} />
                  <Bar dataKey="total" fill={ct.barFill} radius={[4, 4, 0, 0]} name="Total" className="cursor-pointer" />
                  {avg > 0 && (
                    <ReferenceLine
                      y={avg}
                      stroke={ct.refLine}
                      strokeDasharray="6 3"
                      label={{ value: `avg ${fmt(avg)}`, fill: ct.tick, fontSize: 10, position: "insideTopRight" }}
                    />
                  )}
                </BarChart>
              </ResponsiveContainer>
```

Replace with:

```tsx
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={barData} margin={{ top: 16, right: 12, left: 0, bottom: 0 }}
                  onClick={(state: any) => {
                    const month = state?.activeLabel;
                    if (month) setDrillMonth(m => (m === month ? null : month));
                  }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={ct.grid} />
                  <XAxis dataKey="month" tick={{ fontSize: 11, fill: ct.tick }} axisLine={{ stroke: ct.grid }} tickLine={false} />
                  <YAxis tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 11, fill: ct.tick }} axisLine={false} tickLine={false} />
                  <Tooltip content={<StackedTooltip />} cursor={{ fill: isDarkMode() ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.04)" }} />
                  <Bar dataKey="checking" stackId="spend" fill={ct.barFill} name="Checking" className="cursor-pointer" />
                  <Bar dataKey="cards" stackId="spend" fill="#f59e0b" radius={[4, 4, 0, 0]} name="Cards" className="cursor-pointer" />
                  {avg > 0 && (
                    <ReferenceLine
                      y={avg}
                      stroke={ct.refLine}
                      strokeDasharray="6 3"
                      label={{ value: `avg ${fmt(avg)}`, fill: ct.tick, fontSize: 10, position: "insideTopRight" }}
                    />
                  )}
                </BarChart>
              </ResponsiveContainer>
```

(`StackedTooltip` already renders one row per `payload` entry with its `fill` color and `dataKey`-derived name — `Bar`'s `name` prop is what shows as the row label, matching the existing pattern used by the category stacked chart below it on the same page.)

- [ ] **Step 3: `TotalBarTooltip` is now unused — remove it**

Find (~line 260-263):

```tsx
  const TotalBarTooltip = ({ active, payload, label }: any) =>
    active && payload?.length ? (
      <TooltipBox label={label} rows={[{ name: "Spending", value: payload[0].value }]} />
    ) : null;
```

Delete this block entirely (grep the file afterward to confirm `TotalBarTooltip` has no remaining references before deleting, in case another chart still uses it).

- [ ] **Step 4: Verify with Interceptor**

Start the app (`bun`/npm dev server per whatever `frontend/package.json` already defines — confirm the existing dev-run command via the repo's own `run` skill/README rather than guessing one). Open the Spending page, Overview tab, both light and dark mode. Confirm: the Monthly Spending chart shows two stacked colors (indigo Checking, amber Cards) per bar, the tooltip on hover shows both rows plus is legible in both themes, clicking a bar still opens the month drill-down (unchanged behavior).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Spending.tsx
git commit -m "Stack the Monthly Spending chart by Checking/Cards

Uses MonthlySpendingEntry.checking/.cards, already returned by
/spending/monthly and previously unread by the frontend.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 4: Frontend — hero card and category list inline source splits

**Files:**
- Modify: `frontend/src/pages/Spending.tsx` (discretionary/fixed hero cards, ~line 435-480; category list rows, ~line 672-704)

**Interfaces:**
- Consumes: `overview.categories[].is_discretionary` and `overview.categories[].children[].breakdown_by_source` (existing `SpendingTopLevel`/`SpendingSubCategory` fields, already present in every `/spending/by-category` response).
- Produces: a `sourceLabel(breakdown: Record<string, number>)` helper function, used by both the hero cards and the category list — defined once, in this task, reused by both sites in this same task (not shared across files; both usages live in `Spending.tsx`).

- [ ] **Step 1: Add a shared formatting helper**

Find the `ProgressBar` component (~line 292-303) and add this function directly above it:

```tsx
  // "$1,240 checking · $310 card" -- omits a source entirely if it's $0, so
  // a category/bucket that's 100% one source doesn't show a pointless
  // "$0 card". Returns null when there's nothing worth showing (zero or
  // one non-zero source), so callers can skip rendering the line at all.
  function sourceSplitLabel(breakdown: Record<string, number>): string | null {
    const nonZero = Object.entries(breakdown).filter(([, v]) => v > 0.005);
    if (nonZero.length < 2) return null;
    return nonZero
      .sort((a, b) => b[1] - a[1])
      .map(([label, v]) => `${fmt(v)} ${label}`)
      .join(" · ");
  }
```

- [ ] **Step 2: Compute discretionary/fixed/total source buckets**

Find the discretionary hero card's IIFE (~line 435-441):

```tsx
          {(() => {
            const disc = parseFloat(overview.discretionary_actual ?? "0");
            const discBudget = parseFloat(overview.discretionary_budgeted ?? "0");
            const fixed = parseFloat(overview.fixed_actual ?? "0");
            const left = discBudget - disc;
            const pct = discBudget > 0 ? (disc / discBudget) * 100 : 0;
            const over = left < 0;
            return (
```

Replace with:

```tsx
          {(() => {
            const disc = parseFloat(overview.discretionary_actual ?? "0");
            const discBudget = parseFloat(overview.discretionary_budgeted ?? "0");
            const fixed = parseFloat(overview.fixed_actual ?? "0");
            const left = discBudget - disc;
            const pct = discBudget > 0 ? (disc / discBudget) * 100 : 0;
            const over = left < 0;

            // breakdown_by_source lives on each child category; bucket by
            // the PARENT's is_discretionary flag to get discretionary vs.
            // fixed vs. total split by source, with no new backend call.
            const discBySource: Record<string, number> = {};
            const fixedBySource: Record<string, number> = {};
            (overview.categories ?? []).forEach((top: any) => {
              const bucket = top.is_discretionary ? discBySource : fixedBySource;
              (top.children ?? []).forEach((ch: any) => {
                Object.entries(ch.breakdown_by_source ?? {}).forEach(([label, amt]) => {
                  bucket[label] = (bucket[label] ?? 0) + parseFloat(amt as string);
                });
              });
            });
            const totalBySource: Record<string, number> = {};
            [discBySource, fixedBySource].forEach(bucket => {
              Object.entries(bucket).forEach(([label, amt]) => {
                totalBySource[label] = (totalBySource[label] ?? 0) + amt;
              });
            });

            return (
```

- [ ] **Step 3: Render the split under each stat card**

Find the three `stat-card` blocks (~line 461-477):

```tsx
                <div className="grid grid-cols-3 gap-4">
                  <div className="stat-card">
                    <span className="stat-label">Discretionary</span>
                    <span className="stat-value text-gray-900 dark:text-[#c4ccd8]">{fmt(disc)}</span>
                    <span className="text-xs text-gray-400">what you chose</span>
                  </div>
                  <div className="stat-card">
                    <span className="stat-label">Fixed Commitments</span>
                    <span className="stat-value text-gray-500 dark:text-gray-400">{fmt(fixed)}</span>
                    <span className="text-xs text-gray-400">mortgage, tithe, insurance</span>
                  </div>
                  <div className="stat-card">
                    <span className="stat-label">Total Spent</span>
                    <span className="stat-value text-gray-900 dark:text-[#c4ccd8]">{fmt(overview.total_actual)}</span>
                    <span className="text-xs text-gray-400">of {fmt(overview.total_budgeted)} budgeted</span>
                  </div>
                </div>
```

Replace with:

```tsx
                <div className="grid grid-cols-3 gap-4">
                  <div className="stat-card">
                    <span className="stat-label">Discretionary</span>
                    <span className="stat-value text-gray-900 dark:text-[#c4ccd8]">{fmt(disc)}</span>
                    <span className="text-xs text-gray-400">what you chose</span>
                    {sourceSplitLabel(discBySource) && (
                      <span className="text-xs text-gray-400 dark:text-[#8f99a8] mt-0.5">{sourceSplitLabel(discBySource)}</span>
                    )}
                  </div>
                  <div className="stat-card">
                    <span className="stat-label">Fixed Commitments</span>
                    <span className="stat-value text-gray-500 dark:text-gray-400">{fmt(fixed)}</span>
                    <span className="text-xs text-gray-400">mortgage, tithe, insurance</span>
                    {sourceSplitLabel(fixedBySource) && (
                      <span className="text-xs text-gray-400 dark:text-[#8f99a8] mt-0.5">{sourceSplitLabel(fixedBySource)}</span>
                    )}
                  </div>
                  <div className="stat-card">
                    <span className="stat-label">Total Spent</span>
                    <span className="stat-value text-gray-900 dark:text-[#c4ccd8]">{fmt(overview.total_actual)}</span>
                    <span className="text-xs text-gray-400">of {fmt(overview.total_budgeted)} budgeted</span>
                    {sourceSplitLabel(totalBySource) && (
                      <span className="text-xs text-gray-400 dark:text-[#8f99a8] mt-0.5">{sourceSplitLabel(totalBySource)}</span>
                    )}
                  </div>
                </div>
```

(Verified: `.stat-card` is `flex flex-col gap-1` in `frontend/src/index.css:49` — the new fourth `<span>` per card stacks correctly with no wrapper changes needed.)

- [ ] **Step 4: Add the inline split to each category list row**

Find the category list row (~line 678-701):

```tsx
                return (
                  <div key={cat.category_id}>
                    <div className="flex items-baseline justify-between gap-3 mb-1">
                      <div className="flex items-center gap-2 min-w-0">
                        <div className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: cat.color }} />
                        <span className="text-sm font-medium text-gray-900 dark:text-[#c4ccd8] truncate">
                          {cat.category_name}
                        </span>
                        {cat.group && (
                          <span className="text-[10px] uppercase tracking-wide text-gray-400 dark:text-[#949daf] shrink-0">
                            {cat.group}
                          </span>
                        )}
                      </div>
                      <div className="flex items-baseline gap-2 shrink-0 text-sm">
                        <span className={`font-semibold tabular-nums ${over ? "text-red-600 dark:text-[#eda2a2]" : "text-gray-900 dark:text-[#c4ccd8]"}`}>
                          {fmt(actual)}
                        </span>
                        <span className="text-xs text-gray-400 dark:text-[#8f99a8] tabular-nums">
                          {budgeted > 0 ? `of ${fmt(budgeted)}` : "unbudgeted"}
                        </span>
                      </div>
                    </div>
                    {budgeted > 0 && <ProgressBar actual={actual} budgeted={budgeted} />}
                  </div>
                );
```

Replace with:

```tsx
                const split = sourceSplitLabel(
                  Object.fromEntries(
                    Object.entries(cat.breakdown_by_source ?? {}).map(([k, v]) => [k, parseFloat(v as string)])
                  )
                );
                return (
                  <div key={cat.category_id}>
                    <div className="flex items-baseline justify-between gap-3 mb-1">
                      <div className="flex items-center gap-2 min-w-0">
                        <div className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: cat.color }} />
                        <span className="text-sm font-medium text-gray-900 dark:text-[#c4ccd8] truncate">
                          {cat.category_name}
                        </span>
                        {cat.group && (
                          <span className="text-[10px] uppercase tracking-wide text-gray-400 dark:text-[#949daf] shrink-0">
                            {cat.group}
                          </span>
                        )}
                      </div>
                      <div className="flex items-baseline gap-2 shrink-0 text-sm">
                        <span className={`font-semibold tabular-nums ${over ? "text-red-600 dark:text-[#eda2a2]" : "text-gray-900 dark:text-[#c4ccd8]"}`}>
                          {fmt(actual)}
                        </span>
                        <span className="text-xs text-gray-400 dark:text-[#8f99a8] tabular-nums">
                          {budgeted > 0 ? `of ${fmt(budgeted)}` : "unbudgeted"}
                        </span>
                      </div>
                    </div>
                    {split && <p className="text-xs text-gray-400 dark:text-[#8f99a8] mb-1">{split}</p>}
                    {budgeted > 0 && <ProgressBar actual={actual} budgeted={budgeted} />}
                  </div>
                );
```

- [ ] **Step 5: Verify with Interceptor**

Open Spending → Overview, light and dark. Confirm: the three hero cards show a muted sub-line only when a bucket has spend from more than one source; category rows with mixed-source spend show the same style of line above their progress bar; a category with only one source shows nothing extra (no empty `·` artifacts).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/Spending.tsx
git commit -m "Show checking/card split on hero cards and category rows

Sums breakdown_by_source (already returned per category) bucketed by
each top-level category's is_discretionary flag -- no new backend
call. Only renders when a bucket/category actually has more than one
non-zero source.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 5: Frontend — consolidate Trends into one ranged chart

**Files:**
- Modify: `frontend/src/pages/Spending.tsx` (Trends tab, ~line 39, ~line 80-90, ~line 314-330, ~line 374-426)

**Interfaces:**
- Consumes: `analyticsApi.rollingMonthly(months)` (existing client method, `frontend/src/api/index.ts:203`) — now also carries `checking`/`cards` per Task 1.
- Removes: `analyticsApi.yearlyTrends` usage from this file (the endpoint itself stays — see spec's compatibility note, it's just no longer called from here).

- [ ] **Step 1: Add a range control and drop the yearly-trends query**

Find (~line 80-90):

```tsx
  const { data: yearlyTrends = [] } = useQuery({
    queryKey: ["yearly-trends"],
    queryFn: () => analyticsApi.yearlyTrends(3),
    enabled: activeTab === "trends",
  });

  const { data: rollingMonthly = [] } = useQuery({
    queryKey: ["rolling-monthly"],
    queryFn: () => analyticsApi.rollingMonthly(24),
    enabled: activeTab === "trends",
  });
```

Replace with:

```tsx
  const { data: rollingMonthly = [] } = useQuery({
    queryKey: ["rolling-monthly", trendsRangeMonths],
    queryFn: () => analyticsApi.rollingMonthly(trendsRangeMonths),
    enabled: activeTab === "trends",
  });
```

Add the range state near the other `useState` calls at the top of the component (~line 53-59, alongside `start`/`end`):

```tsx
  const [trendsRangeMonths, setTrendsRangeMonths] = useState(12);
```

- [ ] **Step 2: Update `rollingBarData` to carry the source split, drop `trendBarData`**

Find (~line 314-330):

```tsx
  const trendBarData = useMemo(() => {
    if (!yearlyTrends.length) return [];
    return MONTH_NAMES.map((name, i) => {
      const entry: Record<string, number | string> = { month: name };
      (yearlyTrends as any[]).forEach((yr: any) => {
        entry[String(yr.year)] = parseFloat(yr.months[String(i + 1)] ?? "0");
      });
      return entry;
    });
  }, [yearlyTrends]);

  const rollingBarData = useMemo(() => {
    return (rollingMonthly as any[]).map((r: any) => ({
      month: r.month,
      total: parseFloat(r.total),
    }));
  }, [rollingMonthly]);
```

Replace with:

```tsx
  const rollingBarData = useMemo(() => {
    return (rollingMonthly as any[]).map((r: any) => ({
      month: r.month,
      total: parseFloat(r.total),
      checking: parseFloat(r.checking),
      cards: parseFloat(r.cards),
    }));
  }, [rollingMonthly]);
```

- [ ] **Step 3: Replace the two Trends charts with one, plus the range control**

Find the entire Trends tab block (~line 374-426):

```tsx
      {/* Trends tab */}
      {activeTab === "trends" && (
        <div className="space-y-6">
          {trendBarData.length > 0 && yearlyTrends.length > 0 && (
            <div className="card">
              <h3 className="font-semibold text-gray-900 dark:text-[#c4ccd8] mb-4">Year-Over-Year Monthly Spending</h3>
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={trendBarData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={ct.grid} />
                  <XAxis dataKey="month" tick={{ fontSize: 11, fill: ct.tick }} axisLine={{ stroke: ct.grid }} tickLine={false} />
                  <YAxis tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 11, fill: ct.tick }} axisLine={false} tickLine={false} />
                  <Tooltip content={({ active, payload, label }) => active && payload?.length ? (
                    <TooltipBox label={label} rows={payload.map((p: any) => ({ name: p.dataKey, value: p.value, color: p.fill }))} />
                  ) : null} cursor={{ fill: isDarkMode() ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.04)" }} />
                  <Legend formatter={(v) => <span style={{ color: ct.tick }} className="text-sm">{v}</span>} />
                  {(yearlyTrends as any[]).map((yr: any, i: number) => (
                    <Bar key={yr.year} dataKey={String(yr.year)} fill={YEAR_COLORS[i % YEAR_COLORS.length]} radius={[3, 3, 0, 0]} name={String(yr.year)} />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {rollingBarData.length > 0 && (
            <div className="card">
              <h3 className="font-semibold text-gray-900 dark:text-[#c4ccd8] mb-4">24-Month Spending Trend</h3>
              <ResponsiveContainer width="100%" height={220}>
                <AreaChart data={rollingBarData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="spendingTrendGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor="#6366f1" stopOpacity={0.20} />
                      <stop offset="95%" stopColor="#6366f1" stopOpacity={0.00} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke={ct.grid} />
                  <XAxis dataKey="month" tick={{ fontSize: 10, fill: ct.tick }} interval={2} axisLine={{ stroke: ct.grid }} tickLine={false} />
                  <YAxis tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 11, fill: ct.tick }} axisLine={false} tickLine={false} />
                  <Tooltip content={({ active, payload, label }) => active && payload?.length ? (
                    <TooltipBox label={label} rows={[{ name: "Spending", value: payload[0].value as number }]} />
                  ) : null} />
                  <Area type="monotone" dataKey="total" stroke="#6366f1" strokeWidth={2} fill="url(#spendingTrendGradient)" dot={false} animationDuration={700} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}

          {trendBarData.length === 0 && rollingBarData.length === 0 && (
            <div className="card text-center py-8 text-gray-400 dark:text-[#949daf] text-sm">
              No transaction data yet. Add transactions to see spending trends.
            </div>
          )}
        </div>
      )}
```

Replace with:

```tsx
      {/* Trends tab */}
      {activeTab === "trends" && (
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <h3 className="font-semibold text-gray-900 dark:text-[#c4ccd8]">Spending Over Time</h3>
            <div className="flex gap-1">
              {([["6M", 6], ["YTD", new Date().getMonth() + 1], ["1Y", 12], ["2Y", 24]] as const).map(([label, months]) => (
                <button
                  key={label}
                  type="button"
                  className={`px-2.5 py-1 text-xs rounded-md ${
                    trendsRangeMonths === months
                      ? "bg-indigo-500 text-white"
                      : "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-indigo-50 dark:hover:bg-indigo-900/30 hover:text-indigo-600 dark:hover:text-indigo-400"
                  }`}
                  onClick={() => setTrendsRangeMonths(months)}
                >{label}</button>
              ))}
            </div>
          </div>

          {rollingBarData.length > 0 ? (
            <div className="card">
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={rollingBarData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={ct.grid} />
                  <XAxis dataKey="month" tick={{ fontSize: 10, fill: ct.tick }} interval={trendsRangeMonths > 12 ? 2 : 0} axisLine={{ stroke: ct.grid }} tickLine={false} />
                  <YAxis tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 11, fill: ct.tick }} axisLine={false} tickLine={false} />
                  <Tooltip content={<StackedTooltip />} cursor={{ fill: isDarkMode() ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.04)" }} />
                  <Legend formatter={(v) => <span style={{ color: ct.tick }} className="text-sm">{v}</span>} />
                  <Bar dataKey="checking" stackId="spend" fill={ct.barFill} name="Checking" />
                  <Bar dataKey="cards" stackId="spend" fill="#f59e0b" radius={[3, 3, 0, 0]} name="Cards" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="card text-center py-8 text-gray-400 dark:text-[#949daf] text-sm">
              No transaction data yet. Add transactions to see spending trends.
            </div>
          )}
        </div>
      )}
```

- [ ] **Step 4: Remove now-dead code**

`YEAR_COLORS` (~line 35) and the `analyticsApi.yearlyTrends` import usage are now unused in this file. Grep the file for `YEAR_COLORS` and `yearlyTrends` — if Step 1-3 removed every reference (they should have), delete the `YEAR_COLORS` constant declaration too. Leave `analyticsApi` itself imported (still used for `rollingMonthly`).

- [ ] **Step 5: Verify with Interceptor**

Open Spending → Trends, light and dark. Confirm: one chart, four range buttons (6M/YTD/1Y/2Y), clicking each re-fetches and re-renders with the right month count, bars are stacked Checking/Cards, legend and tooltip both legible in dark mode.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/Spending.tsx
git commit -m "Consolidate Trends into one ranged, stacked chart

Removes the redundant year-over-year bar chart (same question as the
rolling chart, just calendar-aligned) and adds a 6M/YTD/1Y/2Y range
control in its place. Stacked by Checking/Cards using the split added
to /spending/rolling-monthly.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 6: Frontend — Flow visual restyle

**Files:**
- Modify: `frontend/src/pages/Spending.tsx` (`SankeyChart`, ~line 979-1052)

**Interfaces:**
- Consumes: the grouped `SankeyResponse` from Task 2 (no shape change, just fewer/larger expense nodes at runtime).

- [ ] **Step 1: Fix the dark-mode contrast bug and tighten spacing**

Find (~line 979-983):

```tsx
function SankeyChart({ data }: { data: any }) {
  const WIDTH = 720;
  const HEIGHT = 400;
  const PADDING = 120;
```

Replace with:

```tsx
function SankeyChart({ data }: { data: any }) {
  const WIDTH = 720;
  const HEIGHT = 400;
  const PADDING = 140;
```

Find (~line 1000-1005):

```tsx
  const sankeyLayout = d3Sankey<{ id: string; name: string; type: string }, { value: number }>()
    .nodeId((d: any) => d.id)
    .nodeAlign(sankeyLeft)
    .nodeWidth(14)
    .nodePadding(16)
    .extent([[PADDING, 10], [WIDTH - PADDING, HEIGHT - 10]]);
```

Replace with:

```tsx
  const sankeyLayout = d3Sankey<{ id: string; name: string; type: string }, { value: number }>()
    .nodeId((d: any) => d.id)
    .nodeAlign(sankeyLeft)
    .nodeWidth(14)
    .nodePadding(20)
    .extent([[PADDING, 10], [WIDTH - PADDING, HEIGHT - 10]]);
```

- [ ] **Step 2: Switch expense nodes to semantic red, fix the amount label's dark-mode contrast**

Find (~line 1030-1046):

```tsx
        {graph.nodes.map((n: any, i: number) => {
          const isLeft = n.x0 < WIDTH / 2;
          const color = n.type === "income" ? "#10b981" : n.type === "income_total" ? "#6366f1" : "#f59e0b";
          const labelX = isLeft ? n.x0 - 6 : n.x1 + 6;
          const anchor = isLeft ? "end" : "start";
          const midY = (n.y0 + n.y1) / 2;
          return (
            <g key={i}>
              <rect x={n.x0} y={n.y0} width={n.x1 - n.x0} height={n.y1 - n.y0} fill={color} rx={2} />
              <text x={labelX} y={midY - 5} textAnchor={anchor} fontSize={11} fill={isDarkMode() ? "#c4ccd8" : "#374151"} fontWeight={500}>
                {n.name}
              </text>
              <text x={labelX} y={midY + 8} textAnchor={anchor} fontSize={10} fill="#6b7280">
                {fmt2(n.value)}
              </text>
            </g>
          );
        })}
```

Replace with:

```tsx
        {graph.nodes.map((n: any, i: number) => {
          const isLeft = n.x0 < WIDTH / 2;
          // Semantic green/red for income/expense, indigo for the total
          // pool node -- was a three-color scheme (green/indigo/amber) that
          // didn't map expense to the red used everywhere else on this page.
          const color = n.type === "income" ? "#10b981" : n.type === "income_total" ? "#6366f1" : "#dc2626";
          const labelX = isLeft ? n.x0 - 6 : n.x1 + 6;
          const anchor = isLeft ? "end" : "start";
          const midY = (n.y0 + n.y1) / 2;
          return (
            <g key={i}>
              <rect x={n.x0} y={n.y0} width={n.x1 - n.x0} height={n.y1 - n.y0} fill={color} rx={2} />
              <text x={labelX} y={midY - 5} textAnchor={anchor} fontSize={11} fill={isDarkMode() ? "#c4ccd8" : "#374151"} fontWeight={500}>
                {n.name}
              </text>
              <text x={labelX} y={midY + 8} textAnchor={anchor} fontSize={10} fill={isDarkMode() ? "#8f99a8" : "#6b7280"}>
                {fmt2(n.value)}
              </text>
            </g>
          );
        })}
```

(The amount label previously hardcoded `#6b7280` regardless of theme — a real dark-mode legibility gap, now matching the muted-tick convention (`ct.tick`) used everywhere else on this page.)

- [ ] **Step 3: Verify with Interceptor**

Open Spending → Flow for a month with real data, light and dark. Confirm: expense nodes are red (not amber), income nodes green, the total-income node indigo, both label lines are legible in dark mode, node spacing looks less cramped than before, an "Other" node appears when there are more categories than the cap (from Task 2) and "Uncategorized" (if present) is still its own separate node.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Spending.tsx
git commit -m "Restyle Flow: semantic red/green/indigo, fix dark-mode label contrast

Expense nodes were amber, not the red used everywhere else on this
page. The per-node amount label was hardcoded #6b7280 regardless of
theme -- a real dark-mode legibility gap, now matching the page's
existing muted-tick color convention.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 7: Frontend — move Tax Export to its own nav item

**Files:**
- Create: `frontend/src/pages/TaxExport.tsx`
- Modify: `frontend/src/pages/Spending.tsx` (remove the `tax` tab entirely)
- Modify: `frontend/src/App.tsx` (add the `/tax` route)
- Modify: `frontend/src/lib/navItems.ts` (add the nav entry)

**Interfaces:**
- Produces: `export default function TaxExport()`, a standalone page component with no props, registered at route `/tax`.

- [ ] **Step 1: Create the new page with the moved content**

Create `frontend/src/pages/TaxExport.tsx`:

```tsx
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { spendingApi } from "../api";
import { api } from "../api/client";
import { fmt } from "../lib/utils";
import { AlertTriangle } from "lucide-react";

export default function TaxExport() {
  const [taxYear, setTaxYear] = useState(new Date().getFullYear() - 1);

  const { data: taxEstimate, isLoading: taxEstimateLoading } = useQuery({
    queryKey: ["tax-estimate", taxYear],
    queryFn: () => spendingApi.taxEstimate(taxYear),
  });

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-gray-900 dark:text-[#c4ccd8]">Tax Export</h2>
        <p className="text-sm text-gray-500 dark:text-[#8f99a8]">Estimated taxes and deductible-transaction export.</p>
      </div>

      <div className="space-y-4">
        {/* Year selector */}
        <div className="flex items-center gap-3">
          <label className="label mb-0">Tax Year</label>
          <select className="input w-auto" value={taxYear} onChange={e => setTaxYear(parseInt(e.target.value))}>
            {[-2, -1, 0].map(d => { const y = new Date().getFullYear() + d; return <option key={y} value={y}>{y}</option>; })}
          </select>
          <button
            className="btn-secondary text-sm ml-auto"
            onClick={async () => {
              const res = await api.get(`/spending/tax-summary?year=${taxYear}&format=csv`, { responseType: "blob" });
              const url = URL.createObjectURL(res.data);
              const a = document.createElement("a");
              a.href = url;
              a.download = `tax-summary-${taxYear}.csv`;
              a.click();
              URL.revokeObjectURL(url);
            }}
          >
            Download Deductibles CSV
          </button>
        </div>

        {taxEstimateLoading && <div className="text-center py-8 text-gray-400 text-sm">Calculating…</div>}

        {taxEstimate?.error && (
          <div className="card bg-amber-50 dark:bg-amber-900/20 text-amber-800 dark:text-amber-300 text-sm">
            {taxEstimate.error} <a href="/settings/tax" className="underline ml-1">Go to Settings</a>
          </div>
        )}

        {taxEstimate && !taxEstimate.error && (() => {
          const te = taxEstimate as any;
          const refund = Number(te.total_refund_or_owed);
          const fedRefund = Number(te.federal_refund_or_owed);
          const stateRefund = Number(te.state_refund_or_owed);
          return (
            <div className="space-y-4">
              {/* Summary banner */}
              <div className={`card border-2 ${refund >= 0 ? "border-green-300 dark:border-green-700 bg-green-50 dark:bg-green-900/20" : "border-red-300 dark:border-red-700 bg-red-50 dark:bg-red-900/20"}`}>
                <div className="flex items-center justify-between flex-wrap gap-4">
                  <div>
                    <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">{refund >= 0 ? "Estimated Refund" : "Estimated Amount Owed"}</p>
                    <p className={`text-3xl font-bold ${refund >= 0 ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}>
                      {refund >= 0 ? "+" : "-"}{fmt(Math.abs(refund))}
                    </p>
                    <p className="text-xs text-gray-500 mt-1">Effective rate: {(Number(te.effective_rate) * 100).toFixed(1)}% · Filing: {te.filing_status.replace("_", " ")} · {te.state}</p>
                  </div>
                  <div className="text-sm space-y-1">
                    <div className="flex gap-6">
                      <span className="text-gray-500">Federal {fedRefund >= 0 ? "refund" : "owed"}</span>
                      <span className={`font-semibold ${fedRefund >= 0 ? "text-green-600" : "text-red-600"}`}>{fedRefund >= 0 ? "+" : ""}{fmt(fedRefund)}</span>
                    </div>
                    {!te.state_no_income_tax && (
                      <div className="flex gap-6">
                        <span className="text-gray-500">State {stateRefund >= 0 ? "refund" : "owed"}</span>
                        <span className={`font-semibold ${stateRefund >= 0 ? "text-green-600" : "text-red-600"}`}>{stateRefund >= 0 ? "+" : ""}{fmt(stateRefund)}</span>
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {/* Breakdown */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="card space-y-2">
                  <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Income</h4>
                  <dl className="space-y-1 text-sm">
                    <div className="flex justify-between"><dt className="text-gray-500">Gross salary</dt><dd className="tabular-nums">{fmt(Number(te.taxable_income) + Number(te.deduction_used))}</dd></div>
                    <div className="flex justify-between"><dt className="text-gray-500">Deduction ({te.used_itemized ? "itemized" : "standard"})</dt><dd className="tabular-nums text-green-600">−{fmt(te.deduction_used)}</dd></div>
                    <div className="flex justify-between border-t border-gray-100 dark:border-gray-700 pt-1 font-medium"><dt>Taxable income</dt><dd className="tabular-nums">{fmt(te.taxable_income)}</dd></div>
                    {te.used_itemized && te.itemized_breakdown && (() => {
                      const bd = te.itemized_breakdown;
                      const rows = [
                        { label: "Mortgage interest", val: bd.mortgage_interest },
                        { label: "Charitable donations", val: bd.donations },
                        { label: "SALT", val: bd.salt },
                        { label: "Property taxes", val: bd.property_tax },
                        { label: "Other deductions", val: bd.other },
                        { label: "Deductible transactions", val: bd.transaction_deductibles },
                      ].filter(r => r.val > 0);
                      return rows.map(r => (
                        <div key={r.label} className="flex justify-between text-xs text-gray-400 pl-2"><dt>{r.label}</dt><dd className="tabular-nums">{fmt(r.val)}</dd></div>
                      ));
                    })()}
                  </dl>
                </div>
                <div className="card space-y-2">
                  <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Tax Breakdown</h4>
                  <dl className="space-y-1 text-sm">
                    <div className="flex justify-between"><dt className="text-gray-500">Federal income tax</dt><dd className="tabular-nums text-red-600">{fmt(te.federal_tax)}</dd></div>
                    {!te.state_no_income_tax && <div className="flex justify-between"><dt className="text-gray-500">State income tax ({(te.state_rate * 100).toFixed(2)}%)</dt><dd className="tabular-nums text-red-600">{fmt(te.state_tax)}</dd></div>}
                    {te.state_no_income_tax && <div className="flex justify-between"><dt className="text-gray-500">State income tax</dt><dd className="text-green-600 text-xs">No state income tax</dd></div>}
                    <div className="flex justify-between"><dt className="text-gray-500">Social Security (6.2%)</dt><dd className="tabular-nums text-red-600">{fmt(te.fica_ss)}</dd></div>
                    <div className="flex justify-between"><dt className="text-gray-500">Medicare (1.45%)</dt><dd className="tabular-nums text-red-600">{fmt(te.fica_medicare)}</dd></div>
                    <div className="flex justify-between border-t border-gray-100 dark:border-gray-700 pt-1 font-medium"><dt>Total taxes</dt><dd className="tabular-nums text-red-600">{fmt(te.total_tax)}</dd></div>
                  </dl>
                </div>
              </div>

              {/* Federal bracket ladder */}
              {te.brackets?.length > 0 && (
                <div className="card">
                  <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">Federal Bracket Breakdown</h4>
                  <table className="w-full text-sm">
                    <thead><tr className="text-xs font-medium text-gray-500 uppercase">
                      <th className="pb-2 text-left">Rate</th>
                      <th className="pb-2 text-right">Income in bracket</th>
                      <th className="pb-2 text-right">Tax</th>
                    </tr></thead>
                    <tbody className="divide-y divide-gray-50 dark:divide-gray-800">
                      {(te.brackets as any[]).map((b: any, i: number) => (
                        <tr key={i}>
                          <td className="py-1 text-indigo-600 dark:text-indigo-300 font-medium">{(b.rate * 100).toFixed(0)}%</td>
                          <td className="py-1 text-right tabular-nums text-gray-600 dark:text-gray-400">{fmt(b.income)}</td>
                          <td className="py-1 text-right tabular-nums font-medium">{fmt(b.tax)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <>
                {(taxEstimate as any)?.bracket_year && (taxEstimate as any).bracket_year !== taxYear && (
                  <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-2.5 mb-2 dark:border-amber-900/60 dark:bg-amber-950/40">
                    <AlertTriangle size={14} className="mt-0.5 shrink-0 text-amber-600 dark:text-amber-400" />
                    <p className="text-xs text-amber-800 dark:text-amber-200">
                      You're estimating <b>{taxYear}</b>, but the bundled bracket tables are{" "}
                      <b>{(taxEstimate as any).bracket_year}</b>. Rates, bracket floors and the standard
                      deduction all shift year to year, so treat this as a rough figure until the {taxYear} tables ship.
                    </p>
                  </div>
                )}
                <p className="text-xs text-gray-400">
                  Estimates use {(taxEstimate as any)?.bracket_year ?? "bundled"} federal brackets. State tax uses
                  approximate effective rates. This is not tax advice — consult a tax professional.
                </p>
              </>
            </div>
          );
        })()}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Remove the tax tab from `Spending.tsx`**

Remove `"tax"` from the `activeTab` type union (~line 39):

```tsx
  const [activeTab, setActiveTab] = useState<"overview" | "trends" | "merchants" | "flow" | "tax">("overview");
```

becomes:

```tsx
  const [activeTab, setActiveTab] = useState<"overview" | "trends" | "merchants" | "flow">("overview");
```

Remove `taxYear` state (~line 50), the `taxEstimate` query (~line 104-108), and the tab array + label ternary (~line 359, 369):

```tsx
        {(["overview", "trends", "merchants", "flow", "tax"] as const).map((tab) => (
```
becomes
```tsx
        {(["overview", "trends", "merchants", "flow"] as const).map((tab) => (
```

and

```tsx
            {tab === "flow" ? "Flow" : tab === "tax" ? "Tax Export" : tab}
```
becomes
```tsx
            {tab === "flow" ? "Flow" : tab}
```

Delete the entire `{activeTab === "tax" && (...)}` JSX block (the whole section from `{activeTab === "tax" && (` through its matching closing `)}`, immediately before the `{showHelp && ...}` line) — its content now lives in `TaxExport.tsx` from Step 1.

Update the `HelpPanel` body text (in the `showHelp` block near the end of the file) to drop the now-inaccurate "Tax Export tab" sentence:

```tsx
{showHelp && <HelpPanel title="Spending Analysis" body={"Analyze your spending by category across any date range.\n\nOverview tab: budgeted vs. actual by category with breakdown by account and card.\nTrends tab: year-over-year comparison and 24-month rolling totals.\nFlow tab: Sankey diagram showing income sources flowing into expense categories.\nTax Export tab: download a CSV of deductible transactions for tax filing."} onClose={() => setShowHelp(false)} />}
```

becomes:

```tsx
{showHelp && <HelpPanel title="Spending Analysis" body={"Analyze your spending by category across any date range.\n\nOverview tab: budgeted vs. actual by category, split by checking vs. card.\nTrends tab: spending over a range you choose, split by checking vs. card.\nFlow tab: Sankey diagram showing income sources flowing into expense categories."} onClose={() => setShowHelp(false)} />}
```

- [ ] **Step 3: Register the route**

In `frontend/src/App.tsx`, add the import alongside the others (~line 10):

```tsx
import Spending from "./pages/Spending";
```
becomes
```tsx
import Spending from "./pages/Spending";
import TaxExport from "./pages/TaxExport";
```

Add the route alongside `spending` (~line 47):

```tsx
          <Route path="spending" element={<Spending />} />
```
becomes
```tsx
          <Route path="spending" element={<Spending />} />
          <Route path="tax" element={<TaxExport />} />
```

- [ ] **Step 4: Add the nav entry**

In `frontend/src/lib/navItems.ts`, add `Receipt` to the icon import (~line 2-6):

```tsx
import {
  LayoutDashboard, CreditCard, TrendingUp, PieChart,
  Repeat, ArrowLeftRight, Target, Settings, Upload,
  CalendarDays, Wallet, BarChart2,
} from "lucide-react";
```
becomes
```tsx
import {
  LayoutDashboard, CreditCard, TrendingUp, PieChart,
  Repeat, ArrowLeftRight, Target, Settings, Upload,
  CalendarDays, Wallet, BarChart2, Receipt,
} from "lucide-react";
```

Add the item to the `"money"` group, right after Spending (spend-derived data, per the design doc's placement note):

```tsx
  {
    key: "money", label: "Money", items: [
      { to: "/transactions", icon: ArrowLeftRight, label: "Transactions" },
      { to: "/spending", icon: PieChart, label: "Spending" },
      { to: "/recurring", icon: Repeat, label: "Recurring" },
      { to: "/import", icon: Upload, label: "Import" },
    ],
  },
```
becomes
```tsx
  {
    key: "money", label: "Money", items: [
      { to: "/transactions", icon: ArrowLeftRight, label: "Transactions" },
      { to: "/spending", icon: PieChart, label: "Spending" },
      { to: "/tax", icon: Receipt, label: "Tax" },
      { to: "/recurring", icon: Repeat, label: "Recurring" },
      { to: "/import", icon: Upload, label: "Import" },
    ],
  },
```

- [ ] **Step 5: Verify with Interceptor**

Confirm: "Tax" appears in the sidebar's Money group (and is pinnable, since `PINNABLE_ITEMS` derives from `NAV_GROUPS` automatically); navigating to it renders identically to the old Tax Export tab (year selector, CSV download, refund banner, bracket table); the Spending page's tab bar now shows only Overview/Trends/Merchants/Flow; the in-app Help panel on Spending no longer mentions a Tax Export tab. Check both light and dark mode.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/TaxExport.tsx frontend/src/pages/Spending.tsx frontend/src/App.tsx frontend/src/lib/navItems.ts
git commit -m "Move Tax Export to its own nav item

Annual tax filing and monthly spend analysis are different rhythms --
gave Tax its own /tax route and sidebar entry (Money group, next to
Spending) instead of a fifth Spending sub-tab. Content/logic moved
as-is, no calculation changes (those are a separate, already-scoped
fix).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Self-Review Notes

**Spec coverage:** §1 (Overview split) → Tasks 3-4. §2 (Trends consolidation) → Task 5. §4 (Flow) → Tasks 2, 6. §5 (Nav/Tax relocation) → Task 7. §6 (Merchants) is explicitly optional/deferred per the spec — no task, matching "cut from v1 scope" language in the spec itself.

**Type consistency check:** `RollingMonthEntry.checking`/`.cards` (Task 1) match the field names `MonthlySpendingEntry` already uses, and Task 5's `rollingBarData` reads `r.checking`/`r.cards` consistently with what Task 1 adds. `sourceSplitLabel` (Task 4) is defined once and used at both call sites in the same task — no cross-task naming drift.

**No new backend endpoints or schema/migration changes anywhere in this plan**, matching the spec's Testing section.
