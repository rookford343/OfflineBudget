# Household Budget Snapshot (Dashboard + Weekly Email)

**Date:** 2026-08-08
**Status:** Approved for planning
**Author:** Iris (with Dan)

## Problem

Dan's wife doesn't use OfflineBudget directly — she needs a low-clutter,
wife-friendly view of household spending, delivered by email. His
spreadsheet's "2026 Overview" tab already has exactly this in the form of
two numbers next to the credit card balances: **"Left to Spend"** and **"Not
saving"** (monthly and per-week), plus top spending categories and top
merchants elsewhere on the sheet. The app has no equivalent of the first
two numbers anywhere, and while it already has a working weekly digest
email (categories, merchants, balance risk) and a Dashboard credit-card
section, neither surfaces "how much is actually safe to spend before it
eats into savings."

Separately, Dan currently tracks pending/not-yet-posted credit card charges
by hand outside the app, specifically to catch overspending before his
checking account would need a rescue transfer from Savings (the buffer-
transfer feature shipped earlier this week). He wants that folded in as a
simple manual number per card.

## Goals

1. Reproduce "Left to Spend" and "Not saving" (monthly + weekly-allowance
   variants) as real, computed numbers — verified against Dan's actual
   spreadsheet cells, not just structurally similar.
2. Surface them, plus the existing top-categories/top-merchants/credit-card
   data, on both the Dashboard and the Friday weekly email, from one shared
   computation.
3. Add a manual `pending_charges` field per credit card, editable from
   Credit Cards settings and inline on the Dashboard, that (a) improves the
   Forecast's credit-card-payment projection and (b) is not part of the
   Left-to-Spend/Not-saving math (that math uses today's real balance only —
   pending charges are a forecast-only concept, mirroring how Dan already
   keeps these as separate mental models today).
4. Visually refresh the weekly email — the current template is plain HTML
   tables.

## Non-goals

- The Needs/Wants/Savings/Charity percent-of-income rollup (deferred from
  the original OfflineBudget audit — still deferred).
- Automatically pulling pending charges from Chase — Dan explicitly wants
  the manual number as a stopgap.
- Auto-resetting `pending_charges` after the statement closes — Dan manages
  it himself.
- Changing `available-to-spend` (the existing Dashboard metric) — it answers
  a different question (income minus all committed expenses minus month-to-
  date actual spending) and stays as-is alongside the new numbers.

## The formulas (reverse-engineered from Budget.xlsx, verified against live cells)

Confirmed by decoding the actual Excel formulas in `2026 Overview!B17:C18`
and `Budget!F1:F6`, and reproducing Dan's real numbers exactly
($1,567.72 / $438.96 / $2,085.64 / $583.98 as of 2026-08-07):

```
Leftover        = MonthlyIncome
                  - Σ(active RecurringItem, type=expense, monthly-equivalent amount)
                  - SavingsBudget (BudgetAllocation, category "Savings", month=0)
                  - GroceriesBudget (BudgetAllocation, category "Groceries", month=0)

CardBalances    = Σ(CreditCard.current_balance) across active cards
                  (uses current_balance only -- NOT + pending_charges; see Goal 3)

ChargedSoFar    = Σ(RecurringItem.amount) for active RecurringItems with
                  card_id set AND day_of_month <= as_of.day
                  (the portion of recurring card subscriptions that have
                  already posted this month -- Dan's "Credit Card Bills"
                  list on the Budget tab)

CCBudgetTotal   = Σ(RecurringItem.amount) for ALL active RecurringItems
                  with card_id set, regardless of day_of_month (the full
                  monthly total of Dan's "Credit Card Bills" list)

LeftToSpend     = Leftover - CardBalances + ChargedSoFar
                  (CCBudgetTotal cancels out algebraically here -- the
                  spreadsheet's actual cell adds the full CC budget back
                  then subtracts the not-yet-due remainder, which nets to
                  just +ChargedSoFar)

NotSaving       = QuarterMinimum - CardBalances - CCBudgetTotal + ChargedSoFar
                  (QuarterMinimum = the current quarter's lowest projected
                  checking balance -- confirmed intentional with Dan, even
                  though it reads oddly out of context: it represents how
                  much of the quarter's safety cushion current card debt +
                  upcoming card bills would eat into. Unlike LeftToSpend,
                  CCBudgetTotal does NOT cancel out here -- verified by hand
                  against the live spreadsheet cell, this term is required)

DaysRemaining   = (last day of as_of's month) - as_of.day + 1

WeeklyAllowance(X) = X                        if DaysRemaining <= 7
                    = X / (DaysRemaining / 7)  otherwise
```

`as_of` is an explicit parameter (defaults to `date.today()`), not an
implicit global read, so the golden-value test can pin it to 2026-08-07 and
assert exact agreement with the spreadsheet.

## Design

### Backend: `backend/services/budget_snapshot.py` (new file)

One function, `compute_budget_snapshot(db, user, account_id, as_of=None) -> BudgetSnapshot`:

- Computes `Leftover`, `CardBalances`, `ChargedSoFar`, `LeftToSpend`,
  `NotSaving`, and their weekly-allowance counterparts per the formulas
  above.
- `QuarterMinimum` reuses `forecast_engine.build_quarters()` for the
  account's current-quarter data (same source the spreadsheet's own
  `min('2026 Forecast'!...)` pulls from) rather than re-deriving it.
- Also returns a `cards: list[CardSnapshot]` (name, current_balance,
  pending_charges, credit_limit, utilization_pct, due_day) and reuses
  `spending_helpers.category_totals_for_range` /
  `merchant_totals` for the trailing-7-day top categories/merchants (same
  helpers `generate_weekly_digest` already uses — no new spending logic).

New schema `BudgetSnapshot` in `backend/schemas.py`:

```python
class CardSnapshot(BaseModel):
    id: int
    name: str
    current_balance: Decimal
    pending_charges: Decimal
    credit_limit: Decimal
    utilization_pct: Decimal
    due_day: int

class BudgetSnapshot(BaseModel):
    as_of: date
    leftover: Decimal
    left_to_spend: Decimal
    left_to_spend_weekly: Decimal
    not_saving: Decimal
    not_saving_weekly: Decimal
    days_remaining_in_month: int
    cards: list[CardSnapshot]
    categories: list[WeeklyDigestCategory]     # reused, trailing 7 days
    top_merchants: list[MerchantSpendingEntry]  # reused, trailing 7 days
```

New endpoint: `GET /spending/budget-snapshot?account_id=` in
`backend/routers/spending.py`, alongside the existing `available-to-spend`
endpoint (same file, same auth pattern).

### New field: `CreditCard.pending_charges`

`Mapped[Decimal] = mapped_column(Numeric(14,2), default=0)` on the
`CreditCard` model, migrated via `upgrade_schema()`'s existing
`ALTER TABLE credit_cards ADD COLUMN` pattern. Exposed on the existing
credit-card read/update schemas and the Credit Cards settings form (a
plain numeric field next to the existing balance/limit fields).

### Forecast integration

In `forecast_engine.build_forecast()`, the existing CC-payment injection
(`cc_payments.setdefault(card.next_payment_date, []).append((card.name,
Decimal(str(card.balance_due))))`) changes to inject
`Decimal(str(card.balance_due)) + Decimal(str(card.pending_charges or 0))`
-- the one place pending_charges actually affects a number Dan already
watches (the checking forecast, and by extension the buffer-transfer
schedule that reads it).

### Dashboard UI

- New "Left to Spend / Not Saving" card, styled like the existing
  Dashboard cards (`Available to Spend` sits right next to it, visually
  distinct so the two aren't confused -- different questions, different
  numbers).
- Existing Credit Cards card (`frontend/src/pages/Dashboard.tsx:246-280`)
  gains a `pending_charges` row per card with inline edit (small pencil/
  input affordance, PATCH to the existing credit-cards update endpoint).
- Top categories/top merchants: **already rendered** on the Dashboard from
  `weeklyDigest` (`Dashboard.tsx:140-165`) -- no new work needed there
  beyond folding the new snapshot fields into the same section visually.

### Email refresh

`backend/main.py`'s `_digest_html()` and `summary_generator.generate_weekly_digest()`
gain the new snapshot fields (calling `compute_budget_snapshot` alongside
the existing digest computation) and a visual pass: card-style sections
with the same color language as the Dashboard (indigo/emerald/amber/red),
instead of plain bordered `<table>` rows. `WeeklyDigest` schema gains a
`snapshot: BudgetSnapshot` field.

## Testing

The core test is a **golden-value regression** against Dan's real spreadsheet
numbers: seed a test user with the same recurring items, budget
allocations, and card balance Dan's spreadsheet describes, call
`compute_budget_snapshot(..., as_of=date(2026, 8, 7))`, and assert
`left_to_spend == 1567.72`, `left_to_spend_weekly == 438.96`,
`not_saving == 2085.64`, `not_saving_weekly == 583.98` (rounded to cents).
This is a stronger guarantee than a synthetic scenario: if the formula
drifts from Dan's actual mental model, this test catches it immediately.

Additional cases:
- `DaysRemaining <= 7` branch of `WeeklyAllowance` (end-of-month date).
- Zero cards / zero card balance (no active cards yet).
- The forecast-injection change: a card with `pending_charges > 0` -- assert
  the injected CC payment amount includes it, and a card with
  `pending_charges = 0` behaves identically to before (regression guard for
  every existing forecast test).

## Open questions for the implementation plan

- Exact Dashboard placement/styling of the new card relative to the
  existing `Available to Spend` card (visual layout call, not a data
  question).
- Whether the email's visual refresh touches `generate_daily_summary`'s
  template too, or only the weekly digest's -- default to weekly-only per
  Dan's stated priority, daily stays as-is unless he asks otherwise.
