# Suggested & Tracked Manual Transfers — Design

## Problem

The forecast now correctly flags a future negative-balance risk (fixed 2026-08-09), but stops there — it doesn't help Dan act on it. Two concrete gaps:

1. A known future cost (Rivian R2 down payment, ~$21k, target Q3 2026, no firm date yet) isn't modeled at all, so the forecast can't warn about it.
2. When a risk IS detected, there's no way to plan a fix. `BufferTransferRule` (the existing automatic transfer mechanism) is the wrong tool here — it silently assumes a transfer happens on schedule with no confirmation step. OfflineBudget has no bank-write access (SimpleFIN is read-only, and manual transfers happen in Dan's real banking app), so any transfer the app "models" is really a *plan Dan has to go execute himself* — the app must never let that plan fade into the background unconfirmed.

## Goals

- Model the R2 down payment as a `PlannedExpense` so it feeds the existing risk detection.
- When the forecast detects a future risk, automatically compute and surface a suggested one-time transfer (amount rounded to a clean increment) that would resolve it.
- Accepting a suggestion (or manually adding a transfer) creates a `PlannedTransfer`: full CRUD (add/edit/delete), injected into the day-by-day forecast so Dan can verify the plan actually clears the shortfall.
- A persistent reminder — separate from the forecast math — nags Dan on every visit until he confirms he's actually scheduled the transfer in his real bank. The app never assumes this happened on its own.
- Once scheduled, auto-verify against real synced/imported transaction data when it lands, closing the loop without a second manual step.

## Out of Scope

- Spreading a suggested transfer across multiple months (confirmed with Dan: single lump-sum suggestion only, not an amortized plan).
- Any bank-write capability — the app never initiates a real transfer. This is planning and tracking only.
- Retrofitting `BufferTransferRule` to require confirmation — it stays as-is (a separate, already-shipped, fully-automatic mechanism for Dan's existing recurring buffer top-ups). `PlannedTransfer` is a new, distinct concept for one-off, Dan-confirmed transfers.
- A dedicated notification/email for pending transfers — the in-app persistent banner is the only surface for this build.

## Design

### Data model

**New `User.transfer_increment`** (`Numeric(14,2)`, default `1000.00`) — follows the existing pattern of per-user settings as columns on `User` (e.g. `ss_gross_per_paycheck`). Editable in Settings → Preferences. Suggested transfer amounts round UP to this increment (`ceil(shortfall / increment) * increment`) so a suggestion is always a clean, bankable number, not "$21,347.82."

**New `PlannedTransfer` table**:
```
id, user_id, from_account_id (FK accounts), to_account_id (FK accounts),
amount (Numeric 14,2), target_date (Date),
status (Enum: pending | scheduled | verified), suggested (Boolean),
notes (Text, nullable), verified_transaction_id (FK transactions, nullable),
created_at, updated_at
```
- `pending`: newly suggested or manually added — not yet acted on.
- `scheduled`: Dan clicked "Mark Scheduled" — he's confirmed he initiated it in his real bank.
- `verified`: the system found a matching real transaction (see Verification below) and closed the loop automatically.

### Suggestion generation

Extends `find_balance_risk` (unchanged) with a new check run alongside it: when a risk is found and no *active* (`pending` or `scheduled`) `PlannedTransfer` already has a `target_date` within a few days of the risk date on the same `to_account_id`, compute:
- `amount = ceil(risk_shortfall / user.transfer_increment) * user.transfer_increment`, where `risk_shortfall` is enough to bring the projected minimum back to the account's `low_balance_threshold` (or 0 if unset) — reuses the same threshold `find_balance_risk` already takes.
- `target_date` = a few days before the risk date (enough buffer for a real bank transfer to clear).
- `from_account_id` = the user's savings-type account (if exactly one exists; if ambiguous, the suggestion prompts Dan to pick when accepting).

Surfaced via a new `suggested_transfer` block on the existing `GET /forecast/risk` response (`ForecastRisk` schema already carries transfer fields from the `BufferTransferRule` integration — this adds parallel `suggested_*` fields so the two are never conflated). Frontend: extends the existing `RiskBanner` component with an "Accept" / "Dismiss" action.

### Forecast integration

`build_forecast` gains a new injection block, following the exact pattern already used for `BufferTransferRule` schedules (`incoming_transfer_schedules`/`outgoing_transfer_schedules` in `forecast_engine.py`): every `PlannedTransfer` with status `pending` or `scheduled` (not yet `verified`, since a verified one's real transaction is already in the actuals feed and would double-count) injects a `ForecastTransaction(is_transfer=True)` on both accounts on its `target_date`. This is why "accept the suggestion" immediately shows the shortfall resolved in the chart — the whole point of the "forecast reflects it, reminder still nags" design decision.

### Reminder callout

New component (Dashboard + Forecast page, mirroring `RiskBanner`'s placement pattern): lists every `PlannedTransfer` with status `pending` or `scheduled`, each row showing amount, from/to account, target date, and inline actions — Mark Scheduled / Edit / Delete. Renders on every page load; there is no auto-dismiss or snooze, matching Dan's explicit requirement that the app never let this go quiet on its own. A `scheduled` row stays visible too (just re-labeled, e.g. "Scheduled — waiting to verify") so Dan can still see and edit/delete it until it's actually verified.

### Verification

A new check (piggybacked on the existing daily bank-sync job, `_run_bank_sync` in `main.py`, so it runs on the same cadence real data arrives) scans `scheduled` `PlannedTransfer`s: for each, look for a real `Transaction` on `to_account_id` with `amount` within the same clean-increment tolerance and `date` within a few days of `target_date`. On match: set status to `verified`, store `verified_transaction_id`, and the forecast injection stops for that transfer (the real transaction now covers it). This reuses the same "fuzzy amount + date window" matching idea already used elsewhere in this codebase (e.g. `_try_auto_match` in `import_service.py`) rather than inventing a new algorithm.

## Data Flow

```
Dan adds "Rivian R2 Down Payment" as a PlannedExpense ($21,000, target date in Q3 2026)
  -> feeds into build_forecast (already wired) -> find_balance_risk detects the future dip

GET /forecast/risk also runs the new suggestion check
  -> no active PlannedTransfer covers this risk -> computes suggested_transfer
  -> RiskBanner shows "Suggested: move $22,000 Savings -> Checking by <date> [Accept] [Dismiss]"

Dan clicks Accept -> POST creates a PlannedTransfer (status=pending, suggested=true)
  -> build_forecast injects it -> chart/risk banner shows the shortfall resolved
  -> persistent reminder banner appears on Dashboard + Forecast: "Move $22,000 ... [Mark Scheduled] [Edit] [Delete]"

Dan actually makes the transfer in his real bank, clicks "Mark Scheduled"
  -> status=scheduled -> reminder banner re-labels but stays visible

Next daily bank sync imports the real transfer transaction
  -> verification check matches it to the PlannedTransfer -> status=verified
  -> reminder banner drops this row -> forecast injection stops (real transaction now covers it)
```

## Error Handling

- No savings-type account exists, or more than one: suggestion is still generated but `from_account_id` is left unset; Accept requires picking one (never guesses wrong and silently moves the wrong account's money in the *model*).
- `transfer_increment` unset or zero: falls back to the model default (1000), never divides by zero.
- Verification finds no match: `PlannedTransfer` stays `scheduled` indefinitely — no auto-expiry, matches "never assume it happened."
- A `PlannedTransfer` deleted while `verified`: the real transaction it matched is untouched (no cascade delete of actual financial history).

## Testing

- Suggestion math: given a risk shortfall, confirm the rounded-up amount matches `transfer_increment` for several increment values (1000 default, and a custom one).
- `build_forecast` injection: a `pending`/`scheduled` `PlannedTransfer` shows up as a transfer transaction on `target_date` on both accounts; a `verified` one does not (avoiding double-count with its now-real transaction).
- Verification matching: a real transaction within the amount/date tolerance flips status to `verified` and stores the link; one outside tolerance does not.
- Reminder callout: `pending` and `scheduled` both render; `verified` does not.
- Frontend Settings: `transfer_increment` field persists and the suggestion math actually uses the updated value (integration-level, not just a schema test).

## Decisions

- 2026-08-09: R2 down payment target date modeled as a rough placeholder within Dan's stated Q3 2026 (Sept/Oct-leaning) window via the existing `PlannedExpense` CRUD — no new "someday/undated" concept needed; Dan can drag the date later as Rivian firms it up.
- 2026-08-09: Suggestions are single lump-sum transfers, not spread across months — simpler to compute, and matches Dan's stated preference.
- 2026-08-09: Suggested amounts round up to a per-user configurable increment (default $1,000) — matches how Dan actually moves money and generalizes for other users of this app.
- 2026-08-09: The forecast shows an accepted transfer as resolved immediately (optimistic), while the separate reminder banner is the actual accountability mechanism — deliberately decoupled so Dan can "check the plan" without the app ever assuming the real-world action happened.
- 2026-08-09: Verification is automatic (matched against real synced data) rather than a second manual "Verify" click, once "Mark Scheduled" has already been an explicit confirmation step.
- 2026-08-09: `BufferTransferRule` is untouched — this is a parallel, distinct mechanism for one-off Dan-confirmed transfers, not a replacement.

## Next Step

Spec awaiting Dan's review. Once approved, invoke `writing-plans` to produce the implementation plan, then execute via `subagent-driven-development` (same process used for the SimpleFIN bank sync build).
