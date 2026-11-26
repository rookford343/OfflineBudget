# Dashboard Wide-Window Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Snapshot hero look right on wide windows. That means four things:
- an honest $0-based chart with a cushion line;
- slim bars and a capped hero width;
- labels in the correct order;
- on very wide windows, a right column holding "Needs attention" and "Upcoming Bills".

**Architecture:** All bar geometry moves into pure functions in `lib/weeklyLows.ts`, and `WeeklyLowsChart` only renders their output. The Upcoming Bills card is extracted into its own component, so `Dashboard.tsx` can place it once: either in its current spot, or in the new right column when the viewport is at least 1700px.

**Tech Stack:** React 19, TypeScript, Tailwind 3 (`darkMode: "class"`, named CSS-variable colors), `bun:test`, `react-dom/server` static-render tests.

**Spec:** `docs/superpowers/specs/2026-11-25-dashboard-redesign-design.md`. Read the section "Addendum 2026-11-26: wide-window polish".

## Global Constraints

- No money logic changes. Statuses come from the backend. The tone rules are unchanged: status wins over accent, accent marks the lowest bar only when that bar's status is `ok`, and ties go to the earliest.
- Masking: with balances hidden, no amount appears in text, `title`, `aria-label` or `placeholder`. The cushion line carries no text.
- Chart geometry:
  - chart height 64px;
  - bars at most 40px wide;
  - 6px gaps between bars, left-aligned;
  - heights are `amount / max(maxAmount, cushion)` of 64px;
  - a week below $0 renders as a 4px red stub;
  - a dashed cushion line in `border-muted`, at `cushion / scaleMax` of 64px from the bottom.
- Order under the chart: month labels aligned to bar positions, then the selected-week caption, then the "Lowest …" rows.
- The hero content is capped at about 960px (`max-w-[960px]`). The wide hero's columns are `grid-cols-[auto_auto] justify-start gap-x-16`, with Spendable keeping its left border.
- Very wide windows: at `useMinWidth(1700)`, the desktop layout is a two-column grid `grid-cols-[minmax(0,960px)_minmax(320px,1fr)] gap-6`. The hero goes on the left. The right column holds `NeedsAttention`, then `UpcomingBillsCard`. Below 1700px, the layout is unchanged from today.
- The phone path is unchanged.
- `frontend/tests/moneyGuard.test.ts`:
  - re-key the existing "chart sampling" entry to the new exact display-only line(s), with the same category and reason;
  - never add allowlist entries for money arithmetic.
- Tooling and process:
  - use bun only;
  - `cd frontend && bun test` and `bunx vite build` must pass;
  - commit directly to `main` and do not push;
  - end every commit with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`;
  - use made-up amounts only.

## Review Focus

1. **Every week above the cushion, with a cushion of 0.** The cushion line sits at the baseline (0px offset), not hidden off-chart and not NaN. Pinned in Task 1.
2. **All-gap or empty list.** `scaleMaxFor` returns the cushion, or 1 when that is 0, so nothing divides by zero. Pinned in Task 1.
3. **A negative low.** It renders a 4px stub with the `danger` tone, not a negative height. Pinned in Task 1.
4. **Hidden balances in the moved Upcoming Bills card.** Amounts are masked exactly as before. Pinned in Task 2.
5. **A 1699px viewport compared with 1700px.** The bills card renders exactly once in both cases. Pinned by the Task 2 grep and the controller's Chrome check.

---

### Task 1: $0-based chart geometry, cushion line, label order, hero width

**Files:**
- Modify: `frontend/src/lib/weeklyLows.ts` and `frontend/src/lib/weeklyLows.test.ts`
- Modify: `frontend/src/components/dashboard/WeeklyLowsChart.tsx`, plus its test `WeeklyLowsChart.test.tsx`
- Modify: `frontend/src/components/dashboard/SnapshotHero.tsx`. Change its wide grid (line ~62) and pass `cushion={parseFloat(snapshot.safety_cushion)}` to the chart.
- Modify: `frontend/tests/moneyGuard.test.ts`, to re-key the entry.

**Interfaces:**
- Produces, in `lib/weeklyLows.ts`:
  - `CHART_PX = 64` and `STUB_PX = 4` as exported constants.
  - `scaleMaxFor(lows: WeeklyLow[], cushion: number): number` returns the maximum of the non-null positive amounts and `cushion`, or `1` if that is ≤ 0.
  - `barHeightPx(amount: string | null, scaleMax: number): number`:
    - `0` for a null amount (the caller renders a gap);
    - `STUB_PX` for an amount ≤ 0;
    - otherwise `Math.max(STUB_PX, Math.round(amount / scaleMax * CHART_PX))`.
  - `cushionOffsetPx(cushion: number, scaleMax: number): number` returns `Math.round(Math.max(0, cushion) / scaleMax * CHART_PX)`.
- Produces: `WeeklyLowsChart({ lows, hidden, cushion, initialSelected? })`. The new prop is `cushion: number`.

- [ ] **Step 1: Write the failing tests.**
  - In `weeklyLows.test.ts`:
    - `scaleMaxFor([{amount:"2500.00"},{amount:"800.00"},{amount:null}], 1000) === 2500`.
    - `scaleMaxFor([{amount:"300.00"}], 1000) === 1000`.
    - `scaleMaxFor([], 0) === 1`.
    - `scaleMaxFor` over all-null amounts with cushion 0 gives `1`.
    - `barHeightPx("2500.00", 2500) === 64`.
    - `barHeightPx("800.00", 2500) === 20`.
    - `barHeightPx("-50.00", 2500) === 4`.
    - `barHeightPx("10.00", 2500) === 4`.
    - `barHeightPx(null, 2500) === 0`.
    - `cushionOffsetPx(1000, 2500) === 26`.
    - `cushionOffsetPx(0, 2500) === 0`.
  - In `WeeklyLowsChart.test.tsx` (static render):
    - The markup contains one element with `data-testid="cushion-line"` whose inline `bottom` equals the `cushionOffsetPx` value in px.
    - The cushion line has no text content.
    - In the markup, `data-testid="month-ticks"` comes before `data-testid="bar-caption"`, which comes before any element the parent renders after the chart. Assert tick-before-caption by index.
    - Each bar's inline height equals `barHeightPx(...)`.
    - In hidden mode the markup, with classes stripped, contains no fixture amount digits.

- [ ] **Step 2: Run the tests and confirm they fail.**
  Run: `cd frontend && bun test src/lib/weeklyLows.test.ts src/components/dashboard/WeeklyLowsChart.test.tsx`. Expected: FAIL, because `scaleMaxFor` is not exported.

- [ ] **Step 3: Implement.**
  - In the chart:
    - The bar row has `height: CHART_PX`, `gap-[6px]` and `justify-start`. Each bar button has `w-full max-w-[40px] flex-1`.
    - The cushion line is absolutely positioned: `border-t border-dashed border-muted opacity-70`, with `bottom: cushionOffsetPx`.
    - Month ticks are positioned at their bar's left offset, using the same index math as the bars, so they align. The selected-week caption sits under the ticks.
  - In `SnapshotHero`:
    - Wrap the content in `max-w-[960px]`.
    - The wide grid becomes `grid grid-cols-[auto_auto] justify-start gap-x-16`.
  - Re-key the `moneyGuard` entry.

- [ ] **Step 4: Run the tests and the build, and confirm they pass.**
  Run: `cd frontend && bun test && bunx vite build`. Expected: pass.

- [ ] **Step 5: Prove the guard can fail.**
  - Temporarily drop `cushion` from `scaleMaxFor`.
  - Confirm the `scaleMaxFor(..., 1000) === 1000` test fails.
  - Restore it.

- [ ] **Step 6: Commit:** `feat: $0-based weekly-lows chart with cushion line and capped hero width`.

---

### Task 2: Very wide layout: right column with Needs attention and Upcoming Bills

**Files:**
- Create: `frontend/src/components/dashboard/UpcomingBillsCard.tsx`. Move the "Upcoming bills" card JSX out of `Dashboard.tsx` (~lines 684-718) verbatim, so it looks and behaves exactly as now.
- Create: `frontend/src/components/dashboard/UpcomingBillsCard.test.tsx`.
- Modify: `frontend/src/pages/Dashboard.tsx`.

**Interfaces:**
- `UpcomingBillsCard({ bills, hasRecurring, hidden }: { bills: any[]; hasRecurring: boolean; hidden: boolean })`.
  - `bills` is `upcomingBills` from the existing `["recurring-upcoming"]` query.
  - `hasRecurring` is `recurring.length > 0`.
  - `hidden` is `balancesHidden`.
  - It calls `useNavigate()` itself for "Manage →".
- Consumes: `SnapshotHero`, `NeedsAttention` and `useMinWidth` (`lib/useMinWidth`), which already exist.

**Dashboard placement on the desktop path:**
- Add `const isXWide = useMinWidth(1700);`.
- **When `isXWide`:**
  - render `<div className="grid grid-cols-[minmax(0,960px)_minmax(320px,1fr)] gap-6 items-start">`;
  - inside it, render `SnapshotHero` on the left, and on the right a `space-y-6` column with `NeedsAttention` then `UpcomingBillsCard`;
  - skip the standalone `NeedsAttention`, and skip `UpcomingBillsCard` in its old location.
- **Otherwise:** keep today's order exactly, rendering `UpcomingBillsCard` where the old card was.
- The phone path is untouched.

- [ ] **Step 1: Write the failing test** `UpcomingBillsCard.test.tsx`. Use a static render with a `MemoryRouter` wrapper and two made-up bills.
  - Shown: each name and formatted amount is present.
  - Hidden: `BALANCE_MASK` is present, and, with classes stripped, no amount digits appear.
  - Empty with `hasRecurring=true`: the text "No bills due in the next 30 days" appears.

- [ ] **Step 2: Run it and confirm it fails.**
  Run: `cd frontend && bun test src/components/dashboard/UpcomingBillsCard.test.tsx`. Expected: FAIL, with module not found.

- [ ] **Step 3: Implement** the extraction and the placement described above.

- [ ] **Step 4: Verify.**
  - Run `cd frontend && bun test && bunx vite build`. Expected: pass.
  - Run `grep -c "<UpcomingBillsCard" src/pages/Dashboard.tsx`. Expected: `2`, the two mutually exclusive branches.
  - Run `grep -c "<NeedsAttention" src/pages/Dashboard.tsx`. Expected: `3` (phone, the wide column, and the non-wide desktop), each in a mutually exclusive branch.

- [ ] **Step 5: Commit:** `feat: right column for Needs attention and Upcoming Bills on very wide windows`.

---

## Controller verification (after the final review)

Use Interceptor on the dev frontend at :5173. On Dan's ~2050px window, in dark and light, with balances shown and hidden, check:
- the chart is $0-based and the cushion line is visible;
- the right column holds the strip and the bills;
- there is no duplicate bills card;
- with balances hidden, no amounts appear.

Deploying waits for Dan.
