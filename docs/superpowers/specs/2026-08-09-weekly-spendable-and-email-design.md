# Weekly Spendable Pacer & Email Consolidation — Design

**Status:** Approved by Dan 2026-08-09 (verbal, via brainstorming session — visual mockup Option A chosen for email style).

## Problem

Two related complaints:

1. The Household Snapshot's "Left to Spend (weekly)" figure is still off. It's a single blended number (`left_to_spend / (days_remaining_in_month / 7)`), doesn't correspond to real calendar weeks, doesn't show whether this week is on/off pace, and — the real root cause — `left_to_spend`'s formula only reacts to **credit card** balance changes. Discretionary spending straight out of checking (debit purchases) never touches it at all, so a chunk of real spend is invisible to the number.
2. On the day the Weekly Digest email sends, the Daily Summary email *also* sends, and both show overlapping account/card/spending data — two emails a day that say almost the same thing. The digest's visual design is also due a polish pass (mockups compared, Option A — refined cards — selected).

## Decisions (from brainstorming)

- **Rollover scope:** one shared monthly pool. Overspend one week and future weeks shrink to compensate; underspend and they grow. The weekly number is a *pacing view* into one true monthly balance, not an independent per-week budget.
- **Replaces, doesn't add:** this replaces the existing weekly figure in place rather than sitting alongside it.
- **What counts as spend:** discretionary transactions only — excludes anything already netted into the monthly pool as a fixed obligation (recurring bills, credit-card-payment recurring items, savings/planned transfers). Counting those again would double-dip and reintroduce the "off" feeling.
- **Week boundaries:** calendar week, Sunday–Saturday. Partial first/last week of the month gets a proportional (not full 7-day) share.

## Architecture

### New concept: discretionary spend, transaction-driven

`left_to_spend` (existing, spreadsheet-verified against Dan's real Budget.xlsx — see `budget_snapshot.py`'s docstrings) stays **exactly as it is today**. It's card-balance-derived, matches Dan's spreadsheet cell-for-cell, and nothing here touches its formula. It continues to be the monthly "Left to Spend" figure shown as-is.

The weekly/daily pacer is a **new, separate calculation**, anchored to `leftover` (income − fixed bills − savings/groceries budgets — the same starting point `left_to_spend` uses) rather than to `left_to_spend` itself, and paced against **actual discretionary transactions** instead of card balances:

```
monthly_discretionary_budget = leftover                         # unchanged existing calc
discretionary_spend_mtd      = sum of discretionary transactions, month start -> today
remaining_pool                = monthly_discretionary_budget - discretionary_spend_mtd
```

**"Discretionary transaction" definition** — a checking-account `Transaction` or `CreditCardTransaction` counts toward `discretionary_spend_mtd` when ALL of:
- It's an outflow (checking: `amount < 0`; card: `amount > 0`, i.e. a charge not a refund).
- Its category is not a `savings`-type category (reuses the existing `NOT_SAVINGS` filter from `spending_helpers.py`).
- For checking `Transaction` rows: `recurring_item_id IS NULL` (a bill/recurring payment is already counted in `leftover`, not discretionary) AND its `id` isn't referenced by any `PlannedTransfer.verified_transaction_id` for this user (a verified planned transfer is a savings movement, not spending).
- For `CreditCardTransaction` rows: it isn't a **card-linked recurring charge** that's already fired this period. Card-linked recurring items (`RecurringItem.card_id IS NOT NULL` — e.g. Netflix on the Sapphire card) are already subtracted from `leftover` via `_cc_budget_total`. Rather than fuzzy-matching individual transactions to a recurring item (fragile), reuse the existing calendar-day approach: build a `_recurring_card_charges_in_range(db, user_id, start, end)` helper — a range-parameterized sibling of `budget_snapshot.py`'s existing `_charged_so_far` — that sums each card-linked recurring item's amount once, if its `day_of_month` falls inside `[start, end]`. Subtract that flat total from the card-charge sum for the same range instead of matching per-transaction. Simpler and matches the codebase's existing pattern (calendar-day firing, not transaction fuzzy-matching, is how `_charged_so_far`/`_fires_soon` already work elsewhere in this file).

### Week/day pacing

```
week_start = the Sunday on/before today
week_end   = the Saturday on/after today
weeks_remaining_in_month = sum over each remaining calendar week this month of
                            (days of that week that fall in this month) / 7
                            -- e.g. a 3-day final week counts as 3/7, not a full week

this_week_target    = remaining_pool / weeks_remaining_in_month
spend_this_week     = discretionary spend, week_start -> today
spendable_this_week = this_week_target - spend_this_week
days_left_in_week   = week_end - today + 1 (inclusive of today)
spendable_today     = spendable_this_week / days_left_in_week
```

Recomputed fresh on every read (no persisted snapshot/state needed) — `remaining_pool` already reflects every actual transaction through today, so a bad week is automatically visible in a shrunk `spendable_this_week`/`spendable_today`, and it carries into next week's `this_week_target` too since `remaining_pool` is one running total for the whole month. No new tables.

### Schema changes

`BudgetSnapshot` (`backend/schemas.py`) gains:
- `spendable_this_week: Decimal`
- `spendable_today: Decimal`
- `days_left_in_week: int`
- `on_pace: bool` — `spendable_this_week >= 0` (simple derived flag the frontend/email can color off directly, no need to reimplement the sign check)

`left_to_spend_weekly` **stays in the schema** (frontend/email already read it) but is **redefined** to equal the new `spendable_this_week` — same slot, corrected math, no field rename needed for the two existing consumers (`Dashboard.tsx`, `main.py`'s digest HTML). `spendable_today` is new, added alongside.

**Known, disclosed trade-off:** `left_to_spend` (monthly, card-balance-derived, spreadsheet-matched) and the new `remaining_pool` (monthly, transaction-derived) are computed differently and can drift apart by small amounts — e.g. a pending-but-uncleared card charge shows up in `left_to_spend` (via `current_balance`) before it has a `CreditCardTransaction` row. This is the same kind of "two independently-verified metrics that don't algebraically collapse into one" situation already true of `left_to_spend` vs. `not_saving` in this file. Not fixing this now; flagging so a future "why don't these two numbers match" question has a documented answer.

## Email changes

### Consolidation

`backend/main.py`'s `_send_daily_summaries` gains one guard at the top: skip sending (log at debug, not error) for any day where `date.today().strftime("%a").lower()[:3] == settings.WEEKLY_DIGEST_DAY`. The weekly digest already covers everything the daily summary shows (account balances, card balances, upcoming bills overlap with categories/merchants) — this makes the digest the sole email on its day, daily summary continues normally every other day.

### Visual redesign (Option A — Refined Cards)

Applies to `_digest_html` in `backend/main.py`: tightened spacing, subtle card shadow/border-radius, rounded stat-card backgrounds already present today get refined padding and a small "per day / on pace" sub-line under the spendable-this-week card. Household Snapshot section becomes:

```
[ Spendable this week    ]  [ Not Saving (this week) ]
[ $NNN                   ]  [ $NNN                    ]
[ $NN/day · on pace       ]
```

("on pace" / "$NN over pace" driven by the new `on_pace` flag — red-tinted card and "over pace" text when false, matching the existing red-risk-card color convention already used for the balance-risk banner.) No structural framework change (still inline-styled table-based HTML for email-client compatibility) — this is a styling pass on the existing template, not a rewrite.

## Testing

- `backend/tests/test_budget_snapshot.py` (or a new `test_weekly_spendable.py`, implementer's call) — discretionary-spend exclusion cases (recurring-linked checking transaction excluded, verified-transfer transaction excluded, card-linked recurring charge excluded via the day-of-month helper, savings-category transactions excluded on both sides), week-boundary math (partial first/last week of month), rollover across weeks (overspend week 1 shrinks week 2's target — assert via two sequential `as_of` calls in the same month), `spendable_today` division.
- `backend/tests/test_email_service.py` or `test_main_scheduler.py` (whichever pattern exists) — daily summary skipped when `date.today()` matches `WEEKLY_DIGEST_DAY`, sent normally otherwise. Mock/patch `date.today()` rather than relying on the real day of the week.
- No frontend test changes expected (Dashboard.tsx keeps reading `left_to_spend`/`left_to_spend_weekly`, both still present).

## Out of scope

- Settings/sidebar reorg (explicitly next, after this).
- Per-category weekly pacing (this is a whole-household aggregate figure, matching how `left_to_spend`/`not_saving` already work).
- Persisting week-snapshot history for a "how did past weeks trend" view — not asked for, YAGNI.
