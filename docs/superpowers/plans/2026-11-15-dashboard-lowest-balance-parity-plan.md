# Dashboard Lowest-Balance Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the Dashboard's "lowest projected balance" display to parity with the daily email: show the "Lowest next month" row (collapsing into the existing 3-month row when they land on the same day/amount) and the "Move $Y into checking by &lt;date&gt;" suggestion when next month's low goes negative.

**Architecture:** The email's row-selection/collapse logic (`_lowest_balance_rows` in `backend/services/summary_generator.py`) is pure comparison over fields the Dashboard already receives from `GET /analytics/budget-snapshot` (`lookahead_minimum(_date)`, `next_month_minimum(_date)`, `next_month_label`) — ported directly into Dashboard.tsx, no backend change needed for that part. The "Move $Y" amount is money math (round UP to the next $1,000) that must NOT be computed in the frontend (`docs/architecture.md`: "the frontend displays backend figures and does no money math", enforced by `frontend/tests/moneyGuard.test.ts`). It's computed once in `backend/services/budget_snapshot.py` (where `next_month_minimum` is already computed) as a new field `move_to_checking_needed`, and `summary_generator.py`'s existing `_move_to_checking_line` is refactored to read that field instead of recomputing it, so the email and the dashboard can never drift. The Dashboard then only displays `move_to_checking_needed`, no arithmetic.

**Tech Stack:** FastAPI + Pydantic (backend/schemas.py), SQLAlchemy service layer (backend/services/), React + TypeScript (frontend/src/pages/Dashboard.tsx), pytest (backend/tests/), bun test (frontend/tests/).

**Spec:** No separate written design doc — Dan approved this directly in chat ("I would like see the three month low just like the email report on the main dashboard" → "build like the email exactly"), after being told the two concrete gaps (the "Lowest next month" row and the "Move $Y into checking" line) and confirming he wants both, matching the email's exact text/colors/conditions.

## Global Constraints

- Public repo (rookford343/OfflineBudget): no real balances/amounts/dates/merchant names in commits, test fixtures, or docs — invented figures only.
- Frontend does no money arithmetic (`docs/architecture.md`; enforced by `frontend/tests/moneyGuard.test.ts`) — the Dashboard reads `move_to_checking_needed` as a ready-made backend figure, and only does date display (first-of-month), never dollar math.
- Match the email's exact text verbatim: `"Lowest next month ({label})"`, `"Lowest next month ({label}) and in the next 3 months"`, `"Lowest in the next 3 months"`, `"Move {amount} into checking by {month} {day}"` (see `backend/services/summary_generator.py:41-88`).
- Commits end with `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`.
- Commit directly to `main` — no feature branches/worktrees (standing repo convention).
- Python via `uv run --locked`; frontend via `bun`/`bunx` — never bare `pip`/`python`/`npm`/`npx`.

## Review Focus

- **`next_month_minimum_date` is `None` but `lookahead_minimum_date` is set** (today's existing-only case): Dashboard must keep showing just the 3-month row, unchanged — covered by Task 2's "no next-month date" case.
- **Negative `next_month_minimum` with `move_to_checking_needed` exactly $0** (e.g. a cent-level negative that still rounds to a $0 need — shouldn't happen given the rounding-UP formula, but the condition for showing the move line must key off `move_to_checking_needed > 0`, not off `next_month_minimum < 0`, so the two can't disagree): covered by Task 1's new backend test and Task 2's render condition.
- **`next_month_minimum_date` present but `lookahead_minimum_date` is `None`** (quarter walk somehow empty while next-month isn't): `_lowest_balance_rows` has no branch for this inverse case today (it only short-circuits when `next_month_minimum_date is None`); port the Python logic exactly as written rather than "fixing" this — covered by Task 2's row-building logic matching Python line-for-line.
- **Dark mode**: every new color class needs a `dark:` variant, matching the file's existing convention (e.g. `text-green-600 dark:text-green-400`) — covered by Task 2's styling step.
- **Existing email tests must not regress** from the `_move_to_checking_line` refactor — covered by Task 1's "run full existing test file" step before any new test is added.

---

### Task 1: Backend — compute and expose `move_to_checking_needed`

**Files:**
- Modify: `backend/schemas.py` (around `BudgetSnapshot.next_month_minimum`/`next_month_minimum_date`/`next_month_label`, ~line 2036-2041)
- Modify: `backend/services/budget_snapshot.py` (near `_next_month_minimum(...)` call at line 612-614, and the `BudgetSnapshot(...)` constructor call at line 882-884)
- Modify: `backend/services/summary_generator.py` (`_round_up_to_thousand` definition at line 32-38, `_move_to_checking_line` at line 41-49)
- Modify: `backend/tests/test_summary_generator_next_month_low.py` (`_blank_snapshot` helper at line 25-59)
- Test: `backend/tests/test_budget_snapshot.py` (new test(s) for `move_to_checking_needed`)

**Interfaces:**
- Produces: `BudgetSnapshot.move_to_checking_needed: Decimal` (default `Decimal("0.00")`) — the amount, already rounded UP to the next whole $1,000, needed to bring next month's projected low back to exactly $0; `Decimal("0.00")` when `next_month_minimum_date is None` or `next_month_minimum >= 0`.
- Produces: `_round_up_to_thousand(amount: Decimal) -> Decimal`, moved to `backend/services/budget_snapshot.py`, still importable as `from backend.services.summary_generator import _round_up_to_thousand` (re-exported) for the existing test that imports it from there.
- Consumes: nothing new — uses `next_month_min` / `next_month_min_date`, already local variables in `compute_budget_snapshot` at line 612-614.

- [ ] **Step 1: Write the failing backend tests**

In `backend/tests/test_budget_snapshot.py`, add (using whatever existing fixture/helper in that file builds a `compute_budget_snapshot` scenario with a checking account and a known negative projected low next month — follow that file's existing pattern for setting up accounts/bills with invented figures):

```python
def test_move_to_checking_needed_rounds_up_when_next_month_low_is_negative(db_session):
    # ... build a scenario whose next month's projected low is -612.40 ...
    snap = compute_budget_snapshot(db_session, user, account.id)
    assert snap.next_month_minimum == Decimal("-612.40")
    assert snap.move_to_checking_needed == Decimal("1000.00")


def test_move_to_checking_needed_is_zero_when_next_month_low_is_non_negative(db_session):
    # ... build a scenario whose next month's projected low is 0 or positive ...
    snap = compute_budget_snapshot(db_session, user, account.id)
    assert snap.move_to_checking_needed == Decimal("0.00")
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `cd backend && uv run --locked pytest tests/test_budget_snapshot.py -k move_to_checking_needed -v`
Expected: FAIL with `AttributeError: 'BudgetSnapshot' object has no attribute 'move_to_checking_needed'` (or similar, since the field doesn't exist yet).

- [ ] **Step 3: Add the `move_to_checking_needed` field to `BudgetSnapshot` in `backend/schemas.py`**

Right after `next_month_label: Optional[str] = None` (~line 2041), add:

```python
# Rounded UP to the next whole $1,000 -- how the daily email's "Move $Y
# into checking by <date>" line is sized (see
# services/budget_snapshot._round_up_to_thousand). 0.00 when next month's
# low isn't negative. API-additive: defaulted so existing callers/fixtures
# keep working unchanged.
move_to_checking_needed: Decimal = Decimal("0.00")
```

- [ ] **Step 4: Move `_round_up_to_thousand` into `backend/services/budget_snapshot.py` and compute `move_to_checking_needed`**

Move the function body verbatim (it already imports `ROUND_CEILING`, which `budget_snapshot.py` already imports) to a module-level function in `budget_snapshot.py`, placed near `_next_month_minimum`. Immediately after the `next_month_min, next_month_min_date, _next_month_start, next_month_label = _next_month_minimum(...)` call (line 612-614), add:

```python
move_to_checking_needed = (
    _round_up_to_thousand(-next_month_min)
    if next_month_min_date is not None and next_month_min < 0
    else Decimal("0.00")
)
```

Pass it into the `BudgetSnapshot(...)` constructor call alongside the other `next_month_*` fields (~line 882-884): `move_to_checking_needed=move_to_checking_needed,`.

- [ ] **Step 5: Update `backend/services/summary_generator.py` to consume the field instead of recomputing**

Delete the local `_round_up_to_thousand` definition (lines 32-38) and instead import it: `from backend.services.budget_snapshot import _round_up_to_thousand` (keep the import alongside the module's other imports — this re-export is what keeps `from backend.services.summary_generator import _round_up_to_thousand` working for the existing test). Replace `_move_to_checking_line` (lines 41-49) with:

```python
def _move_to_checking_line(snap) -> str | None:
    """"Move $Y into checking by <1st of next month>" when next month's low
    is projected to dip below $0, else None. Y is `snap.move_to_checking_needed`,
    computed once in budget_snapshot.py so the email and dashboard agree."""
    if snap.next_month_minimum_date is None or snap.move_to_checking_needed <= 0:
        return None
    move_by = snap.next_month_minimum_date.replace(day=1)
    return f"Move {_fmt(snap.move_to_checking_needed)} into checking by {move_by.strftime('%b %-d')}"
```

- [ ] **Step 6: Update the `_blank_snapshot` test helper so existing email tests keep passing unchanged**

In `backend/tests/test_summary_generator_next_month_low.py`, add `move_to_checking_needed=Decimal("0")` to the `defaults` dict in `_blank_snapshot` (~line 52, next to `next_month_label=None`). Then, after `defaults.update(overrides)` and before `return BudgetSnapshot(**defaults)`, derive it automatically when the test didn't override it directly, reusing the same helper:

```python
if "move_to_checking_needed" not in overrides:
    nm_min = defaults["next_month_minimum"]
    defaults["move_to_checking_needed"] = (
        _round_up_to_thousand(-nm_min)
        if defaults["next_month_minimum_date"] is not None and nm_min < 0
        else Decimal("0.00")
    )
```

This keeps every existing test in this file (which only sets `next_month_minimum`/`next_month_minimum_date`) passing without touching their bodies.

- [ ] **Step 7: Run the new tests to verify they pass**

Run: `cd backend && uv run --locked pytest tests/test_budget_snapshot.py -k move_to_checking_needed -v`
Expected: PASS

- [ ] **Step 8: Run the full existing test file to confirm no regression**

Run: `cd backend && uv run --locked pytest tests/test_summary_generator_next_month_low.py -v`
Expected: all PASS, unchanged from before this task (same test count, same names) — this is the regression check for the `_move_to_checking_line` refactor.

- [ ] **Step 9: Run the full backend test suite**

Run: `cd backend && uv run --locked pytest -q`
Expected: PASS (coverage floor in `backend/.coveragerc` met)

- [ ] **Step 10: Lint**

Run: `cd backend && uv run --locked ruff check .`
Expected: no findings

- [ ] **Step 11: Commit**

```bash
git add backend/schemas.py backend/services/budget_snapshot.py backend/services/summary_generator.py backend/tests/test_summary_generator_next_month_low.py backend/tests/test_budget_snapshot.py
git commit -m "feat: expose move_to_checking_needed on BudgetSnapshot

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: Frontend — render the next-month row and move-to-checking line

**Files:**
- Modify: `frontend/src/pages/Dashboard.tsx` (the lowest-balance block at lines 456-484)

**Interfaces:**
- Consumes: `snapshot.lookahead_minimum`, `snapshot.lookahead_minimum_date`, `snapshot.lookahead_status`, `snapshot.safety_cushion` (all already used at lines 457-480); new: `snapshot.next_month_minimum: string`, `snapshot.next_month_minimum_date: string | null`, `snapshot.next_month_label: string | null`, `snapshot.move_to_checking_needed: string` (all already serialized by the backend as of Task 1 — same `GET /analytics/budget-snapshot` response `snapshot` already fetched at line 192-196, no new API call).

- [ ] **Step 1: Replace the lowest-balance block (lines 456-484) with row-building logic ported from `_lowest_balance_rows` / `_move_to_checking_line`**

Port `backend/services/summary_generator.py:52-88` (`_lowest_balance_rows`) and the move-line condition from `:41-49` (`_move_to_checking_line`) line-for-line into a small helper near the top of the component (follow the existing precedent at `nextCardDueOccurrence`, including a comment noting what it mirrors and why — "so the dashboard and the daily email never disagree"). Build an array of `{ label: string; amount: number; date: string; isLookaheadRow: boolean }` (0, 1, or 2 entries) exactly matching the Python branches:
  - both `lookahead_minimum_date` and `next_month_minimum_date` absent → `[]` (render nothing, same as today when there's no lookahead date — though note Review Focus: this plan does not add a branch for "next_month_minimum_date present but lookahead_minimum_date absent", matching Python's existing gap)
  - `next_month_minimum_date` absent → single row: `{ label: "Lowest in the next 3 months", amount: lookahead_minimum, date: lookahead_minimum_date, isLookaheadRow: true }` (today's existing behavior, unchanged)
  - both present, same date AND same amount → single combined row: `{ label: \`Lowest next month (${next_month_label || "next month"}) and in the next 3 months\`, amount: next_month_minimum, date: next_month_minimum_date, isLookaheadRow: true }`
  - both present, different → two rows in this order: `{ label: \`Lowest next month (${next_month_label || "next month"})\`, amount: next_month_minimum, date: next_month_minimum_date, isLookaheadRow: false }`, then `{ label: "Lowest in the next 3 months", amount: lookahead_minimum, date: lookahead_minimum_date, isLookaheadRow: true }`

  `isLookaheadRow` marks which row is the one `_is_lookahead_row` picks out in Python (`"next 3 months" in label`) — it's the row that gets the cushion/danger coloring and warning phrase; the plain next-month-only row never does.

- [ ] **Step 2: Render each row**

For each row, keep the existing structure/wrapper (`<p className="text-xs text-gray-500 dark:text-gray-400 mt-3 text-center">` for the first row, `mt-1` or similar for a second row — match the vertical rhythm used elsewhere on this page for stacked lines) with the label text followed by the amount:
  - If `row.isLookaheadRow` and `snapshot.lookahead_status !== "ok"`: keep exactly the existing amber/red logic (lines 458-463, 475-481) — `figureClass` from `lookahead_status`, and the "below $0" / "below your cushion" phrase on its own line.
  - Else: color by sign only, matching the file's existing sign-based convention (e.g. lines 372, 512, 610) — `text-red-600 dark:text-red-400` when `row.amount < 0`, else `text-green-600 dark:text-green-400`. No warning phrase.
  - Keep `HowCalculated`/`WhatChanged` only on the row that already has them today (the lookahead-carrying row — `metric: { key: "lookahead_minimum", ... }`); the plain next-month-only row gets neither (the email doesn't attach per-row "since" lines to the dashboard's WhatChanged equivalent, and this dashboard already has a richer per-metric history view than the email's "since" line).

- [ ] **Step 3: Render the move-to-checking line directly under the first row, when needed**

Immediately after the first row (matching the email's `if i == 0 and move_line` at line 518), when `parseFloat(snapshot.move_to_checking_needed) > 0` and `snapshot.next_month_minimum_date` is present:

```tsx
<p className="text-[11px] text-red-600 dark:text-red-400 mt-1 text-center">
  Move {maskIfHidden(balancesHidden, fmt(parseFloat(snapshot.move_to_checking_needed)))} into checking by{" "}
  {new Date(new Date(snapshot.next_month_minimum_date + "T12:00:00").getFullYear(), new Date(snapshot.next_month_minimum_date + "T12:00:00").getMonth(), 1)
    .toLocaleDateString("en-US", { month: "short", day: "numeric" })}
</p>
```

(Date-only manipulation — setting the day-of-month to 1 — not money math; `move_to_checking_needed` itself is displayed as-is from the backend, never computed here.)

- [ ] **Step 4: Verify the moneyGuard test still passes**

Run: `cd frontend && bun test tests/moneyGuard.test.ts`
Expected: PASS (confirms no new money arithmetic was introduced in the frontend)

- [ ] **Step 5: Build**

Run: `cd frontend && bunx vite build`
Expected: builds successfully (same pre-existing TypeScript error count as before this change — tracked debt, not to be fixed or added to)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/Dashboard.tsx
git commit -m "feat: show next-month low and move-to-checking line on Dashboard

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

- [ ] **Step 7: Live verification via Interceptor**

Per standing operational rules, verify the rendered Dashboard live (not just build success) via the Interceptor skill before calling this done — check: the existing-only case (no next-month date) still renders unchanged, a different-date-and-amount case shows two rows in the right order/colors, and (if reachable with current data) the move-to-checking line renders when applicable. Requires the Interceptor test Chrome profile to be connected — reopen it manually first if needed.
