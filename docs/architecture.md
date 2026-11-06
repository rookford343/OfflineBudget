# Architecture: where every number comes from

Read this before touching any money calculation. It is the map from a figure on a
screen or in an email to the function that computes it, and the checklist for
consolidating those functions into one shared layer.

Design background: `docs/superpowers/specs/2026-11-06-calculation-consistency-design.md`.
Status today: the shared layer is partly built. Rows marked `-> Task N` are scheduled
to move; until they do, the "function" column is where the math really lives.

## System overview

```
bank sync (SimpleFIN / Plaid / CSV / OFX)
        |
        v
SQLite database  (accounts, transactions, card transactions, recurring items,
        |          planned expenses, overrides, pending charges)
        v
shared calculation layer   backend/services/*
   month model . card payment model . real-spending rule . pending + thresholds
   forecast walk (forecast_engine.build_forecast)
        |
        v
API routers   backend/routers/*
        |
        v
screens (frontend/src/pages/*)  and  emails (summary_generator.py)
```

Rule of the layer: one recipe per base quantity, computed in one place, read by every
screen, email and endpoint.

## Number provenance table

Paths are under `backend/` unless noted. Names are functions unless noted.
"Surfaces" lists where the figure shows up.

| Figure | Plain-English definition | Function (file) | Surfaces |
|---|---|---|---|
| Month income / bills / one-offs | Every income and bill occurrence in a calendar month, with override amounts, Social Security boost, `include_in_forecast` filter, planned one-offs | `build_month_base` (services/month_base.py) | Recurring strip, Leftover, card bill split |
| Card-linked bills this month | Recurring bills charged to a card rather than checking | `card_bill_occurrences` (services/month_base.py) | Leftover, Left to Spend, Safety Margin |
| Leftover | Income minus bills minus planned one-offs minus budget allocations for the month | `leftover_parts` (services/budget_snapshot.py) | Dashboard Household Snapshot, daily email |
| Recurring "Left over" | Month model income minus expenses | `build_month_summary` (services/month_summary.py) | Recurring page strip |
| Left to Spend | Leftover minus card spending this month and pending charges, plus card bills already counted, plus card one-offs | `compute_budget_snapshot` (services/budget_snapshot.py), helpers `_card_spending_this_month`, `_transaction_fed_card_ids` | Dashboard, daily email, /spending/snapshot |
| Weekly / today allowance | Left to Spend or Safety Margin spread over weeks or days left | `_weekly_allowance`, `compute_budget_snapshot` (services/budget_snapshot.py) | Dashboard, email |
| Safety Margin | Lowest balance from today through end of next month (walk without unbilled card bills) minus unbilled card bills plus bills charged so far | `_lookahead_window`, `compute_budget_snapshot` (services/budget_snapshot.py) | Dashboard, email |
| Displayed lowest point (3-month low) | Lowest forecast balance over the lookahead window, walk including unbilled card bills, ignoring locked statement-payoff dips | `_lookahead_window`, `_lookahead_minimum`, `floor_mask` (services/budget_snapshot.py) | Dashboard, email |
| Next-month minimum | Lowest forecast balance in the next calendar month | `_next_month_minimum`, `_next_calendar_month_bounds` (services/budget_snapshot.py) | Dashboard, email |
| Lookahead status (amber/red) | Amber below the cushion, red below $0 | `lookahead_status` (services/budget_snapshot.py) | Dashboard, email |
| Cushion | `user.safety_cushion` (default $1,000) for the lookahead status. Separately: Wish List cushion (`WishSettings.cushion`, then account `low_balance_threshold`) and the risk banner threshold (`low_balance_threshold`, default $0) -> Task 6 (one cushion) | `compute_budget_snapshot` (services/budget_snapshot.py), `effective_cushion` (services/wish_plan.py), `find_balance_risk` callers (routers/forecast.py, services/summary_generator.py) | Dashboard, Wish List, risk banner, email |
| Forecast balances | Day-by-day projected checking balance | `build_forecast` (services/forecast_engine.py) | Forecast tab, lows, risk banner, Wish List, upcoming bills, baselines |
| Forecast walk start/flags | Callers choose their own start date and `include_unbilled_card_bills`; bridge walks inside `build_forecast` drop the flag -> Task 4 (standard walk) | `build_forecast` call sites: routers/forecast.py, services/budget_snapshot.py, services/summary_generator.py, services/upcoming_bills.py, services/wish_plan.py, services/forecast_baseline.py, services/forecast_engine.py (bridges, quarters) | Forecast tab, lows, digest, Wish List, baselines |
| Card payment amount (payoff) | Locked statement payoff, cycle estimate (pending + spent since statement + subscriptions before close + one-offs), second-hop rule, flat estimate, subscription fallback; basis kept on `ForecastTransaction.basis` | inline in `build_forecast`, helpers `_card_payoff_date_for_charge`, `_card_subscription_charges`, `_cc_actual_nearby` (services/forecast_engine.py) -> Task 5 (card payment model) | Forecast tab, Safety Margin, explain notes (`_cc_basis_note`) |
| Pending charges (fresh) | Hand-typed or synced pending total, ignored when older than 7 days | `card_pending` (services/pending.py), read by the forecast, Left to Spend, available-to-spend, the email and statement checks. The frontend still reads the raw field -> Plan 2 | Forecast, Left to Spend, Credit Cards page, email |
| Social Security boost | Extra take-home per paycheck once the wage base is met | `ss_paycheck_boosts`, `SSWageBaseTracker`, `pay_year_dates` (services/forecast_engine.py); month model calls them | Forecast, Recurring, Leftover |
| Weekend shift | Posting day moves off a weekend; override keyed by natural due date | `_adjust_for_weekend`, `_matches_schedule` (services/forecast_engine.py); month model and upcoming bills have their own date handling -> Task 4 | Forecast, Recurring, Upcoming bills |
| Card bill in month | Whether a card-paid recurring bill belongs to a month (quarterly lands whole in its due month) | `is_card_bill_in_month` (services/forecast_engine.py) | Month model, forecast |
| Upcoming bills | Next occurrence per bill with override amounts | `upcoming_bills` (services/upcoming_bills.py), `_next_fire_date` (services/summary_generator.py) | Dashboard card, daily email |
| Real spending (rule) | Whether a row is spend, income, a transfer or a card payment, and its signed amount: card payments and own-account transfers are neither, savings-category rows are transfers, refunds net as negative spend, an income-category debit reduces income | `classify_checking`, `classify_card`, `classified_rows`, `spend_totals` (services/real_spend.py); description checks `is_card_payment`, `looks_like_internal_transfer` (services/spending_helpers.py), `card_matches_description`, `looks_like_card_autopay` (services/card_matching.py) | everything below |
| Category / merchant totals | Real spending per category or merchant over a range | `category_totals_for_range` (= `spend_totals().by_category`), `merchant_totals` (services/spending_helpers.py, both over services/real_spend.py); `spending_breakdown` (services/budget_snapshot.py) | Weekly digest, Budget overview, snapshot explain |
| Spending page charts | Monthly, line items, by category, by card, yearly, rolling, Sankey, merchants | `spending_monthly`, `spending_line_items`, `spending_monthly_by_category`, `spending_by_category`, `spending_by_card`, `spending_yearly_trends`, `spending_rolling_monthly`, `spending_sankey`, `spending_by_merchant` (routers/spending.py), all reading `_spend_rows` / `classified_rows` (services/real_spend.py) | Spending page |
| Budget actuals | Real spend per budget line, split checking / cards; savings-type lines show money moved to savings | `compute_overview` (services/budget_calculator.py) over `classified_rows` and `savings_moved_rows`; `merchant_totals` use in routers/budget.py | Budget page |
| Monthly summary / Month in Review | Category totals, debits, credits, month-over-month change, net cashflow | `_month_spending_by_category` (= `spend_totals`), `generate_summary` (services/summary_generator.py) | Monthly email, Month in Review, `/spending/monthly-summary` |
| Weekly digest | Trailing 7 days of spending plus forward balance risk | `generate_weekly_digest` (services/summary_generator.py) | Weekly email, `/spending/weekly-digest` |
| Daily email | Headline figures, cards, upcoming, stale-connection notes | `generate_daily_summary` (services/summary_generator.py) | Daily email |
| Available to Spend | Monthly-frequency income minus bills for the calendar month (no boost, no overrides, refunds dropped) -> Task 7 rebuild | `available_to_spend`, `_committed_card_bills_fired` (routers/spending.py) | Dashboard card |
| Pacer add-backs / discretionary spend | Real spending in a range for the weekly pacer, with recurring card charges added back | `discretionary_spend_checking`, `discretionary_spend_card` (spend verdicts from `classified_rows`, minus recurring bills, Groceries/Savings lines and verified planned transfers), `discretionary_spend_in_range`, `compute_weekly_spendable` (services/spendable_pacer.py) | Dashboard weekly allowance |
| Wish List plan | Earliest safe date to afford a wish, using forecast plus cushion | `build_plan`, `earliest_safe_date`, `effective_cushion` (services/wish_plan.py); `wish_math.py` | Wish List page |
| Planned expense settlement | A planned one-off settles when a matching real charge appears | `auto_settle_planned_expenses`, `settle_after_sync` (services/planned_auto_settle.py) | Month model, forecast, Recurring |
| Tax estimate | Federal, state and FICA estimate from the tax profile | `estimate_taxes` (services/tax_service.py), `tax_estimate`, `tax_summary` (routers/spending.py) | Tax export page |
| Net Position | Checking balances minus card balances due | Dashboard.tsx (client-side `netPosition`) -> Task 8 (move to backend) | Dashboard |
| Cycle spend / pending-adjusted balance | Current balance minus balance due plus pending; checking balance after pending | Dashboard.tsx (`cycleSpend`), frontend/src/lib/usePendingBalances.ts -> Task 8 | Dashboard, Credit Cards |
| Budget track totals | Committed, flexible, budgeted and spent totals | frontend/src/pages/Budget.tsx, frontend/src/lib/budgetPlan.ts -> Task 8 | Budget page |
| Spending average | Average of the monthly bars | frontend/src/pages/Spending.tsx (`avg`) -> Task 8 | Spending page |

## Shared primitives

Filled in as each primitive lands. Until then the provenance table above is the truth.

### 1. Month model
Exists: `backend/services/month_base.py`. Edge cases and rules to document when finished:
weekends, quarterly bills, Social Security boost, funded one-offs.

### 2. Card payment model
Not yet extracted from `build_forecast` (Task 5).

### 3. Real-spending rule
`backend/services/real_spend.py`. One verdict per row; every spending and income total
reads it (Spending page charts, Sankey, Budget overview, weekly digest, monthly email,
Month in Review, Left to Spend's card spending, pacer).

Verdicts, checked in this order:

- **Checking rows** (only `is_actual` ones; `classify_checking` raises on a planned row):
  1. `card_payment` when the description matches an active card (`card_matches_description`)
     or reads like a card payoff (`looks_like_card_autopay`, which also catches a card no
     longer active).
  2. `transfer` when the description is an own-account transfer
     (`looks_like_internal_transfer`) or the row is under a savings-type category. Both
     directions: a transfer back from savings is not income either.
  3. `income` under an income-type category, signed: a debit there (a paycheck reversal)
     is negative income.
  4. `spend` for any other debit. A "Zelle payment to <person>" stays spend; only
     own-account wording is a transfer.
  5. A credit whose description matches a spend debit in the same window is a refund:
     negative `spend`. Any other credit is `income`.
- **Card rows** (`classify_card`): `card_payment` for payment wording (`is_card_payment`),
  `transfer` under a savings-type category, otherwise `spend` with the row's sign, so a
  refund is negative spend. Card rows are never income.

Amounts: spend and income are signed (refunds negative); transfers and card payments carry
their magnitude. Totals are never clamped: refunds larger than charges make a category
negative. The Sankey diagram alone omits non-positive flows, because it can't draw them.

Entry points: `classify_checking` / `classify_card` for one row; `classified_rows` for a
window, with the Spending page's `account_id` (checking side) and `card_id` (card side)
filters; `spend_totals` for `by_category`, `spend` and `income`. A balance-only card (no
transaction feed) has no rows and contributes nothing. Callers layer their own exclusions on
spend verdicts, never a second rule: the pacer drops recurring bills, the Groceries/Savings
lines and verified planned transfers. `filter_real_spend` (spending_helpers) keeps spend and
income rows for list views; `/spending/available-to-spend` keeps its own recipe until its
rebuild (Task 7).

Savings-type budget lines: their actual is money moved into savings, not spending.
`savings_moved` / `savings_moved_rows` (real_spend.py) sum the transfer verdicts on checking
debits and card charges filed under a savings-type category (a credit pulled back out is not
subtracted). `compute_overview` uses it for those lines only, so the Track Budgets "spent"
figure and `apply_rollover` see it; every spending total still excludes it.

Parity: `backend/tests/test_real_spend.py::test_all_spend_surfaces_agree`.

### 4. Pending and thresholds
Pending charges: `card_pending(card, today)` in `services/pending.py` is the only reader of
`CreditCard.pending_charges`. It returns the sum of the card's `CardPendingTransaction` rows
(floored at 0) when the card has any; otherwise the hand-typed field, only if
`pending_charges_updated_at` is within `PENDING_FRESH_DAYS` (7) of `today`; otherwise 0. A stale or
unstamped figure is never carried forward. A synced card whose pending list just went empty has
the field set to 0 by sync, so it reads 0. Writers (`bank_sync_service`, the credit-cards router)
touch the field; nobody else reads it.

Checking pending: `checking_pending_debits(db, account, today, card_payments_only=...)` returns the
Plaid `AccountPendingTransaction` debits, only while an active Plaid link keeps the snapshot live
(`pending_snapshot_is_live`). `card_payments_only=True` keeps the debits `match_payment_card` pins
to one active card (the forecast's rule). `checking_balance_with_pending` is posted balance minus
all pending debits; the sidebar adopts it in Plan 2.

One cushion is not yet adopted (Task 6).

### Forecast walk policy
No standard walk function yet (Task 4).

## Decisions log

Settled by the principal. Record any behavior change here.

- **Quarterly bills** land whole in their due month, everywhere. No dividing by three.
- **Savings-funded one-offs** net to zero in Leftover, matching the forecast.
- **Income items excluded from the forecast** are excluded from Leftover too.
- **Displayed lowest points** (dashboard, email) equal the Forecast tab's balances. Locked statement-payoff dips are still not treated as the floor.
- **Safety Margin** covers today through the end of next month.
- **The 3-month low is a warning:** amber below the user's cushion, red below $0. The cushion is a user setting, default $1,000.
- **Planned expenses auto-settle** when a matching real charge (pending or posted) appears at sync.
- **Available to Spend is rebuilt, not retired.** Streamline where numbers are calculated.
- **History is recorded** at each bank sync and each email. The "why" view is available everywhere in the app; the dashboard is the primary place.
- **Architecture documentation** for new people and AI is required.
- **Available to Spend (rebuilt)** is figured "before budgets": this month's income minus bills minus one-offs minus real spending so far, without the groceries/savings budgets, for the whole calendar month. Its info panel walks to Left to Spend (subtract budgets, then card and pending adjustments).
- **Real-spending verdicts, applied to every total:** refunds net against spending; transfers to savings or between your own accounts are not spending; a debit filed under an income category reduces income (for example a paycheck reversal).
- **One cushion everywhere.** The risk banner, the 3-month low and the Wish List all use the single cushion (default $1,000): amber below it, red below $0. The per-account `low_balance_threshold` and the Wish List cushion are retired; any existing non-default value migrates into the single setting.
- **Overrides are keyed by the item's natural due date.** The weekend shift moves only the posting day.
- **Workflow:** build in the live working tree. Take a `backup_database()` copy before schema changes, and run a before/after on a database copy for any step that moves a visible number.

## Tracing a mismatch

When two places show different numbers for the same concept:

1. Name the figure and find its row in the provenance table. Note every surface listed.
2. Read the function in the "Function" column for each surface. If two surfaces use different functions, that is the bug; fix it by routing both through the shared primitive.
3. Take a WAL-safe copy of the live database. Never copy `data/budget.db` with `cp`, and never run the tool on the live file:
   `uv run --locked python -c "from backend.services.db_backup import backup_database; backup_database('data/budget.db', '/path/outside/repo/copy.db')"`
4. Compare the current tree with an earlier commit on that copy:
   `uv run --locked python scripts/calc_before_after.py --db /path/outside/repo/copy.db --user <id> --ref <git-ref>`
   It prints leftover, left to spend, safety margin, next-month minimum, lookahead minimum, each card's next payment, and the last full month's spend, from both trees, with deltas. It creates and removes its own temporary git worktree.
5. A nonzero row tells you which figure moved. Bisect `--ref` until the delta appears, then read that commit.
6. Delete the copy afterward. This repo is public: never paste real figures into code, docs, tests or commit messages.
7. If a calculation's meaning changed on purpose, bump `CALC_VERSION` and add a changelog line below.

## Rules for contributors and AI agents

- Never compute a money figure outside the shared layer (`backend/services`). Routers and the frontend display figures; they do not sum them.
- Before adding a figure, find its primitive in the provenance table. If it has none, add a row.
- Add a parity test for any new surface that shows an existing headline concept: it must return the identical value as every other surface, from one fixture.
- Record behavior changes in the decisions log and the calculation changelog; bump `CALC_VERSION` (`backend/services/calc_version.py`).
- Any change that moves a visible number runs `scripts/calc_before_after.py` on a `backup_database()` copy first, and the diff goes in the task or PR notes (synthetic figures only in public text).
- Use synthetic numbers in tests, docs and commit messages.

## Calculation changelog

Hand-bumped alongside `CALC_VERSION`. One line per version, newest last.

- v1: baseline after 2026-11-06 fixes.
- v2: one real-spending rule; refunds net everywhere
- v3: one pending freshness rule
