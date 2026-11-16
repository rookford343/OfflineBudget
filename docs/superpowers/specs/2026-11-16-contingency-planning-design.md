# Contingency Planning — Design

## Intent

Dan wants a guardrail, not a calculator. Today, Money Market functions as his
emergency fund, but the app shows it as one lump balance — nothing
distinguishes "the part I actually need to keep" from "money that's sitting
there." Two things are driving this:

1. He doesn't want to look at Money Market and mistake the whole balance for
   money he can spend without consequence.
2. Looking ahead, Money Market will eventually hold more than just the
   emergency fund (growth money mixed in), and at that point he needs a clear
   line between "floor" and "actually available."

A dedicated **Contingency Planning** page answers one question: if income
stopped today, is the floor covered, and what would get cut first? ("Job-loss"
framing was deliberately dropped for "contingency" — same substance, less
threatening to look at.)

## Goals

- A **3-month floor**: 3 × the monthly cost of everything tagged essential,
  recalculated live from current data — never a number set once and left
  stale.
- A per-recurring-item **essential/non-essential** flag, replacing the
  implicit (and wrong) assumption that today's `is_discretionary` category
  tag means "would survive without this." Sensible defaults (mortgage,
  insurance, vehicle loans default essential); Dan can override any item.
- Groceries counted toward the floor even though it isn't a recurring item.
- The page shows: the floor, the current Money Market balance, the surplus
  above the floor (which doubles as "what's actually free for other things"
  once Money Market grows past pure-emergency-fund size — no separate
  feature needed for that), and a list of non-essential active expenses with
  their monthly cost.
- A manual **"paused — confirmed"** mark per non-essential item, so once Dan
  has actually gone and cancelled or paused something in real life, the page
  reflects that it's done.

## Non-goals / anti-goals

- No automated pausing, cancelling, or skipping from this page. It's a list
  that tells Dan what to go do; it never acts on his behalf. (He already has
  the floating-expense skip feature elsewhere for routine month-to-month
  skipping — this is a different, crisis-specific, manually-confirmed state.)
- Not a forecast or scenario tool. No "what if I also cut X" modeling. Just
  the floor, the surplus, and the cut list.
- Not shown inline on the Dashboard or account sidebar. Dedicated page only
  — Dan confirmed he doesn't want this competing for attention day-to-day.
- The 6-month figure is explicitly out of scope for this feature. The 3-month
  number is the real line; a 6-month figure isn't tracked or displayed here.

## Current state (grounding)

- `RecurringItem` has no essential/non-essential concept today.
  `categories.is_discretionary` is the closest existing field, but it's an
  app-internal budget-bucket distinction (assignable/variable vs fixed
  recurring), not a "would survive without this" judgment — e.g. Groceries is
  tagged `is_discretionary=1` today purely because it's a variable spending
  category, despite being true survival spending.
- Groceries is tracked as a `budget_allocations` row (category "Groceries",
  `month=0` default), not a `RecurringItem` — it has no monthly-equivalent
  machinery to hook into automatically.
- Money Market is already treated as the emergency fund by convention
  (excluded from savings totals, sorts last in account lists), but nothing
  computes or displays a floor against it today.
- `GET /recurring/breakdown` already computes `monthly_equivalent` per item
  (handles monthly/quarterly/yearly normalization) — the floor reuses this,
  it doesn't reimplement amortization.

## Data model

- `RecurringItem.is_essential: bool`, default `True`. Migration backfill:
  `is_essential = NOT category.is_discretionary` for items with a category;
  `True` for items with no category (an uncategorized bill is more likely a
  real bill than discretionary fluff — my call, flagged for the builder
  check). This already satisfies Dan's explicit examples without
  special-casing: Mortgage/Rent, Insurance, and Vehicles are all
  `is_discretionary=0` today, so they land essential by default with zero
  extra logic.
- **Create-time default, then manual forever (Dan's explicit call):** when a
  new item is created, `is_essential` defaults from the chosen category the
  same way the migration backfill does (`NOT category.is_discretionary`,
  `True` if uncategorized) — a one-time starting guess, not a live binding.
  After that, `is_essential` is Dan's own flag: changing an item's category
  later (for any reason, including recategorizing an existing bill) never
  touches `is_essential` again. This trades "stays perfectly in sync with
  category" for "never silently overwrites a choice Dan made," which Dan
  chose explicitly after the builder check flagged the ambiguity.
- `RecurringItem.contingency_paused_at: datetime | None`, default `None`.
  Non-null means Dan has confirmed, outside the app, that this expense is
  actually paused/cancelled. A nullable timestamp (not a bare boolean)
  mirrors this codebase's existing pattern for "mark get confirmed, record
  when" fields (e.g. `drift_dismissed_through`) and gives Dan an implicit
  "paused since" date for free. My call — flagged for the builder check in
  case Dan wants this to auto-clear on some condition (none identified in
  this conversation; default is it never auto-clears, only a manual
  uncheck).
- No new table for groceries. The floor's grocery component reuses the
  existing `budget_allocation_total()` helper (`backend/services/month_base.py:53-77`)
  for the user's "Groceries" category — the same helper `month_base`,
  `month_summary`, `available_to_spend`, and `budget_snapshot` already share.
  That helper resolves a month-specific override over the `month=0` default
  when one is set (not a flat `month=0`-only read, corrected after the
  builder check flagged the original wording as contradicting both this
  codebase's existing convention and this design's own "recalculated live,
  never stale" goal). If no row resolves at all, the grocery component is
  `$0` (no error) — my call, flagged for the builder check.

## The floor calculation

```
essential_monthly = sum(monthly_equivalent for each active, expense-type,
                         is_essential=True RecurringItem)
                     + budget_allocation_total(groceries category, current year/month, or 0)

floor = essential_monthly * 3
```

- Only `is_active=True` items count (an item the user already deactivated
  shouldn't inflate the floor).
- `credit_card_payment`-type items are excluded the same way `by_category`
  and `by_owner` already exclude them (a card's own payoff isn't new
  spending, it's covering spending already counted elsewhere).
- Floating/skipped items: a floating item's monthly average already reflects
  its normal monthly cost regardless of which exact day it lands — no special
  handling needed, consistent with how `by_category`/`by_owner` already treat
  floating items.

## The page

**Contingency Planning**, a new top-level page (placement alongside Budget /
Goals / Forecast on the Planning section of the sidebar — matches this app's
existing nav grouping).

- **Headline numbers:** the floor (3-month essential run-rate), the current
  emergency-fund balance, and the surplus (`emergency-fund balance - floor`).
  "Emergency-fund balance" means accounts with `is_emergency_fund == True`
  (not `type == money_market`) — the same filter `budget_snapshot.py:707-715`
  already uses to isolate the emergency fund from its complement "savings
  pool," per the `Account` model's own comment on why account type alone
  can't be used for this. Today that's just the Money Market account; this
  stays correct automatically if that ever changes. Surplus
  rendered as a warning/negative state when it's below zero — the floor
  isn't covered.
- **Cut list:** every active, expense-type, `is_essential=False` recurring
  item, sorted by monthly cost descending, each row showing its name,
  monthly cost, and a checkbox labeled something like "Paused" bound to
  `contingency_paused_at` (checked = set to now, unchecked = cleared to
  null).
- **Essential toggle:** reachable from the existing Recurring page's item
  form (a new checkbox next to the existing Floating/Amount-varies
  checkboxes), not from the Contingency Planning page itself — this page is
  for reviewing the list and tracking pause status, not for editing item
  properties.
- No money math happens client-side; the page consumes a new backend
  endpoint that returns the floor, the MM balance, and the cut list
  pre-computed, same pattern as `GET /recurring/breakdown`.

## What's left to the builder

- Exact new endpoint shape and route name (e.g. `GET
  /recurring/contingency`), following this app's existing router
  conventions.
- Exact page layout within the "dedicated page, simple list" brief above —
  no mockup was requested for this feature.
