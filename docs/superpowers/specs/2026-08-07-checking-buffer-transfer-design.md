# Checking-Account Buffer Transfer + Two-Tier Low-Balance Alert

**Date:** 2026-08-07
**Status:** Approved for planning
**Author:** Iris (with Dan)

## Problem

`build_forecast()` (`backend/services/forecast_engine.py`) projects the Main
Checking balance from recurring items alone. Dan's manual spreadsheet
(`Budget.xlsx`, "2026 Forecast" tab) never goes negative because he
periodically moves money from Savings into Checking by hand and records it
there. The app has no equivalent, so its forecast diverges sharply from the
spreadsheet — reproduced for Q3 2026, where the app projects the account
going to **-$3,125** on Jul 25 while the spreadsheet stays positive the whole
quarter. This is the root cause of Dan not trusting the app's forecast.

Dan's actual habit: at the start of each month he checks whether he's about
to run low, and if so pulls money from Savings in **$1,000 increments** — a
round-number habit, not a precisely computed top-up. His stated goal is to
save monthly, but that often gets overridden by this top-up. He does **not**
want the shortfall silently hidden — the projection should still make clear
when he's dipping into a below-target zone, just with the transfer modeled
so the running balance reflects what he actually does next.

Separately, the spreadsheet's own conditional formatting on the running
balance column is a hardcoded `< $100` red flag (confirmed in the underlying
XLSX `dxfId="0"` rule, sqref `B2:B41 G2:G42 L2:L41 Q2:Q41`), which is a
harder "action needed" line than the app's current single configurable
`low_balance_threshold` (set to $500 on Main Checking today). Dan wants both
tiers: $500 as a soft alert, $100 as the threshold that actually triggers a
transfer.

## Goals

1. Model a recurring monthly "top up Checking from Savings" behavior in the
   forecast so projected balances reflect what Dan actually does, without
   requiring him to enter transfers as static recurring items (a fixed
   amount every month is wrong — some months need it, some don't).
2. Surface two distinct low-balance signals on Main Checking:
   - **$500 — alert**: unchanged from today's `low_balance_threshold`,
     purely informational (existing amber quarter-highlighting behavior).
   - **$100 — action**: the threshold that actually triggers a modeled
     buffer transfer.
3. Keep Savings' own projected balance consistent — a modeled transfer into
   Checking must show as a matching outflow from Savings.

## Non-goals (deferred to a follow-up round)

- Needs/Wants/Savings/Charity percent-of-income rollup with health-band
  coloring (spreadsheet Budget tab `F8:F10`).
- Making the Chase Sapphire credit-card estimate ($5,500/mo flat) reflect
  real month-to-month variance.
- Backfilling Planned Expenses for the spreadsheet's Annual Expenses list,
  fixing Savings/Money Market $0 balances, or catching up transaction
  imports past May 1 — these are data-entry tasks for Dan, not app changes,
  and the buffer-transfer feature is only meaningful once Savings has a real
  balance.

## Design

### New model: `BufferTransferRule`

A new table, one row per (from_account, to_account) pair a user configures:

```
buffer_transfer_rules
  id                INTEGER PK
  user_id           INTEGER FK users.id
  from_account_id   INTEGER FK accounts.id   -- e.g. Savings
  to_account_id     INTEGER FK accounts.id   -- e.g. Main Checking
  action_threshold  NUMERIC(14,2)            -- e.g. 100.00 — triggers a transfer
  target_floor      NUMERIC(14,2)            -- e.g. 200.00 — balance must clear this after transfer
  increment         NUMERIC(14,2)            -- e.g. 1000.00 — transfer step size
  check_day         INTEGER                  -- day of month the rule evaluates, e.g. 1
  is_active         BOOLEAN
```

This is deliberately a new table rather than overloading `RecurringItem`:
the transfer amount is conditional and computed at forecast time (zero,
one, or several `increment` steps), not a fixed recurring amount, so it
doesn't fit `RecurringItem`'s "fires for `amount` on `day_of_month`" model.

No new `RecurringType` enum value is needed — categories already exist for
this ("Transfer from Savings" / "Transfer to Savings", category ids 47/41
today), used to label the generated forecast line items.

### Forecast engine change

In `build_forecast()`, add a pass keyed on each account's active
`BufferTransferRule`s:

- On `check_day` of each month in the forecast window, look ahead at the
  running `balance` for the rest of that month (reuse the existing
  day-by-day walk — no separate simulation needed, since `check_day` is
  processed in date order like everything else).
- If the lowest point before the *next* `check_day` would fall below
  `action_threshold`, add `ceil(shortfall / increment) * increment` to
  `balance` on `check_day`, capped so the result is at least `target_floor`.
- Record it as a `ForecastTransaction` named `"Transfer from Savings"`
  (positive, checking) and mirror a matching negative entry when the
  `from_account`'s own forecast is built (so Savings and Checking stay
  consistent when viewed separately).
- This only applies to accounts with at least one active
  `BufferTransferRule`; behavior is unchanged for accounts without one.

Implementation detail to work out in the plan: computing "lowest point
before next check_day" requires either a lookahead sub-pass per month or
restructuring the walk to be month-aware. Keep it simple — a per-month
lookahead pass computed once before the main day loop is preferable to
rewriting the walk's control flow.

### Two-tier low-balance alert

- Reuse `accounts.low_balance_threshold` as the existing "alert" tier
  (already wired into quarter highlighting) — no schema change needed
  there.
- `action_threshold` on `BufferTransferRule` doubles as the "action" tier
  for that account; the Forecast UI should render a distinct (redder) flag
  on any day dropping below it, versus the existing amber for the alert
  tier. If an account has no `BufferTransferRule`, it only shows the
  existing single-tier alert — no regression for accounts without this
  feature configured.

### Settings UI

Add a "Buffer Transfers" section under **Settings → Accounts** (or a new
small settings page) to create/edit `BufferTransferRule` rows: from
account, to account, action threshold, target floor, increment, check day.
Pre-fill Dan's values as the default when creating the first rule: $100 /
$200 / $1,000 / day 1.

## Data flow

```
Settings UI → BufferTransferRule (DB)
                    │
                    ▼
build_forecast() ── monthly lookahead ── inject transfer ForecastTransaction
                    │                           │
                    ▼                           ▼
      Checking day-by-day balance      Savings day-by-day balance
                    │
                    ▼
         Forecast page: two-tier flag (alert @ $500, action @ $100)
```

## Testing

- Unit tests on `build_forecast()` with a synthetic recurring-item set that
  would dip below $100 mid-month, asserting a transfer is injected, sized
  correctly (rounded up to the increment), and the resulting balance is
  ≥ target_floor.
- A case where the dip is small enough that one `$1,000` increment
  overshoots `target_floor` — confirm only one increment fires, not zero.
- A case with no `BufferTransferRule` configured — confirm forecast output
  is byte-for-byte unchanged from today's behavior (regression guard).
- A case verifying the mirrored outflow appears on the `from_account`'s own
  forecast for the same date/amount.

## Open questions for the implementation plan

- Exact lookahead window semantics when `check_day` isn't day 1 of a
  30/31-day range at the edges of the requested forecast window.
- Whether `BufferTransferRule` needs a UI at all for v1, or whether seeding
  Dan's one rule directly via the CLI/DB is enough to validate before
  building settings screens.
