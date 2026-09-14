# Spending Tab Redesign — Design

Dan's framing: the Spending tab is the biggest gap in the app right now —
he hasn't used it since the project started. Two problems, not one: (1) it
never surfaces the checking-vs-card distinction that matters most to him
(big fixed spend — mortgage, loans — posts through checking; discretionary
spend mostly posts through cards), and (2) several charts don't earn their
keep or feel arbitrary as a tab split. Approach B from brainstorming:
consolidate the redundant charts and bake source visibility into the
existing views, rather than a full ground-up rebuild (Approach C) or a
narrow patch that leaves the tab structure untouched (Approach A).

Tax Export is out of scope here — moving to its own nav spot (see [§5](#5-navigation-tax-export-moves-out)),
and its accuracy bugs (stale Indiana rate, missing Child Tax Credit — found
during this same brainstorming pass) are a separate, already-scoped fix
deferred until after this ships, per Dan's explicit call ("redesign first,
that's readily useful").

## Key discovery driving this whole spec

Most of what this design needs already exists server-side and is simply
never read by the frontend:

- `SpendingSubCategory.breakdown_by_source` (`backend/routers/spending.py:298-356`) —
  per-category dict of `{"Checking": amount, "<Card name>": amount}`,
  computed on every `/spending/by-category` call. `Spending.tsx` spreads
  the category object into `budgetCategories` but never reads this field.
- `MonthlySpendingEntry.checking` / `.cards` (`backend/routers/spending.py:73-81`) —
  every `/spending/monthly` row already carries the checking/card split
  Dan wants on the monthly bar chart. The frontend reads `.total` only.

Because of this, sections 1–3 below are **frontend-only, zero new backend
endpoints or fields**. Section 4 (Flow) needs one small backend grouping
change. Section 6 (Merchants) is the one place a new backend field would
be needed, and it's explicitly optional/deferred.

## Scope

1. Overview — checking/card split baked into hero cards, monthly chart, category list
2. Trends — consolidate two redundant time-series charts into one, split by source
3. (folded into 1) Category list inline source split
4. Flow — Uncategorized/small-category grouping + visual restyle
5. Navigation — Tax Export moves to its own top-level nav item
6. Merchants — optional per-merchant source split (stretch, not required for this pass)

**Explicitly deferred:** Tax Export's Indiana-rate and Child-Tax-Credit
bugs (separate fix, already scoped in chat, not part of this spec).

## 1. Overview — checking/card split baked in

**Where:** `frontend/src/pages/Spending.tsx`, `activeTab === "overview"` block.

**Discretionary/Fixed hero cards** (currently: `overview.discretionary_actual`,
`overview.fixed_actual`, `overview.total_actual` as blended totals only):
add a small sub-line under each of the three stat-card figures showing the
Checking/Card split for that figure, sourced from summing
`breakdown_by_source` across whichever categories feed that bucket
(discretionary categories vs. fixed categories — the existing
`budgetCategories` flattening already tags each row with enough info to
bucket it; no new backend call). Render as muted small text, e.g.
`$1,240 checking · $310 card`, omitted when one side is $0 (a category with
only one source shouldn't show a pointless "$0 card").

**Monthly bar chart:** convert the single-series `Bar` (line ~496-517) to a
**stacked** bar with two series — Checking and Cards — using
`MonthlySpendingEntry.checking`/`.cards` directly (`barData` mapping
changes from `{ month, total }` to `{ month, checking, cards }`). Two
`<Bar>` elements with `stackId="spend"`, colors: indigo for Checking
(matches existing `ct.barFill`), a second muted accent for Cards (reuse
the amber already used elsewhere for warnings — avoid introducing a new
hue not used anywhere else on this page). Tooltip (`TotalBarTooltip`)
updates to show both rows plus the total, following the existing
`TooltipBox` component's multi-row rendering (already used by
`StackedTooltip` for the category chart — reuse that component directly
instead of writing a new one).

**Category list** (`budgetCategories.map(...)`, line ~672-704): each row
gets an inline split shown under the existing actual/budgeted line,
_only_ when `breakdown_by_source` has more than one non-zero source (a
category that's 100% one source shows nothing extra — this is about
surfacing the mixed cases, not cluttering every row). Format matches the
hero-card sub-line style for visual consistency: `$340 checking · $210
card`. Uses the `breakdown_by_source` field already present on every
`overview.categories[].children[]` entry — no new query.

**Top Merchants:** left as-is (blended). Per-merchant source split is
section 6, optional.

## 2. Trends — consolidate into one chart

**Where:** `frontend/src/pages/Spending.tsx`, `activeTab === "trends"` block
(currently two separate cards: Year-Over-Year Monthly Spending bar chart,
24-Month Spending Trend area chart — lines 374-426).

**Replace both with one chart** plus a paired segmented control (Securo
reference pattern from `docs/securo-comparison.md`'s Analytics-page notes):
range (6M / YTD / 1Y / 2Y) and implicitly monthly granularity (this app has
no daily/weekly spending grain to switch to, so the granularity half of
Securo's D/W/M/Y control isn't applicable — range alone is the control).

**Data:** reuse `analyticsApi.rollingMonthly(n)` (already fetches N months
of `{ month, total }` — confirm during implementation whether it also
carries `checking`/`cards` per month like `/spending/monthly` does, or
needs the same two fields added; if missing, this is the one small backend
addition in this section, mirroring the existing `/spending/monthly`
pattern exactly rather than inventing a new shape). Bar count driven by
the selected range (6/12/24 months) rather than the current hardcoded
`analyticsApi.rollingMonthly(24)` always-24 call. Drop the separate
year-over-year grouped-bar chart entirely — it answers the same "how does
spending trend" question as the rolling chart, just calendar-aligned
instead of rolling, and Dan flagged this pairing as charts not earning
their space.

**Render:** stacked bars (Checking/Cards), same two-series treatment as
section 1's monthly chart, for visual consistency across the tab.

**Compatibility note:** `analyticsApi.rollingMonthly` is also called by
`Dashboard.tsx` (`rollingMonthly(6)`) — any `checking`/`cards` fields
added to `/spending/rolling-monthly`'s response must be purely additive
(new optional fields), never a change to the existing `month`/`total`
shape, so Dashboard's usage is unaffected. `/spending/yearly-trends`
becomes unused by the frontend once the YoY chart is removed; leaving the
endpoint in place (not deleting it) is fine — cheap to leave, and deleting
it is unrelated cleanup outside this spec's scope.

## 3. (see section 1 — category list split is documented there)

## 4. Flow — grouping + visual fix

**Where:** `backend/routers/spending.py`'s `spending_sankey` (line
740-807) for grouping; `Spending.tsx`'s `SankeyChart` component (line
979-1052) for the restyle.

**Root cause (confirmed, not a logic bug):** `spending_sankey` already
buckets uncategorized transactions into an "Uncategorized" node (line 776,
786) — nothing is silently dropped. The diagram looks incomplete because
many small categories each get their own thin node/link, and Dan doesn't
categorize everything, so "Uncategorized" ends up one of the largest
nodes among a lot of visual noise.

**Backend fix:** apply the same small-value collapsing this file already
uses on the stacked monthly-by-category chart (`_MAX_STACK_CATEGORIES`,
`_OTHER_CATEGORY_ID`, referenced at the top of `spending.py`) to
`expense_totals` before building nodes/links — past a threshold (reuse the
existing constant rather than picking a new number), collapse the
remainder into an "Other" node. "Uncategorized" stays its own node
regardless of size (it's diagnostic — collapsing it into "Other" would
hide the exact signal Dan needs to notice he should categorize more).

**Frontend restyle:** tighten node/link colors to the app's existing
indigo accent + semantic green/red (income/expense) rather than the
current three-color scheme (`#10b981`/`#6366f1`/`#f59e0b` at line 1032),
increase label contrast in dark mode (confirm via Interceptor per
`OPERATIONAL_RULES.md`'s verification rule before calling this done —
static code reading isn't enough for a visual color-contrast claim),
tighten node/link spacing (`nodePadding`, `PADDING` constants at the top
of `SankeyChart`) so labels don't crowd at typical viewport widths.

## 5. Navigation — Tax Export moves out

**Where:** `frontend/src/components/Layout.tsx` (nav items), app router
(wherever `Spending.tsx`'s routes are registered), `Spending.tsx` (remove
the `"tax"` tab and its whole render block, relocate that block to a new
`frontend/src/pages/TaxExport.tsx`).

**Route:** new top-level `/tax` page, own sidebar nav entry (placement:
near Spending, given it's still spend-derived data, but its own item —
confirm exact sidebar grouping against the current `Layout.tsx` nav-group
structure during implementation rather than guessing an order here).

**Data/logic:** unchanged, moved as-is (`spendingApi.taxEstimate`,
`taxYear` state, the CSV download handler, the whole JSX block currently
at lines 802-948) — this section is a relocation, not a rewrite. The
Indiana-rate/Child-Tax-Credit fixes are explicitly a separate, later pass.

**Spending.tsx** loses the `"tax"` entry from `activeTab`'s type union and
the tab-switcher array (line 39, line 359).

## 6. Merchants — optional per-merchant source split (stretch)

Not required for this pass. If time remains after 1-5: `merchant_totals`
(`backend/services/spending_helpers.py`) would need to track source per
merchant the same way `spending_monthly` already tracks it per month,
returned as a new field on `MerchantSpendingEntry` (e.g.
`breakdown_by_source`, matching the naming already established by
`SpendingSubCategory` for consistency). Frontend renders it as a small
inline tag per row, same visual treatment as section 1. Explicitly cut
from v1 scope if it threatens the rest of the spec's timeline — Dan's
stated priority is fixed/checking vs. discretionary/card at the
category level, not the merchant level.

## Testing

- Backend: new/changed tests for the Sankey "Other" collapsing (small
  categories grouped, "Uncategorized" never collapsed, total across nodes
  still reconciles to the pre-change total) and for `rollingMonthly` if it
  needs the `checking`/`cards` fields added — mirror the existing test
  pattern in `backend/tests/test_bank_sync_service.py`-style TDD (write
  the failing test first).
- Frontend: this repo has no existing frontend test suite pattern to
  extend (confirm during implementation — if true, verification for the
  UI changes is Interceptor-driven per `OPERATIONAL_RULES.md`, not new
  unit tests: screenshot each changed view in both light and dark mode,
  confirm the stacked bars/inline splits render correctly against real
  data, confirm Tax Export still works identically at its new route).
- No migration needed — no schema changes anywhere in this spec.

## Explicitly not doing (matches Approach A/C rejection from brainstorming)

- Not rebuilding tab labels/IA around "questions instead of chart types"
  (Approach C) — keeping Overview/Trends/Merchants/Flow.
- Not adding a separate dedicated "Compare Sources" tab/page — the split
  lives inline in the views that already exist, per Dan's "always-visible,
  no extra click" preference from brainstorming.
- Not touching Tax Export's calculation logic in this pass.
