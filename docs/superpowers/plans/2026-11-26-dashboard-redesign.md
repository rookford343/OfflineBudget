# Dashboard Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Household Snapshot the calm, full-width hero of the Dashboard. Safety Margin leads, Spendable is secondary, and a 3-month weekly-low chart sits below them. Add a single "Needs attention" strip and a slate + teal palette with light and dark values.

**Architecture:**
- **Backend.** One read-only field, `weekly_lows`, sliced from the same `display_window` walk that already produces `lookahead_minimum`.
- **Frontend palette.** Named CSS-variable colors in `index.css`, exposed through Tailwind. A temporary `indigo` → teal alias covers pages not yet converted.
- **Frontend components.** New components: `SnapshotHero`, `WeeklyLowsChart` and `NeedsAttention`. Their pure logic lives in `lib/` with `bun:test` coverage.

**Tech Stack:** FastAPI, Pydantic, pytest (uv); React 19, TypeScript, Tailwind 3 (`darkMode: "class"`), TanStack Query, `bun:test`, `react-dom/server` for static-render tests.

**Spec:** `docs/superpowers/specs/2026-11-25-dashboard-redesign-design.md`. Read it, including "Calls made after the builder check".

## Global Constraints

**Money calcs**
- No money calculation changes. Read `docs/architecture.md` before touching `backend/services/budget_snapshot.py`.
- `weekly_lows` reads `display_window` only, never Safety Margin's `lookahead_window`.

**Colors**
- A week's bar is `danger` below $0 and `warning` below the cushion. Statuses come from `cushion_status` (`backend/services/cushion.py`) and are never recomputed in the frontend.
- The Safety Margin figure is `ink` at $0 or above and red below $0. It has no amber state.
- On the chart, status color wins over `accent`. `accent` marks the lowest bar only when that bar's status is `ok`. Ties go to the earliest bucket.

**Masking**
- Every amount goes through `useBalancesHidden()` with `maskIfHidden` (`store/balanceVisibility.ts`) or `maskMoneyText` (`lib/maskMoney.ts`).
- With balances hidden, no amount renders anywhere: text, chart tooltips, axis labels, `title`, or `aria-label`.

**Palette values (verbatim from the spec)**

| Token | Light | Dark |
|---|---|---|
| surface | `#f8fafc` | `#0b1220` |
| card | `#ffffff` | `#131c2e` |
| ink | `#0f172a` | `#e2e8f0` |
| muted | `#64748b` | `#94a3b8` |
| line | `#e2e8f0` | `#22304a` |
| bar | `#cbd5e1` | `#334155` |
| accent | `#0f766e` | `#2dd4bf` |
| accent-strong | `#0f766e` | `#0f766e` |
| warn | `#d97706` | `#f59e0b` |
| warn-text | `#92400e` | `#fcd34d` |
| warn-figure | `#b45309` | `#fbbf24` |
| warn-bg | `#fef3c7` | `#2a1a06` |
| warn-line | `#fde68a` | `#5a3a0e` |

**Accessibility**
- Contrast is WCAG AA: 4.5:1 for body text, 3:1 for text 24px+ or 19px+ bold.
- Body text is at least 13px.
- Phone tap targets are at least 44px.

**Tooling**
- Frontend uses `bun` only: `cd frontend && bun test`, plus `bunx vite build`, which must succeed. Do not use `tsc -b`, which has 35 known pre-existing errors.
- Backend uses uv only: `uv run --locked pytest backend/tests/<file> -q` and `uv run --locked ruff check .`.

**Live data**
- The dev backend runs `uvicorn --reload` against the real DB. Before the first backend commit, the controller runs `backup_database()`. Implementers never touch `backend/budget.db`.
- No migrations.

**Repo**
- Public repo. Tests, fixtures and commit messages use made-up amounts only.
- Commit directly to `main` and do not push.
- End every commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A week where every day is masked by `floor_mask`.** Expected: the bucket has `amount: null` and renders as a gap. It must not be treated as $0, which would read as "below cushion". Pinned in Task 1 and Task 5.
2. **Balances hidden while hovering or tapping a bar.** Expected: the tooltip shows the week and date with `••••••`, and the `aria-label` carries no digits. Pinned in Task 5.
3. **A ±$0.00 boundary.** Safety Margin of exactly 0 is `ink`, not red. A week low exactly at the cushion is `ok`, matching `cushion_status`. Pinned in Task 1 and Task 5.
4. **A typed transfer amount, then "Hide balances" toggled on.** Expected: the typed value is dropped and Accept uses the backend suggestion. The hint "Show balances to edit the amount" is visible text. Pinned in Task 3.
5. **Snapshot without `weekly_lows`.** This covers an older cached response or an empty walk. Expected: the hero renders without the chart and does not crash. Pinned in Task 5.

---

### Task 1: Backend: `weekly_lows` on the budget snapshot

**Files:**
- Modify: `backend/services/budget_snapshot.py`. Add `_weekly_lows`, and set the field where `BudgetSnapshot(...)` is built, around line 880–905, next to `lookahead_minimum=display_min`.
- Modify: `backend/schemas.py`. Add the `WeeklyLow` model near `BudgetSnapshot` (line 2196), and add the field `weekly_lows: list[WeeklyLow] = []` with a comment.
- Test: create `backend/tests/test_weekly_lows.py`.

**Interfaces:**
- Produces, Python side: `WeeklyLow(BaseModel)` with these fields:
  - `start: date`
  - `end: date` (inclusive)
  - `amount: Optional[Decimal]` (`None` when every day in the bucket is masked)
  - `date: Optional[date]` (the day of the low)
  - `status: Literal["ok", "warning", "danger"]` (`"ok"` when `amount` is None)
- Produces, Python side: `_weekly_lows(window: LookaheadWindow, as_of: date, cushion: Decimal) -> list[WeeklyLow]`.
- Produces, JSON side: `snapshot.weekly_lows` is an array of these objects. Decimals serialize as strings, the same as the other snapshot money fields.

**Behavior:**
- Buckets are rolling 7-day ranges: `[as_of, as_of+6]`, `[as_of+7, as_of+13]`, and so on.
- The last bucket ends at the last day in `window.days` and may be shorter than 7 days.
- Days before `as_of` are ignored.
- Within a bucket, the low is the minimum `projected_balance` over days whose mask is `True`. Ties go to the earliest day.
- A bucket with no unmasked day gets `amount=None` and `date=None`.
- An empty `window.days` produces `[]`.

- [ ] **Step 1: Write the failing tests** in `backend/tests/test_weekly_lows.py`.
  - The unit tests build `LookaheadWindow(minimum=..., minimum_date=..., days=[...], mask=[...])` with days as `SimpleNamespace(date=..., projected_balance=Decimal(...))`. Fixtures use made-up amounts.
  - `test_buckets_are_rolling_weeks_from_as_of`:
    - Setup: as_of 2026-03-20 with 20 daily days from 03-20 to 04-08.
    - Assert 3 buckets with starts 03-20, 03-27 and 04-03, and ends 03-26, 04-02 and 04-08.
  - `test_short_last_bucket`:
    - Setup: 9 days.
    - Assert 2 buckets, with the second ending on day 9.
  - `test_days_before_as_of_ignored`:
    - Setup: a day on 03-19 with balance -999.
    - Assert no bucket includes it and no amount is -999.
  - `test_masked_days_excluded`:
    - Setup: the lowest day in bucket 1 has mask False.
    - Assert bucket 1's amount is the next-lowest unmasked balance.
  - `test_all_masked_bucket_is_gap`:
    - Setup: every day in bucket 2 is masked.
    - Assert `amount is None`, `date is None` and `status == "ok"`.
  - `test_status_uses_cushion_status`:
    - Setup: cushion 1000; bucket lows of 1000.00, 999.99, -0.01 and 0.00.
    - Assert the statuses are ok, warning, danger and warning.
  - `test_tie_goes_to_earliest_day`:
    - Setup: two equal lows in one bucket.
    - Assert `date` is the earlier one.
  - `test_min_of_buckets_equals_lookahead_minimum`:
    - Integration test. Reuse the `_scenario(db, monkeypatch)` fixture pattern from `backend/tests/test_snapshot_display_low_matches_forecast.py` (copy it, don't import private test helpers), then call `compute_budget_snapshot`.
    - Let `non_null = [w for w in snap.weekly_lows if w.amount is not None]`.
    - Assert `min(w.amount for w in non_null) == snap.lookahead_minimum`.
    - Assert that the earliest bucket holding that amount has `date == snap.lookahead_minimum_date`.
    - Assert `snap.weekly_lows[0].start == TODAY`.

- [ ] **Step 2: Run the tests and confirm they fail.**
  Run: `uv run --locked pytest backend/tests/test_weekly_lows.py -q`. Expected: FAIL, with an ImportError or AttributeError on `_weekly_lows` or `WeeklyLow`.

- [ ] **Step 3: Implement** `WeeklyLow` in `schemas.py`, and `_weekly_lows` in `budget_snapshot.py` using `cushion_status`. In `compute_budget_snapshot`, pass `weekly_lows=_weekly_lows(display_window, as_of, safety_cushion)`. Add a short comment that it slices `display_window` so the lowest bar equals `lookahead_minimum`.

- [ ] **Step 4: Run the new tests plus the snapshot suites and confirm they pass.**
  Run: `uv run --locked pytest backend/tests/test_weekly_lows.py backend/tests/test_budget_snapshot.py backend/tests/test_snapshot_display_low_matches_forecast.py backend/tests/test_safety_cushion.py -q`. Expected: all pass.

- [ ] **Step 5: Prove the guard can fail.**
  - Temporarily change `_weekly_lows` to ignore the mask.
  - Confirm `test_masked_days_excluded` fails.
  - Restore the mask. Note this in the report.

- [ ] **Step 6: Lint and import check.**
  Run: `uv run --locked ruff check . && uv run --locked python -c "import backend.main, cli.budget"`. Expected: clean.

- [ ] **Step 7: Commit:** `feat: add weekly lows to the budget snapshot`.

---

### Task 2: Palette: named colors, dark values, indigo alias, shared components

**Files:**
- Modify: `frontend/src/index.css`.
  - Add `:root { --c-surface: …; … }` and `.dark { … }`, using the Global Constraints table with names `--c-<token>`.
  - Convert `html`, `body`, `.card`, `.btn-primary`, `.btn-secondary`, `.btn-ghost` and `.input` to the named colors.
  - Remove the old hard-coded dark hexes in those rules, such as `#2a2f3d` and `#c4ccd8`.
- Modify: `frontend/tailwind.config.js`.
  - Add `theme.extend.colors` entries: `surface`, `card`, `ink`, `muted`, `line`, `bar`, `accent`, `accent-strong`, `warn`, `warn-text`, `warn-figure`, `warn-bg` and `warn-line`, each as `"var(--c-<token>)"`.
  - Add a temporary `indigo` override (see Step 3).
  - Keep `income`, `expense`, `warning` and `projected`.
- Modify: `frontend/src/components/Layout.tsx` and `frontend/src/components/MoreSheet.tsx`. Replace `indigo-*`, gradients and gray surfaces with the named colors: `text-accent` for active nav, `bg-surface`, `border-line`, `text-muted`.
- Create: `frontend/src/theme/contrast.ts`, exporting `contrastRatio(hexA: string, hexB: string): number` (WCAG relative luminance).
- Create: `frontend/src/theme/palette.test.ts`.

**Interfaces:**
- Produces: Tailwind classes `bg-surface`, `bg-card`, `text-ink`, `text-muted`, `border-line`, `bg-bar`, `text-accent`, `bg-accent`, `bg-accent-strong`, `text-warn-text`, `text-warn-figure`, `bg-warn`, `bg-warn-bg` and `border-warn-line`. They switch with `.dark` automatically, so no `dark:` variant is needed for these.
- Produces: `contrastRatio` for later tasks' tests.

- [ ] **Step 1: Write the failing test** `palette.test.ts`.
  - Read `src/index.css` with `Bun.file`. Parse the `--c-*` values in the `:root` block and the `.dark` block.
  - Assert every token in the Global Constraints table exists in both blocks with the exact hex.
  - Assert `contrastRatio` meets these minimums in each theme:
    - ≥ 4.5 for ink/card, muted/card, muted/surface, accent/card, warn-text/card, warn-text/warn-bg, and `#ffffff`/accent-strong
    - ≥ 3.0 for warn-figure/card, as large text
  - Read `tailwind.config.js` as text. Parse the indigo override map, then assert:
    - indigo 600 and 700 on `#ffffff` are ≥ 4.5;
    - indigo 300 and 400 on `#131c2e` are ≥ 4.5.

- [ ] **Step 2: Run it and confirm it fails.**
  Run: `cd frontend && bun test src/theme/palette.test.ts`. Expected: FAIL, because the variables are missing.

- [ ] **Step 3: Implement.**
  - The indigo alias is a full 50–950 teal scale, chosen so the Step 1 contrast assertions pass. A good starting point is Tailwind's teal scale shifted one step darker for 500–700.
  - Put this comment above it: `// TEMPORARY (2026-11-26 Dashboard redesign): indigo renders as teal until each page swaps indigo-* for the named colors. Follow-up: hard-coded indigo hexes in Spending.tsx, Forecast.tsx, NetWorth.tsx charts. Delete this alias when no indigo-* remains.`

- [ ] **Step 4: Run the tests and the build, and confirm they pass.**
  Run: `cd frontend && bun test && bunx vite build`. Expected: all tests pass and the build succeeds.

- [ ] **Step 5: Prove the guard can fail.**
  - Temporarily set dark `--c-muted` to `#475569`.
  - Confirm the contrast assertion fails.
  - Restore it.

- [ ] **Step 6: Commit:** `feat: add calm slate+teal palette with dark values and temporary indigo alias`.

---

### Task 3: RiskBanner: masking follow-ups, has-content predicate, named colors

**Files:**
- Modify: `frontend/src/store/balanceVisibility.ts`. Export the existing `MASK` as `BALANCE_MASK`; `maskIfHidden` keeps using it.
- Modify: `frontend/src/lib/riskBannerText.ts`. Add these two functions:
  - `riskHasContent(risk: Risk | null | undefined): boolean`, the same condition as today's `if (!risk) return null` plus `!showAlert && !showTransfer && !showSuggestion` in `RiskBanner.tsx:75-97`;
  - `effectiveTransferAmount(hidden: boolean, override: string, suggested: string | null | undefined): string`, which returns `suggested ?? ""` when hidden, otherwise `override || suggested || ""`.
- Modify: `frontend/src/components/RiskBanner.tsx`.
  - Use `riskHasContent` for the early return.
  - Use `effectiveTransferAmount` for the amount.
  - Use `useEffect` to clear `amountOverride` when `hidden` becomes true.
  - Replace the hard-coded `••••••` with `BALANCE_MASK`.
  - When hidden, render the visible hint text "Show balances to edit the amount" next to the masked span. The `title` may stay.
  - Restyle: amber variants use `bg-warn-bg border-warn-line text-warn-text`, danger keeps the red family, and indigo becomes accent.
- Modify: `frontend/src/lib/riskBannerText.test.ts`. Broaden `LEAKS` with the fixture's amounts in no-decimal and thousands-separator forms, such as `"123"`, `"750"`, `"600"`, `"500"` and `"1,234"` (add a 1234.00 fixture field), and assert `/\d/` does not appear where the text carries only amounts.
- Create: `frontend/src/components/RiskBanner.test.tsx`.

**Interfaces:**
- Produces: `riskHasContent(risk)` (used by Task 4), `effectiveTransferAmount(...)`, and `BALANCE_MASK`.

- [ ] **Step 1: Write the failing tests.**
  - `riskBannerText.test.ts`:
    - `riskHasContent` is `false` for null, and for a risk that has no alert, transfer or suggestion.
    - `riskHasContent` is `true` for each of the three.
    - `effectiveTransferAmount(true, "999", "600.00") === "600.00"`.
    - `effectiveTransferAmount(false, "999", "600.00") === "999"`.
    - `effectiveTransferAmount(false, "", "600.00") === "600.00"`.
    - The broadened LEAKS assertions for every headline function with `hidden=true`.
  - `RiskBanner.test.tsx`:
    - Render with `renderToStaticMarkup`, inside a `QueryClientProvider` with a fresh `QueryClient`.
    - Force hidden mode the way `balanceVisibility.ts` reads it. Check how `getBalancesHidden` reads it, and set that source in the test.
    - Use a suggestion risk with made-up amounts.
    - Assert the markup contains `BALANCE_MASK` and the text "Show balances to edit the amount".
    - Assert it contains none of the fixture amounts and no `<input` for the amount field.

- [ ] **Step 2: Run the tests and confirm they fail.**
  Run: `cd frontend && bun test src/lib/riskBannerText.test.ts src/components/RiskBanner.test.tsx`. Expected: FAIL.

- [ ] **Step 3: Implement** the changes listed under Files.

- [ ] **Step 4: Run the full suite and the build, and confirm they pass.**
  Run: `cd frontend && bun test && bunx vite build`. Expected: pass.

- [ ] **Step 5: Prove the guard can fail.**
  - Temporarily make `effectiveTransferAmount` ignore `hidden`.
  - Confirm its test fails.
  - Restore it.

- [ ] **Step 6: Commit:** `fix: close RiskBanner masking gaps and move it onto the calm palette`.

---

### Task 4: "Needs attention" strip

**Files:**
- Modify: `frontend/src/components/PlannedTransferReminder.tsx`. Export `usePlannedTransfersHasContent(): boolean`. It uses the same `useQuery` key `["planned-transfers"]` and the same `status === "pending" || "scheduled"` filter, and the component uses it for its own early return. That makes it a single source.
- Modify: `frontend/src/components/BillsToConfirm.tsx`. Export `useBillsToConfirmHasContent()` (same key `["bills-to-confirm"]`, `length > 0`), used the same way.
- Modify: `frontend/src/components/AmountDrift.tsx`. Export `useAmountDriftHasContent()` (same key `["amount-drift"]`, `length > 0`), used the same way.
- Restyle all three onto the named colors: `warn-*` for warnings, `accent` instead of indigo, and `card`, `line` and `muted` for surfaces.
- Create: `frontend/src/components/NeedsAttention.tsx`.
- Create: `frontend/src/components/NeedsAttention.test.tsx`.

**Interfaces:**
- Consumes: `riskHasContent` from Task 3.
- Produces: `NeedsAttention({ risk }: { risk: Risk | null | undefined }): JSX.Element`.
  - It renders a container labelled "Needs attention" holding `RiskBanner`, `PlannedTransferReminder`, `BillsToConfirm` and `AmountDrift` in that order.
  - When all four have no content, it renders exactly one line, `Nothing needs you today.`, styled `text-muted bg-card border-line`.
  - The container itself is neutral (`bg-card border-line`), and the items carry their own warn styling.

- [ ] **Step 1: Write the failing tests.** Use `renderToStaticMarkup`. Seed the `QueryClient` with `setQueryData` for each key, and stub the fetchers so the test makes no network calls.
  - `quiet when nothing needs action`: all keys hold empty arrays and `risk={null}`. Assert the markup contains `Nothing needs you today.` and does not contain `Needs attention`.
  - `shows items when one has content`: seed one pending planned transfer. Assert the markup contains `Needs attention` and does not contain `Nothing needs you today.`
  - `risk alone counts`: empty arrays and a risk with an alert. Assert the markup contains `Needs attention`.

- [ ] **Step 2: Run the tests and confirm they fail.**
  Run: `cd frontend && bun test src/components/NeedsAttention.test.tsx`. Expected: FAIL.

- [ ] **Step 3: Implement** the hooks and `NeedsAttention`.

- [ ] **Step 4: Run the full suite and the build, and confirm they pass.**
  Run: `cd frontend && bun test && bunx vite build`. Expected: pass.

- [ ] **Step 5: Commit:** `feat: add Needs attention strip with a calm empty state`.

---

### Task 5: Snapshot hero and weekly-lows chart

**Files:**
- Create: `frontend/src/lib/weeklyLows.ts`, holding the pure logic.
- Create: `frontend/src/lib/weeklyLows.test.ts`.
- Create: `frontend/src/lib/lowestBalanceRows.ts`. Move `lowestBalanceRows` and its `LowestBalanceRow` type out of `Dashboard.tsx` (lines ~60–90) unchanged, and export them.
- Create: `frontend/src/components/dashboard/WeeklyLowsChart.tsx`.
- Create: `frontend/src/components/dashboard/SnapshotHero.tsx`.
- Create: `frontend/src/components/dashboard/SnapshotHero.test.tsx`.

**Interfaces:**
- Consumes: `snapshot.weekly_lows` from Task 1 (Decimals arrive as strings), the named colors from Task 2, and `BALANCE_MASK` from Task 3.
- Produces in `lib/weeklyLows.ts`:
  - `type WeeklyLow = { start: string; end: string; amount: string | null; date: string | null; status: "ok" | "warning" | "danger" }`
  - `lowestIndex(lows: WeeklyLow[]): number | null`: the index of the minimum non-null amount, earliest on ties, or `null` if none.
  - `barTone(low: WeeklyLow, isLowest: boolean): "danger" | "warning" | "accent" | "bar" | "gap"`. It returns `"gap"` when `amount` is null; otherwise `danger`/`warning` by status; otherwise `"accent"` if lowest; otherwise `"bar"`.
  - `barLabel(low: WeeklyLow, hidden: boolean): string`. It returns, for example, `Week of Dec 1: low $1,050.00 on Dec 3`, and `Week of Dec 1: low •••••• on Dec 3` when hidden. A gap reads `Week of Dec 1: no forecast low`. It's used for the tooltip, `title` and `aria-label`.
  - `monthTicks(lows: WeeklyLow[]): { index: number; label: string }[]`: the first bucket whose `start` falls in each new month, labelled `"Dec"`.
  - `safetyMarginTone(weekly: number): "ink" | "danger"`: `danger` only when `< 0`.
- Produces in `components/dashboard/`:
  - `WeeklyLowsChart({ lows, hidden }: { lows: WeeklyLow[]; hidden: boolean })`.
    - It renders plain divs: about 48px tall, one bar per bucket, and bar heights scaled between the min and max non-null amounts.
    - Gaps are empty slots. Month ticks sit below the bars. Each bar's `title` and `aria-label` come from `barLabel`.
    - It renders nothing if `lows` is empty.
    - Do not use recharts here.
  - `SnapshotHero({ snapshot, primaryCheckingId, hidden, isWide }: {...})`.
    - It is the full-width hero card (`bg-card border-line`, no gradient), per the spec's "Hero (desktop)" sketch.
    - On wide screens it uses a two-column grid, `grid-cols-[1.4fr_1fr]`.
    - **Safety Margin column:**
      - The figure is `text-4xl` or `text-[40px]`, colored by `safetyMarginTone`, so `text-ink` or red.
      - It keeps the existing `/day` line and "this month" line.
      - When `savings_pull_needed > 0`, it shows a "Pull X from savings" action line in `text-warn-text`.
    - **Spendable column:**
      - The figure is `text-[22px]`, colored `text-ink`.
      - It keeps the existing `/day · on pace|over pace` line, with "over pace" in `text-warn-text`.
      - It keeps the "this month" line.
    - **Chart:** under the label "Checking low point each week · next 3 months".
    - **Caption:** `lowestBalanceRows(snapshot)` rows below the chart, keeping the existing `lookahead_status` warn logic, the "below your … cushion" and "below $0" text, and the "Move … into checking by …" line. Recolor them onto the named colors.
    - **Header and links:** move every existing `HowCalculated`, `WhatChanged` and `VerificationFlagButton` from `Dashboard.tsx:429-534`, keeping the same props.
    - On phone it stacks in a single column.
    - The chart is omitted when `snapshot.weekly_lows` is missing or empty.

- [ ] **Step 1: Write the failing tests.**
  - `weeklyLows.test.ts`:
    - `lowestIndex`: earliest wins on a tie, null amounts are skipped, and an all-null array gives `null`.
    - `barTone`:
      - a lowest `warning` bucket is `"warning"`;
      - a lowest `ok` bucket is `"accent"`;
      - a null amount is `"gap"`, even if lowest is passed;
      - `danger` beats everything else.
    - `barLabel`: hidden output contains `••••••`, no `$`, and no digits from the amount, but keeps the dates. Shown output equals `Week of Dec 1: low $1,050.00 on Dec 3` (fixture amount 1050.00).
    - `monthTicks`: three months of buckets produce 3 or 4 ticks, the first at index 0.
    - `safetyMarginTone`: `0` is `"ink"`, `-0.01` is `"danger"`, and `5` is `"ink"`.
  - `SnapshotHero.test.tsx`, using `renderToStaticMarkup` with a `QueryClientProvider` and a made-up snapshot fixture that includes `weekly_lows`:
    - With `hidden=true`: strip the static strings `below $0`, then assert the markup contains no `$` and no digit sequence from any fixture amount, including in `title` and `aria-label` attributes.
    - `positive Safety Margin is not amber`: the markup for `safety_margin_weekly: "250.00"` contains no `amber` or `warn` class on the figure element (mark the figure with `data-testid="sm-figure"`).
    - `no weekly_lows still renders`: delete `weekly_lows` from the fixture. It renders without throwing and with no chart label.

- [ ] **Step 2: Run the tests and confirm they fail.**
  Run: `cd frontend && bun test src/lib/weeklyLows.test.ts src/components/dashboard/SnapshotHero.test.tsx`. Expected: FAIL.

- [ ] **Step 3: Implement** `lib/weeklyLows.ts`, `lib/lowestBalanceRows.ts`, `WeeklyLowsChart` and `SnapshotHero`. Map tones to classes: `danger` → `bg-red-500 dark:bg-red-400`, `warning` → `bg-warn`, `accent` → `bg-accent`, `bar` → `bg-bar`. Dashboard wiring is Task 6.

- [ ] **Step 4: Run the full suite and the build, and confirm they pass.**
  Run: `cd frontend && bun test && bunx vite build`. Expected: pass.

- [ ] **Step 5: Prove the guard can fail.**
  - Temporarily make `barLabel` ignore `hidden`.
  - Confirm the hidden-mode tests fail.
  - Restore it.

- [ ] **Step 6: Commit:** `feat: add Snapshot hero with weekly-lows chart`.

---

### Task 6: Wire the Dashboard (desktop and phone), retire the old tiles, calm the rest

**Files:**
- Modify: `frontend/src/pages/Dashboard.tsx`.
- Delete: `frontend/src/components/phone/SafetyMarginHero.tsx` and `frontend/src/components/phone/SpendableTile.tsx`. Only `Dashboard.tsx` imports them; confirm with grep before deleting.

**Interfaces:**
- Consumes: `SnapshotHero` and `lowestBalanceRows` (Task 5), and `NeedsAttention` (Task 4).

**Desktop path** (the main return, around line 355 onward):
- Render `SnapshotHero` full width directly after the header and `BankSyncStatusLine`.
- Under it, render `<NeedsAttention risk={weeklyDigest?.risk} />`. It replaces the separate `RiskBanner`, `PlannedTransferReminder`, `BillsToConfirm` and `AmountDrift` lines at ~366–369.
- Remove the Household Snapshot card from the panel grid (~425–534). Adjust that grid so the remaining panels (Available to Spend, Month in Review, Net Position) fill it without an empty slot. One way is to drop the 4-column `2xl` template to three columns, `2xl:grid-cols-[0.85fr_1.15fr_0.85fr]`.

**Phone path** (~297–325):
- Replace `SafetyMarginHero` and `SpendableTile` with `SnapshotHero` (`isWide={false}`).
- Then render the "+ Plan a one-off" button (`min-h-[44px]`, unchanged), then `<NeedsAttention risk={weeklyDigest?.risk} />`, replacing the four separate lines.

**Rest of the page:**
- Remove `bg-gradient-*` classes and decorative tints on Dashboard cards.
- Replace `indigo-*` on this page with the named colors.
- Move the chart colors at lines ~292–294 (`#6366f1` / `#a5b4fc`) and the Balance Flow chart's indigo onto the palette: light accent `#0f766e`, dark `#2dd4bf`. Read the palette with the existing `isDark` pattern.
- Raise any `text-[11px]` or `text-[10px]` body text on this page to `text-[13px]`.
- Remove the now-unused imports.

- [ ] **Step 1: Make the changes** above.

- [ ] **Step 2: Grep checks.**
  Run: `cd frontend && grep -n "bg-gradient\|indigo\|#6366f1\|#a5b4fc\|text-\[1[01]px\]" src/pages/Dashboard.tsx src/components/dashboard/*.tsx src/components/NeedsAttention.tsx; grep -rn "SafetyMarginHero\|SpendableTile" src`. Expected: no output.

- [ ] **Step 3: Run the full suite and the build, and confirm they pass.**
  Run: `cd frontend && bun test && bunx vite build`. Expected: pass.

- [ ] **Step 4: Commit:** `feat: make the Household Snapshot the Dashboard hero and retire old phone tiles`.

---

## Controller verification (after the final whole-branch review; not an implementer task)

Use the Interceptor skill: run the preflight, use `--context`, and check the dev frontend against the dev backend.
- Desktop at about 1440px and phone at about 390px, in light and dark, with balances shown and hidden.
- The lowest bar's date and amount match "Lowest in the next 3 months".
- No amount is visible while hidden, including bar tooltips.
- No console errors.

Report screenshots without amounts. Deploying to `:8443` waits for Dan's "deploy".
