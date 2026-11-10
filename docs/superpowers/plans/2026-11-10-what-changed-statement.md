# What Changed Statement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the "what changed" popup into a running statement of one figure: grouped by day, each row showing when it moved, why, by how much and the balance after, with the math one tap away.

**Architecture:** A new read-only route, `GET /history/{metric_key}/statement`, builds the statement from the readings already stored. `services/metric_diff.py` adds the day grouping, subtotals, running balances and before/after math lines, so the frontend only displays figures. `WhatChanged.tsx` is rewritten around that response and takes one figure instead of a list.

**Tech Stack:** FastAPI, SQLAlchemy 2 (SQLite), pydantic v2, pytest via `uv run --locked`; React + TypeScript, TanStack Query, Radix Dialog, lucide icons, `bun test`.

**Spec:** Approved in chat on 2026-11-10 (mockup option A, "running statement"). The requirements are:

- Each popup follows one figure, the monthly one. Spendable shows `left_to_spend`; Safety Margin shows `safety_margin`. No week, day or next-month-low lists.
- Rows are grouped by local day, newest first. Each day header shows that day's net change.
- Each row shows the time, the cause, the signed change and the balance after it.
- Tapping a row shows "What came in" (the charges and other events) and "How the number moved" (each line of the calculation, before and after, ending in the figure itself).
- The top shows the current figure and "down $X since <date>, from $Y", measured from the oldest update shown. Older days load behind "Show earlier days".
- A note says times are when the app noticed the change, not when the charge happened.
- Whether a charge was planned is out of scope.

## Global Constraints

- Public repo: no real figures in code, tests, docs or commit messages. Synthetic numbers only.
- Read `docs/architecture.md` first (project rule). No figure's meaning changes, so `CALC_VERSION` stays as it is.
- No model changes and no new tables.
- The frontend does no money math (`frontend/tests/moneyGuard.test.ts`). Every subtotal and difference comes from the backend. Do not add allowlist entries.
- Money in UI text uses the app's shape: `$1,234.56`, negative with U+2212 `−`. Signed changes: `+$50.00` / `−$400.00`.
- Every amount must mask when balances are hidden, including running balances, day subtotals, the top line and math lines.
- Phone width of about 400px must work.
- Python via `uv run --locked`; frontend via `bun`/`bunx` only.
- Commits go straight to `main`. Do not push; pushing waits for Dan's OK.
- Gate before calling a task done: `uv run --locked ruff check .`, `uv run --locked pytest backend/tests -q`, and for frontend work `cd frontend && bun test && bunx vite build`. After the final task: `graphify update .`.

## Review Focus

1. **A stored receipt that can't be read.** Expect the row to still list with its change and balance, headline "Inputs changed", and no math section. Test: Task 1 `test_statement_unreadable_receipt_has_no_math`.
2. **A change just before local midnight** (11:30 PM Eastern is the next day in UTC). Expect it under the local day. Test: Task 1 `test_statement_groups_by_local_day`.
3. **Hide balances on with a row open.** Expect no digit from any amount, including "→ balance" and the top line. Test: Task 2 `hidden mode masks statement figures`.
4. **The period nets to zero.** Expect "no net change since <date>", never "up $0.00". Test: Task 2 `periodLine says no net change`.
5. **A calculation line that exists on only one side** (a line added or removed between readings). Expect "added" or "removed" wording, not a blank or `$0.00` side. Tests: Task 1 `test_math_lines_line_on_one_side`, Task 2 `mathFigures words a one-sided line`.

---

### Task 1: The statement endpoint

**Files:**
- Modify: `backend/schemas.py` (after `MetricHistoryOut`)
- Modify: `backend/services/metric_diff.py`
- Modify: `backend/routers/history.py`
- Modify: `docs/architecture.md` ("How the change history works")
- Test: `backend/tests/test_history_statement.py` (create; import `_user`, `_client`, `_snap`, `_sources`, `_explain`, `_pinned_zone` from `test_history_api.py`)

**Interfaces:**
- Produces, in `schemas.py`:
  - `HistoryMathPart`: `label: str`, `delta: Decimal`
  - `HistoryMathLine`: `label: str`, `old: Optional[Decimal]`, `new: Optional[Decimal]`, `parts: list[HistoryMathPart] = []`
  - `HistoryStatementRow`: `taken_at: datetime`, `delta: Decimal`, `old_value: Decimal`, `new_value: Decimal`, `headline: str`, `events: list[HistoryCause]`, `math: list[HistoryMathLine]`
  - `HistoryStatementDay`: `day: date`, `delta: Decimal`, `rows: list[HistoryStatementRow]`
  - `HistoryStatementOut`: `metric_key: str`, `label: str`, `current_value: Decimal`, `period_delta: Optional[Decimal]`, `period_from: Optional[Decimal]`, `period_since: Optional[datetime]`, `days: list[HistoryStatementDay]`, `has_more: bool`
- Produces, in `metric_diff.py`:
  - `math_lines(old: schemas.Explanation, new: schemas.Explanation) -> list[schemas.HistoryMathLine]`
  - `statement_headline(causes: list[Cause]) -> str`
  - `statement_for(db: Session, user_id: int, newest: models.MetricReading, max_days: int) -> schemas.HistoryStatementOut`
- Produces the route `GET /history/{metric_key}/statement?days=` (`days`: default 7, `ge=1`, `le=90`). `days` counts days that had a change, not calendar days.

- [ ] **Step 1: Write the failing tests** in `backend/tests/test_history_statement.py`. Build receipts with `ExplainBuilder`-shaped rows and invented figures:

```python
def test_math_lines_sign_subtracted_rows_and_add_up():
    # old: start "Low" 2000, subtract "Bills" 800 -> 1200
    # new: start "Low" 1900, subtract "Bills" 800 -> 1100
    lines = math_lines(old, new)
    assert [(l.label, l.old, l.new) for l in lines] == [
        ("Low", D("2000"), D("1900")), ("Bills", D("-800"), D("-800"))]
    assert sum(l.new for l in lines) == D("1100")

def test_math_lines_skip_result_and_divide_rows(): ...
def test_math_lines_line_on_one_side():
    # a row only in new -> old is None; a row only in old -> new is None
def test_math_lines_parts_are_the_changed_children():
    # "Low" has informational child "Card estimate" -100 -> -160
    # lines[0].parts == [HistoryMathPart(label="Card estimate", delta=D("-60"))]
    # an unchanged child is not listed

def test_statement_headline_drops_line_causes_when_an_event_exists():
    # [grouped "new pending Visa charge", line cause short "Low changed"]
    assert statement_headline(causes) == "New pending Visa charge"
def test_statement_headline_uses_the_line_when_no_event(): ...  # "Low changed"

def test_statement_rows_carry_change_and_balance(db_session):
    # readings 500 -> 450 -> 475: newest row delta +25, old_value 450, new_value 475
def test_statement_day_delta_is_the_days_net(db_session):
    # two changes on one local day: -50 and +25 -> day delta -25
def test_statement_groups_by_local_day(db_session):
    # taken_at 2026-11-03 04:30 UTC is Nov 2, 11:30 PM Eastern -> day == date(2026, 11, 2)
def test_statement_period_measures_from_oldest_shown(db_session):
    # readings 1000, 900 (day 1), 850 (day 2), 800 (day 3); days=2
    # period_from == 900, period_delta == -100, period_since == day 2's taken_at, has_more True
def test_statement_max_days_counts_days_with_changes(db_session):
    # an unchanged reading on a day between two changes does not use up a day
def test_statement_no_changes_is_empty(db_session):
    # one reading: days == [], period_* None, has_more False
def test_statement_unreadable_receipt_has_no_math(db_session):
    # explain_json="not json" on one side: row kept, headline "Inputs changed", math == [], events == []
def test_statement_events_exclude_line_causes(db_session):
    # a pending charge and a moved receipt line: events only has the grouped cause
def test_statement_route_unknown_key_is_404(db_session): ...
def test_statement_route_bad_key_is_422(db_session): ...
def test_statement_route_is_scoped_to_the_caller(db_session): ...  # another user's readings 404
```

Add `("get", "/history/leftover/statement")` to the login-required parametrize list in `test_history_api.py`, in the shape that list already uses.

- [ ] **Step 2: Run them.** `uv run --locked pytest backend/tests/test_history_statement.py -q`. Expected: FAIL on the missing imports.

- [ ] **Step 3: Add the schemas, then implement in `metric_diff.py`.**
  - `math_lines`: pair rows with `_rows` (so `result` and `divide` stay out, and order matches `diff_explanations`). Report a `subtract` row's amount negated. `parts` are the changed children from `_kids`; move the child comparison in `diff_explanations` into a helper both functions call, with no change to its output.
  - `statement_headline`: events are causes with no `short`. Return `headline(events)` when there are any, else `headline(causes)`.
  - `statement_for`: walk readings newest first as `changes_for` does and skip pairs that moved less than a cent. Group by local day, using a `_local(t)` helper pulled out of `_since_text`. Stop explaining once a change would start day `max_days + 1`, and set `has_more`. `events` are the causes with no `short`, minus `_NOTHING_NAMED`. Build `math` inside a `try` catching the same exceptions as `_causes_or_fallback`, falling back to `[]`. `period_from` is the oldest shown change's old value, `period_delta` is the newest new value minus `period_from`, and `period_since` is the oldest shown change's `taken_at`.
  - Route: same `KEY_PATTERN`, auth and 404 as `metric_history_for`.

- [ ] **Step 4: Run them.** Same command. Expected: PASS. Then the full backend suite and ruff. Expected: PASS. If `test_calc_guard.py` flags the new subtraction, follow that test's instructions for a shared-layer module.

- [ ] **Step 5: Document it.** Add a short paragraph on the statement route to "How the change history works" in `docs/architecture.md`.

- [ ] **Step 6: Commit.** `git add backend/schemas.py backend/services/metric_diff.py backend/routers/history.py backend/tests/test_history_statement.py backend/tests/test_history_api.py docs/architecture.md docs/superpowers/plans/2026-11-10-what-changed-statement.md` · `git commit -m "feat(history): statement endpoint with running balances and before/after math"`

---

### Task 2: The statement popup

**Files:**
- Modify: `frontend/src/api/index.ts`
- Modify: `frontend/src/lib/historyMoney.ts`
- Modify: `frontend/src/components/WhatChanged.tsx`
- Modify the callers: `frontend/src/pages/Dashboard.tsx`, `frontend/src/pages/CreditCards.tsx`, `frontend/src/components/RecurringSummaryStrip.tsx`, `frontend/src/components/CheckingBalancesCard.tsx`
- Modify: `docs/USER_GUIDE.md` (only if it describes this popup)
- Test: `frontend/tests/historyMoney.test.ts`

**Interfaces:**
- Consumes: the Task 1 route and schemas. Decimals arrive as strings, dates as ISO strings.
- Produces:
  - `historyApi.statement(key: string, days: number): Promise<HistoryStatement>`, with TypeScript types mirroring the Task 1 schemas. Remove `historyApi.changes` and the `MetricChange` and `MetricHistory` types if nothing else imports them.
  - `historyMoney.ts`: `periodLine(hidden: boolean, delta: string, from: string, since: string): string`, `dayLabel(day: string, today: Date): string`, `mathFigures(hidden: boolean, old: string | null, next: string | null): string`
  - `WhatChanged` props become `{ metric: { key: string; title: string } }`.

- [ ] **Step 1: Write the failing tests** in `frontend/tests/historyMoney.test.ts`:

```ts
test("periodLine words a fall and a rise", () => {
  expect(periodLine(false, "-906.00", "2000.00", "Nov 7")).toBe("down $906.00 since Nov 7, from $2,000.00");
  expect(periodLine(false, "50.00", "100.00", "Nov 7")).toBe("up $50.00 since Nov 7, from $100.00");
});
test("periodLine says no net change", () => {
  expect(periodLine(false, "0.00", "100.00", "Nov 7")).toBe("no net change since Nov 7");
});
test("dayLabel names today and reads the date as local", () => {
  const today = new Date(2026, 10, 10);
  expect(dayLabel("2026-11-10", today)).toBe("Today, Nov 10");
  expect(dayLabel("2026-11-09", today)).toBe("Mon, Nov 9");
});
test("mathFigures shows before and after, or says no change", () => {
  expect(mathFigures(false, "2032.00", "1894.00")).toBe("$2,032.00 → $1,894.00");
  expect(mathFigures(false, "-800.00", "-800.00")).toBe("−$800.00, no change");
});
test("mathFigures words a one-sided line", () => {
  expect(mathFigures(false, null, "25.00")).toBe("added, $25.00");
  expect(mathFigures(false, "25.00", null)).toBe("removed, was $25.00");
});
test("hidden mode masks statement figures", () => {
  expect(periodLine(true, "-906.00", "2000.00", "")).not.toMatch(/\d/);
  expect(mathFigures(true, "2032.00", "1894.00")).not.toMatch(/\d/);
});
```

- [ ] **Step 2: Run them.** `cd frontend && bun test tests/historyMoney.test.ts`. Expected: FAIL on the missing exports.

- [ ] **Step 3: Implement the three helpers.** Compose them from `signedMoney` and `sameFigure`, with no arithmetic. `dayLabel` must build the date from its parts, because `new Date("2026-11-09")` reads as UTC and lands on the wrong day.

- [ ] **Step 4: Rewrite `WhatChanged.tsx`** to match mockup A, keeping the Radix dialog and trigger button:
  - Title `{title} history`, then `current_value` large, then `periodLine` when there is a period.
  - One block per day: `dayLabel` left, the day's signed `delta` right.
  - Each row: local time, `maskMoneyText(hidden, headline)`, signed `delta` (green for a rise, red for a fall, the sign always shown), `→ new_value` beneath.
  - A row expands only when it has grouped events or math lines. Track open rows by `taken_at`, not index, because the list grows.
  - Open row: "What came in" lists each event (a grouped event's head and items, or a plain event's text). "How the number moved" lists each math line with `mathFigures`, its `parts` indented with signed deltas, then a bold total line using the popup's title and `mathFigures(old_value, new_value)`. Hide a section that would be empty.
  - "Show earlier days" appears when `has_more` and raises `days` by 7, keeping the current list on screen while it loads.
  - Footer note: "Times are when the app noticed the change, not when the charge happened."
  - Keep the loading, error and "No changes recorded yet." states, and the 404 handling.

- [ ] **Step 5: Update the callers.** The Spendable popup becomes `metric={{ key: "left_to_spend", title: "Spendable this month" }}` and the Safety Margin popup becomes `metric={{ key: "safety_margin", title: "Safety Margin (month)" }}`. Every other caller passes its single entry as `metric`.

- [ ] **Step 6: Run the gate.** `cd frontend && bun test && bunx vite build`. Expected: PASS, with `moneyGuard` clean and no new allowlist entries.

- [ ] **Step 7: Check it in a real browser** using the Interceptor skill at desktop width and about 400px wide: open the Safety Margin popup, expand a row, press "Show earlier days", and turn on hide balances. Expected: no console errors, no horizontal scroll, no digits from amounts while hidden. Do not paste real figures into any report.

- [ ] **Step 8: Commit, then refresh the graph.** `git add frontend/src frontend/tests/historyMoney.test.ts docs/USER_GUIDE.md` · `git commit -m "feat(history): show what changed as a running statement of the monthly figure"` · `graphify update .`
