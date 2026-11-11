# Plan: WhatChanged popup clarity fixes (math-table noise + duplicate headline)

**Repo convention:** commit directly to `main`, no branches/worktrees. Pre-push hook re-runs backend + frontend suites and `bunx vite build`.

## Context

Live-inspected the "What changed?" popup (WhatChanged.tsx / `/history/{key}/statement`)
via Interceptor against the running app. Found two concrete, confirmed clarity
problems (two others are tracked separately — one is parked pending a product
decision, see below):

1. **The math table always lists unchanged lines.** `math_lines()`
   (backend/services/metric_diff.py) returns every receipt row from both
   readings, never filtered by whether the row actually moved. In practice,
   almost every expanded row shows "Income this month: no change",
   "Recurring bills this month: no change", "One-offs this month: no change"
   — three lines that essentially never move within a day — pushed above the
   one line that actually did. Confirmed live: every expanded row in a real
   popup showed this exact pattern.

2. **Expanding a grouped row repeats its own headline.** The collapsed row
   title (`statement_headline`) is always derived from the FIRST event cause's
   `.head` when one exists (e.g. "New pending Test Visa charges"). When
   you expand the row, "What came in" shows that identical group again as its
   own bullet header before finally listing the real items (merchant names).
   Confirmed live: a real expanded row showed "New pending Test Visa
   charges" as both the row title AND the first line under "What came in",
   with the two merchants only appearing after that repeated sentence.

   Related, same root cause: a single-item group's collapsed headline never
   names the item (e.g. "New pending Test Visa charge" rather than
   "...: Example Coffee Co"), so several same-shaped rows across
   different days/times (all titled "New pending Test Visa charge(s)")
   are indistinguishable without expanding each one.

**Out of scope / parked:** a third issue (collapsed headlines like "Checking
spending changed" carry zero information until expanded) traces to
`headline()` preferring `Cause.short` (the amount-stripped generic form) over
`.text` (which carries the real amount, when available) at
backend/services/metric_diff.py:470. Flipping that preference was considered,
but `backend/tests/test_metric_diff.py::test_line_cause_headline_has_no_amount`
(line 532) explicitly, by name, asserts a headline never carries a dollar
amount — a deliberate design invariant, not incidental test fragility. This
plan does not touch `headline()`'s preference order or that test; it is a
product-design question, parked pending Dan's explicit call (see the parent
session's message to Dan).

## Global Constraints

- `uv run --locked pytest backend/` and `uv run --locked ruff check .` pass
  for the backend task. `bunx vite build` succeeds and
  `bun test` passes for the frontend task (per this repo's established
  frontend gate — no `tsc -b`, 35 pre-existing TS errors are tracked debt).
- Do not touch `headline()`'s selection order (`first.head or first.short or
  first.text`) or `test_line_cause_headline_has_no_amount` — that invariant
  is explicitly out of scope for this plan (see Context).
- Do not touch the email's "what changed" section
  (`backend/services/summary_generator.py` `_reasons()`/`_changes_section()`)
  — already fixed in a separate, already-merged plan
  (2026-11-11-email-whatchanged-vague-causes.md) and not implicated here.
- Commit directly to `main` once each task's review is clean.

## Task 1 — Drop unchanged lines from the math table

**File:** `backend/services/metric_diff.py` (`math_lines`), plus
`backend/tests/test_history_statement.py`, `backend/tests/test_history_api.py`.

1. In `math_lines()` (around line 147-163), after building each
   `HistoryMathLine`, skip it when **all** of the following hold: `before` and
   `after` are both not `None` (the row exists on both sides — a one-sided
   added/removed line is never skipped), the signed old and new amounts are
   equal, and `parts` is empty (no child line changed under it either — a row
   whose own net is unchanged but whose children shifted, e.g. two offsetting
   informational children, must still be kept). Concretely: compute `old =
   _signed(before)`, `new = _signed(after)` as the function already does, and
   `continue`/skip appending the line when `before is not None and after is
   not None and old == new and not parts`.

2. **Existing tests that must be updated** (their current expectations
   encode the OLD unfiltered behavior and will fail once the filter is in
   place — this is expected and correct, not something to work around):

   - `test_math_lines_skip_result_and_divide_rows`
     (`backend/tests/test_history_statement.py` ~line 53): currently calls
     `math_lines(old, old)` (same receipt both sides) and asserts `["Low"]`.
     Change `new` to a receipt where `Low` actually differs (e.g.
     `_row("start", "Low", "750")` instead of `"700"`, keeping the same
     `divide`/`result` rows), and assert `[ln.label for ln in
     math_lines(old, new)] == ["Low"]` — this still proves `divide`/`result`
     rows are excluded via `SKIPPED_OPS`, now alongside a real change on
     `Low` rather than relying on the no-change filter being absent.

   - `test_math_lines_line_on_one_side`
     (`backend/tests/test_history_statement.py` ~line 58): currently asserts
     `[("Low", D("100"), D("100")), ("Gone", D("30"), None), ("Fresh", None,
     D("20"))]`. `Low` is unchanged (100→100, no parts) so it is now
     correctly dropped. Update the expected list to just `[("Gone", D("30"),
     None), ("Fresh", None, D("20"))]`.

   - `test_statement_rows_carry_change_and_balance`
     (`backend/tests/test_history_statement.py` ~line 99): this test's
     `row.headline` assertion (`"Base changed"`) is untouched by this task
     (that's the parked `headline()` question) — do not change it. Only
     touch this test if, after your `math_lines` change, running it reveals
     an unrelated failure; if it still passes unchanged, leave it alone.

   - `test_history_api.py` has no `math_lines`-dependent assertions needing
     a change for this task — leave it alone unless a test run says
     otherwise.

3. **New regression test** (add near the other `math_lines` tests in
   `test_history_statement.py`): a line whose own old/new values are equal
   (no net change) but whose children changed (e.g. `_row("start", "Low",
   "1000", kids=[("A", "100"), ("B", "200")])` to `_row("start", "Low",
   "1000", kids=[("A", "150"), ("B", "150")])` — `Low` stays 1000→1000 but
   `A`/`B` shift by +50/-50) is still present in `math_lines()`'s output,
   with non-empty `parts`. This is the exception the filter must respect.

4. Also add a regression test confirming a genuinely unchanged line with NO
   parts (e.g. two identical `_row("start", "Flat", "500")` rows on both
   sides, no kids/info) is absent from `math_lines()`'s output — the direct
   positive-case test for the new behavior itself, not just the updated
   pre-existing tests.

**Verification:** `uv run --locked pytest backend/tests/test_history_statement.py backend/tests/test_history_api.py backend/tests/test_metric_diff.py -q`, then the full backend suite and `ruff check .`.

## Task 2 — Stop repeating a row's headline inside its own expansion; name a single-item group

**Files:** `frontend/src/lib/historyMoney.ts`, `frontend/tests/historyMoney.test.ts`, `frontend/src/components/WhatChanged.tsx`.

1. In `frontend/src/lib/historyMoney.ts`, add a new pure function:

   ```ts
   import type { HistoryCause } from "../api";

   export function displayHeadline(headline: string, events: HistoryCause[]): string {
     if (events.length === 1 && events[0].items.length === 1) {
       return `${headline}: ${events[0].items[0].name}`;
     }
     return headline;
   }
   ```

   `HistoryCause` and `HistoryCauseItem` are already exported from
   `frontend/src/api/index.ts` (`HistoryCause { text, amount, head, items:
   HistoryCauseItem[] }`, `HistoryCauseItem { name, amount }`) — import the
   type from there, don't invent a new shape or redefine it locally. The
   function is intentionally narrow: it only
   adds the item's name when there is exactly one event with exactly one
   item in it (the common "a single new pending charge" case) — it does not
   touch the multi-item or multi-event cases, and it does not add an amount
   (amounts stay in the expanded detail only, consistent with headlines
   never carrying a dollar figure — see this plan's parked Context note).

2. In `frontend/tests/historyMoney.test.ts`, add tests for `displayHeadline`:
   - one event, one item → headline gets `": <name>"` appended
   - one event, two items → headline unchanged
   - two events (each with items) → headline unchanged
   - zero events → headline unchanged

3. In `frontend/src/components/WhatChanged.tsx`:
   - In the `Statement` component's row button (around the `maskMoneyText(hidden, r.headline)` call, ~line 157), replace `r.headline` with `displayHeadline(r.headline, r.events)`, importing `displayHeadline` from `../lib/historyMoney`.
   - In `RowDetail` (around lines 34-66), in the `row.events.map((k, ki) => ...)` loop, suppress rendering the group's own head line for `ki === 0` specifically — render only its `items` sub-list for that first event (still inside the "What came in" section), while rendering every subsequent event (`ki >= 1`) exactly as today, head line and all. Add a one-line comment explaining why: the row's own collapsed headline is always derived from `events[0]`'s head (see `statement_headline` in metric_diff.py), so repeating it here says nothing new — only `events[1:]` (the "+ N more" causes) are genuinely new information when expanded.
   - Do not change anything else in this file (do not touch the "How the number moved" rendering, the day grouping, or anything outside these two spots).

**Verification:** no component-test infra exists in this repo for `.tsx` files (all existing `frontend/tests/*.test.ts` are pure-function tests) — do not introduce one for this task. `bun test` (covers the new `displayHeadline` tests) and `bunx vite build` must both pass. Additionally, describe in your report exactly what you changed in the JSX loop (the `ki === 0` branch) precisely enough that a reviewer can trace it against the diff without running the app.

## Commit messages

Describe the behavior change in plain terms (the popup no longer pads every expanded row with lines that didn't change, and no longer repeats a group's own name as its first sub-item). No real balances/amounts/dates from Dan's actual data — invented example text only (this repo is public).
