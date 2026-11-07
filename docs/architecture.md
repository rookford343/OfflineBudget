# Architecture: where every number comes from

Read this before touching any money calculation. It is the map from a figure on a
screen or in an email to the function that computes it, and the checklist for
consolidating those functions into one shared layer.

Design background: `docs/superpowers/specs/2026-11-06-calculation-consistency-design.md`.
Status: the backend shared layer is built (calculation version 6). Rows marked `-> Plan 2` are
the frontend figures and the Available to Spend rebuild still to move; until they do, the
"function" column is where that math really lives. Everything else points at a function in
`backend/services`.

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
| Leftover | Income minus bills minus planned one-offs plus planned inflows minus committed savings and the Groceries budget for the month: `MonthBase.left_over` | `build_month_base` (services/month_base.py); `leftover_parts` (services/budget_snapshot.py) only reads it | Dashboard Household Snapshot, daily email, Recurring strip |
| Recurring "Left over" | The same `MonthBase.left_over`, with its explain panel | `build_month_summary` (services/month_summary.py) over `build_month_base` | Recurring page strip |
| Left to Spend | Leftover minus card spending this month and pending charges, plus card bills already counted, plus card one-offs | `compute_budget_snapshot` (services/budget_snapshot.py), helpers `_card_spending_this_month`, `_transaction_fed_card_ids` | Dashboard, daily email, /spending/snapshot |
| Weekly / today allowance | Left to Spend or Safety Margin spread over weeks or days left | `_weekly_allowance`, `compute_budget_snapshot` (services/budget_snapshot.py) | Dashboard, email |
| Safety Margin | Lowest balance from today through end of next month (walk without unbilled card bills) minus unbilled card bills plus bills charged so far | `_lookahead_window`, `compute_budget_snapshot` (services/budget_snapshot.py) | Dashboard, email |
| Displayed lowest point (3-month low) | Lowest forecast balance over the lookahead window, walk including unbilled card bills, ignoring locked statement-payoff dips | `_lookahead_window`, `_lookahead_minimum` (services/budget_snapshot.py), `floor_mask` (services/forecast_walk.py) | Dashboard, email |
| Next-month minimum | Lowest forecast balance in the next calendar month | `_next_month_minimum`, `_next_calendar_month_bounds` (services/budget_snapshot.py) | Dashboard, email |
| Risk banner (first breach, amount, status) | First day below the cushion and the window's lowest balance over the standard walk, ignoring locked statement-payoff dips (`floor_mask` computed over the full walk, then cut to today onward, same as the 3-month low). An actual overdraft is never skipped: if only a locked payoff day goes below $0, status is red (`danger`) with that first negative day. Transfer signal reads the whole walk; the suggested top-up is sized from the unmasked window minimum | `walk_risk`, `floor_entries`, `floor_mask` (services/forecast_walk.py), `find_balance_risk`, `risk_status` (services/forecast_engine.py); `/forecast/risk` (routers/forecast.py), `generate_weekly_digest` (services/summary_generator.py) | Risk banner, weekly digest |
| Cushion status (amber/red) | Amber below the cushion, red below $0 | `cushion_status` (services/cushion.py); `lookahead_status` and `risk_status` call it | Dashboard, risk banner, email |
| Cushion | `user.safety_cushion` (default $1,000), the one cushion for the 3-month low, the risk banner and the Wish List | `cushion_for` (services/cushion.py); read by `compute_budget_snapshot`, `effective_cushion` (services/wish_plan.py), `/risk` (routers/forecast.py), the weekly digest | Dashboard, Wish List, risk banner, email |
| Forecast balances | Day-by-day projected checking balance | `build_forecast` (services/forecast_engine.py) | Forecast tab, lows, risk banner, Wish List, upcoming bills, baselines |
| Forecast walk start/flags | The standard walk: starts 45 days before today; purpose `display` (unbilled card bills in) or `safety` (out). Every start gives the same balances from that horizon on | `standard_walk` (services/forecast_walk.py), horizon and bridges in `build_forecast` (services/forecast_engine.py). Custom ranges, with a comment: GET /forecast, /multi-year, /monthly-summary (routers/forecast.py), `build_quarters` | Forecast tab, lows, risk banner, digest, upcoming bills, Wish List, baselines |
| Card payment amount (payoff) | Locked statement payoff, cycle estimate (pending + spent since statement + subscriptions before close + one-offs), second-hop rule, flat estimate, subscription fallback; basis kept on `ForecastTransaction.basis` | `card_payments`, `card_payment_plan` (services/card_payment_model.py); helpers `_card_payoff_date_for_charge`, `_card_subscription_charges`, `_cc_actual_nearby` (services/forecast_engine.py) | Forecast tab, Safety Margin, explain notes (`_cc_basis_note`) |
| Pending charges (fresh) | Hand-typed or synced pending total, ignored when older than 7 days | `card_pending` (services/pending.py), read by the forecast, Left to Spend, available-to-spend, the email and statement checks. The frontend still reads the raw field -> Plan 2 | Forecast, Left to Spend, Credit Cards page, email |
| Social Security boost | Extra take-home per paycheck once the wage base is met | `ss_paycheck_boosts`, `SSWageBaseTracker`, `pay_year_dates` (services/forecast_engine.py); month model calls them | Forecast, Recurring, Leftover |
| Weekend shift | Posting day moves off a weekend; override keyed by natural due date everywhere | `_adjust_for_weekend`, `_matches_schedule`, the override lookup in `build_forecast` (services/forecast_engine.py); `build_month_base` (services/month_base.py) and `upcoming_bills` (services/upcoming_bills.py) key by the natural date | Forecast, Recurring, Upcoming bills |
| Card bill in month | Whether a card-paid recurring bill belongs to a month (quarterly lands whole in its due month) | `is_card_bill_in_month` (services/forecast_engine.py) | Month model, forecast |
| Upcoming bills | Next occurrence per bill with override amounts | `upcoming_bills` (services/upcoming_bills.py), `_next_fire_date` (services/summary_generator.py) | Dashboard card, daily email |
| Real spending (rule) | Whether a row is spend, income, a transfer or a card payment, and its signed amount: card payments and own-account transfers are neither, savings-category rows are transfers, refunds net as negative spend, an income-category debit reduces income | `classify_checking`, `classify_card`, `classified_rows`, `spend_totals` (services/real_spend.py); description checks `is_card_payment`, `looks_like_internal_transfer` (services/spending_helpers.py), `card_matches_description`, `looks_like_card_autopay` (services/card_matching.py) | everything below |
| Category / merchant totals | Real spending per category or merchant over a range | `category_totals_for_range` (= `spend_totals().by_category`), `merchant_totals` (services/spending_helpers.py, both over services/real_spend.py); `spending_breakdown` (services/budget_snapshot.py) | Weekly digest, Budget overview, snapshot explain |
| Spending page charts | Monthly, line items, by category, by card, yearly, rolling, Sankey, merchants | `spending_monthly`, `spending_line_items`, `spending_monthly_by_category`, `spending_by_category`, `spending_by_card`, `spending_yearly_trends`, `spending_rolling_monthly`, `spending_sankey`, `spending_by_merchant` (routers/spending.py), all reading `_spend_rows` / `classified_rows` (services/real_spend.py) | Spending page |
| Budget actuals | Real spend per budget line, split checking / cards; savings-type lines show money moved to savings | `compute_overview` (services/budget_calculator.py) over `classified_rows` and `savings_moved_rows`; `merchant_totals` use in routers/budget.py; `/export/budget-report` (routers/exports.py) reads `compute_overview` | Budget page, budget export |
| Monthly summary / Month in Review | Category totals, debits, credits, month-over-month change, net cashflow | `_month_spending_by_category` (= `spend_totals`), `generate_summary` (services/summary_generator.py) | Monthly email, Month in Review, `/spending/monthly-summary` |
| Weekly digest | Trailing 7 days of spending plus forward balance risk | `generate_weekly_digest` (services/summary_generator.py) | Weekly email, `/spending/weekly-digest` |
| Daily email | Headline figures, cards, upcoming, stale-connection notes | `generate_daily_summary` (services/summary_generator.py) | Daily email |
| Available to Spend | Monthly-frequency income minus bills for the calendar month (no boost, no overrides, refunds dropped) -> Plan 2 rebuild (legacy; allowlisted in the guard test as "rebuilt in Plan 2") | `available_to_spend`, `_committed_card_bills_fired` (routers/spending.py) | Dashboard card |
| Pacer add-backs / discretionary spend | Real spending in a range for the weekly pacer, with recurring card charges added back | `discretionary_spend_checking`, `discretionary_spend_card` (spend verdicts from `classified_rows`, minus recurring bills, Groceries/Savings lines and verified planned transfers), `discretionary_spend_in_range`, `compute_weekly_spendable` (services/spendable_pacer.py) | Dashboard weekly allowance |
| Wish List plan | Earliest safe date to afford a wish, using forecast plus cushion | `build_plan`, `earliest_safe_date`, `effective_cushion` (services/wish_plan.py); `wish_math.py` | Wish List page |
| Planned expense settlement | A planned one-off settles when a matching real charge appears | `auto_settle_planned_expenses`, `settle_after_sync` (services/planned_auto_settle.py) | Month model, forecast, Recurring |
| Tax estimate | Federal, state and FICA estimate from the tax profile | `estimate_taxes` (services/tax_service.py), `tax_estimate`, `tax_summary` (routers/spending.py) | Tax export page |
| Net Position | Checking balances minus card balances due | Dashboard.tsx (client-side `netPosition`) -> Plan 2 (move to backend) | Dashboard |
| Cycle spend | Current balance minus balance due plus pending | Dashboard.tsx (`cycleSpend`) -> Plan 2 | Dashboard, Credit Cards |
| Budget track totals | Committed, flexible, budgeted and spent totals | frontend/src/pages/Budget.tsx, frontend/src/lib/budgetPlan.ts -> Plan 2 | Budget page |
| Spending average | Average of the monthly bars | frontend/src/pages/Spending.tsx (`avg`) -> Plan 2 | Spending page |
| Net worth | Manual assets plus account balances minus card balances and manual liabilities; no shared primitive yet (allowlisted in the guard test) -> Plan 2 | `get_totals`, `capture_snapshot` (routers/networth.py) | Net Worth page |
| Checking balance with pending | Posted balance plus every live pending row, credits and debits alike, only while an active Plaid link keeps the snapshot live; otherwise the posted balance. The same service gives each account's month start and percent change (start = posted balance before this month's actual flow) | `account_balances` (services/account_balances.py) over `checking_balance_with_pending`, `checking_pending_rows`, `pending_snapshot_is_live` (services/pending.py); `GET /accounts/balances` (routers/accounts.py) | Sidebar list, total and % badge, Dashboard Checking card |
| Calculation version | Hand-bumped integer naming the current calculation meaning | `CALC_VERSION` (services/calc_version.py) | Explain panels, changelog below |

## Shared primitives

The provenance table above names the function for every figure; the sections below give each
primitive's rules.

### 1. Month model
`backend/services/month_base.py`. `build_month_base(db, user, year, month, extra_items=None)` returns
a `MonthBase`: every income, bill and one-off occurrence in the calendar month, their totals, and
`left_over`. The Recurring strip (`build_month_summary`), the Dashboard's Leftover
(`leftover_parts`) and the pacer all read it. `card_bill_occurrences(base)` picks the card-linked
bills out of it. Rules:

- **Occurrences:** every active recurring item that fires on a day of the month, except
  `credit_card_payment` items and items excluded from the forecast (`include_in_forecast` false,
  so excluded income is out of Leftover too). `extra_items` are a scenario's never-saved proposals.
- **Overrides** (`BillAmountOverride`) replace the item's amount on its natural due date.
- **Weekends:** the month model lists a bill on its natural due date. The forecast shifts only the
  posting day (see the weekend rule below); the override is keyed by the natural date either way.
- **Quarterly and yearly bills** land whole in their due month (`periodic_due`), never divided.
- **Social Security boost:** `ss_paycheck_boosts` (forecast_engine) adds the extra take-home to each
  paycheck once the wage base is met, so a month with two boosted paychecks counts two boosts.
- **One-offs:** a planned one-off counts on its expected date, or its settled date and actual amount
  once settled. A one-off funded from savings (`funding_account_id`) also adds an equal inflow, so it
  nets to zero. A planned inflow (a refund) adds to Leftover.
- **Leftover:** income - bills - one-off outflows + one-off inflows - committed savings - the
  Groceries budget. Under `pull_from_savings` nothing is set aside for savings.

Parity: `tests/test_month_leftover_parity.py` and `tests/test_parity_headline.py`.

### 2. Card-payment model
`backend/services/card_payment_model.py`. `card_payments(db, user, account, start, end, *,
include_unbilled_card_bills, proposal=None, today=None)` returns the `CardPayment`s (card, due date,
amount, `locked`, `basis`) a checking account pays in the window, card by card;
`card_payment_plan` adds the overdue payoffs. `build_forecast` injects them ("CC Payment" when
locked, "CC Estimate" otherwise) and the snapshot's explain notes read their `basis`
(`_cc_basis_note`). A savings account draws none. Per card, in this order:

- **Locked payoff:** `balance_due` on `next_payment_date`, less any payment already pending at the
  bank. A due date inside the last week still unpaid is *overdue*: still a payoff, re-planned onto
  today after the auto anchor. A due date older than that rolls forward to the next real one. A due
  date reached with nothing due is a paid statement: that month gets no payoff and no flat estimate.
- **Cycle estimate:** the cycle after the payoff. `carried` (running balance + `card_pending` -
  `balance_due`, never below 0) + subscriptions that post before the statement closes - any excess
  of pending payments over the statement. Anchored to today, not the window start. When a stale due
  date lands on the same date, the two merge into one locked line.
- **Second hop:** one more cycle, only for cards with a `monthly_spend_estimate`, from fresh
  pending alone (zero when the pending came from the bank feed: it is already in the carried
  figure).
- **Flat estimate:** `monthly_spend_estimate` on each due date no real payment covers. Without one,
  the card's own subscriptions, routed to the due date of the statement that carries them
  (`subscription_flat`).
- A card with a recurring `credit_card_payment` item, or a payment marked sent and awaiting sync, is
  skipped: something else already pays it.

Pending is always `card_pending(card, today)`; the model never reads `pending_charges`. A balance-only
card (no transaction feed) has no spend rows, so the payments come from its balance.

`include_unbilled_card_bills=False` (Safety Margin's walk) leaves this month's not yet charged card
bills out of the cycle estimate because Safety Margin subtracts them itself
(`cc_budget_total`). Every path honors this: the cycle estimate, and the subscription fallback
(no estimate, or charges past the cycle's close), skip a charge still to come in today's month that is on
that month's card-bills list; before v8 the fallback kept them and took each off twice. That total includes a scenario's proposed card bills (negative ids,
`card_bill_occurrences(base, include_proposed=True)`), which the safety walk drops from the payment
too; before v5 nothing subtracted them. Proposals are not in posted card spending, so they stay out
of `charged_so_far` and the pacer's card-bill take-out. Tests: `tests/test_card_payment_model.py`
(the golden test pins every line the forecast draws for each path).

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
  5. A credit whose description matches a spend debit in the 90 days before it
     (`REFUND_LOOKBACK_DAYS`, whatever the query window) is a refund: negative `spend`. Any other credit is `income`.
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
rebuild (Plan 2).

Savings-type budget lines: their actual is money moved into savings, not spending.
`savings_moved` / `savings_moved_rows` (real_spend.py) sum the transfer verdicts on checking
debits and card charges filed under a savings-type category (a credit pulled back out is not
subtracted). `compute_overview` uses it for those lines only, so the Track Budgets "spent"
figure and `apply_rollover` see it; every spending total still excludes it.

Parity: `backend/tests/test_real_spend.py::test_all_spend_surfaces_agree` and
`backend/tests/test_parity_headline.py` (last month's spend across Month in Review, the Sankey, the
Budget overview and the weekly digest).

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
to one active card (the forecast's rule). `checking_pending_rows` returns every live pending row, credits
included, and `checking_balance_with_pending` is the posted balance plus all of them (decision (a) below).
`account_balances` (services/account_balances.py) wraps it per active account for `GET /accounts/balances`, which
the sidebar and the Checking card read.

One cushion: `cushion_for(user)` (`services/cushion.py`) is read by the 3-month low, `/risk`
(`threshold` is the cushion; `status` is `cushion_status` of the window's lowest balance, skipping locked payoff dips (but not a below-$0 day) via `walk_risk`, so `at_risk`
stays true for both amber and red) and the Wish List. `PUT /wish-list/cushion` writes
`users.safety_cushion`. `accounts.low_balance_threshold` and `wish_settings.cushion` stay in the schema
but nothing reads them. `database.migrate_cushions(db, apply)` folds an old non-default value into
`safety_cushion` (wish setting first, then the primary checking threshold); startup runs it only with
`CUSHION_MIGRATION_APPLY=1`.

### Forecast walk policy
`standard_walk(db, user_id, account_id, as_of, end, purpose="display", **extra)` in
`backend/services/forecast_walk.py` is the walk every consumer reads: Safety Margin and the displayed
lows (`_lookahead_window`), the risk banner (`/forecast/risk`), the weekly digest risk, upcoming bills
(paycheck amounts and dates), the Wish List and the start-of-month baselines. It starts at
`as_of - WALK_LOOKBACK_DAYS` (45). `purpose` picks the flag: `display` keeps this month's not yet
charged card bills in the next card payment (`include_unbilled_card_bills=True`, the Forecast tab);
`safety` leaves them out because Safety Margin subtracts them itself. `extra` passes `overrides` and
`proposal` through. Callers that only want today onward slice with `walk_from`.

The horizon (today - 45 days) lives in `build_forecast`, so every start agrees with the standard walk
from the horizon on:
- A start after the horizon (a calendar month, today, a future month) opens on a bridge walked from
  the horizon, with the caller's flags. A recurring item due since the horizon and still unmatched
  counts as not yet posted.
- A start at or before it (the year views, `/monthly-summary`) walks its history as before, then
  re-seeds at the horizon to the bank balance less the actuals since. An old unmatched projection or an
  old checkpoint stays in the history and stops there.
- A walk that reaches today reverses today's actuals from the bank balance too (it re-applies them).
- The card cycle after a locked payoff is anchored to today, not to the window's start.

The engine reads `date.today()`, so the horizon is today's; pass `as_of` = today.

Callers that keep a custom range say so in a comment: GET /forecast (any client range), `/multi-year`,
`/monthly-summary`, `build_quarters`. `has_unsettled_projection` probes a single day.

**Weekend rule.** A `BillAmountOverride` (statement amount) is keyed by the item's natural due date.
The weekend shift moves only the posting day: a bill due Saturday posts Friday at the override amount.
The forecast looks the override up on the natural date; the month model and upcoming bills key by it
too. For a paycheck the override replaces the base amount and the Social Security boost still applies,
so upcoming bills shows the forecast's paycheck amount as it is.

### Guards and parity tests

Two tests keep the layer from eroding; both run in the normal suite.

- `backend/tests/test_parity_headline.py` builds one fixture (a paycheck past the Social Security
  base, a weekly card bill, a quarterly bill, a savings-funded one-off, a refund, a pending charge)
  and requires the same value from every surface: Leftover (`build_month_base`,
  `/recurring/month-summary`, the snapshot), the lowest point (snapshot vs the `/forecast` endpoint
  with the floor mask), each card's next payment (forecast line, snapshot explain, `card_payments`)
  and last month's spend (Month in Review, Sankey, Budget overview, weekly digest).
- `backend/tests/test_calc_guard.py` is an AST scan of `routers/` and `services/`. It fails on
  `sum(...)` or `+=` / `-=` over `amount`, `pending_charges`, `balance_due` or `current_balance`
  outside the shared-layer modules, and on any read of `.pending_charges` outside `pending.py` and
  the code that writes it. Its allowlist is a module list for the shared layer plus a
  function-by-function list of presentational code and writers, each with a reason; an entry that no
  longer matches a violation fails the test. Adding a module to the allowlist needs a line in this
  document: the shared-layer modules are `month_base`, `real_spend`, `pending`, `forecast_walk`,
  `forecast_engine`, `card_payment_model`, `cushion`, `account_balances` (pending-adjusted balances), `calc_version`, `tax_service` (tax estimates),
  and the writers `bank_sync_service`, `plaid_sync_service`, `import_service` and
  `planned_auto_settle`, plus `statement_reconcile` (matches a statement's credits to synced card
  rows, not a headline figure). The scan also covers SQL `func.sum(...)`.

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
- **Budget export = Budget page.** `/export/budget-report` emits `compute_overview` rows: actuals are positive real spend including cards, budgeted uses the overview's month fallback, savings lines show money moved to savings, income lines show 0. Child rows are named "Parent / Child" and parents carry "Includes subcategories" = yes, because a parent's actual already includes its children. To total the file, sum the top-level rows (no ' / ' in Category); a flagged parent row already includes its subcategories and any spend filed directly on the parent (calculation v7).
- **A pending-adjusted checking balance (decision (a))** is the posted balance plus every live pending row, credits and debits alike, and only while the pending snapshot is live; otherwise it is the posted balance. The sidebar's month percent change is measured from the posted balance before this month's actual (non-planned) transactions, over the absolute start, and is blank when the start is under one cent. The forecast keeps its own card-payment-only pending debits (`checking_pending_debits`).
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
- `tests/test_calc_guard.py` fails on new money sums in routers and services; route the figure
  through the shared layer instead of widening its allowlist.
- Add a parity test for any new surface that shows an existing headline concept: it must return the identical value as every other surface, from one fixture.
- Record behavior changes in the decisions log and the calculation changelog; bump `CALC_VERSION` (`backend/services/calc_version.py`).
- Any change that moves a visible number runs `scripts/calc_before_after.py` on a `backup_database()` copy first, and the diff goes in the task or PR notes (synthetic figures only in public text).
- Use synthetic numbers in tests, docs and commit messages.

## Calculation changelog

Hand-bumped alongside `CALC_VERSION`. One line per version, newest last.

- v1: baseline after 2026-11-06 fixes.
- v2: one real-spending rule; refunds net everywhere; savings budget lines show money moved to savings
- v3: one pending freshness rule
- v4: one walk policy; weekend overrides
- v5: card-payment model shared by forecast and snapshot; scenario card bills in Safety Margin
- v6: one cushion for safety, risk and wish list
- v7: budget export reads the Budget page's actuals
- v8: subscription-fallback cards no longer double-count in Safety Margin; refunds match by lookback, not query window
- v9: risk banner skips locked statement-payment dips, like the 3-month low
