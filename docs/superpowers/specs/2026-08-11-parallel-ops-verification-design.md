# Parallel Ops Verification — Design

**Status:** Approved by Dan 2026-08-11 (via question round in chat).

## Problem

Dan doesn't fully trust three areas of OfflineBudget: Forecast, Transactions
(bank-sync data coming in), and Household Snapshot. He wants a way to flag a
specific number that looks wrong, right where he sees it, with what he
expected instead — captured somewhere I can review later and go fix, rather
than a one-off chat message every time.

## Decisions

- **New Settings toggle** ("Parallel Ops") turns this on/off. Off by
  default — it's a debugging aid, not a permanent UI fixture.
- **Inline flag icon**, not a periodic nudge. When Parallel Ops is on, a
  small flag/thumbs-down icon appears next to the relevant numbers on
  Forecast, Transactions, and Household Snapshot. Click it any time
  something looks wrong — fully passive, no prompts, no nagging.
- **Structured correction**: the form captures an expected value (decimal,
  optional) plus a free-text note. Structured beats free-text-only because
  it lets me diff "what the app showed" against "what you expected"
  directly instead of parsing a number out of prose every time.
- **Context is captured automatically**, not typed by Dan — the exact
  values the app was showing at flag time, so the entry stays meaningful
  even after the underlying data changes.

## Data model

New table `verification_flags`:

| Column | Type | Notes |
|---|---|---|
| id | int, PK | |
| user_id | int, FK | |
| feature | enum | `forecast` \| `transactions` \| `household_snapshot` |
| reference_type | str, nullable | e.g. `"transaction"`, `"account"`, `"card"` — what `reference_id` points at |
| reference_id | int, nullable | e.g. transaction id, account id |
| observed_json | text (JSON) | snapshot of what the app displayed (values, not just ids — see below) |
| expected_value | Decimal, nullable | what Dan says it should be |
| note | text, nullable | |
| status | enum | `open` \| `resolved`, default `open` |
| created_at | datetime | |
| resolved_at | datetime, nullable | |

`observed_json` shape per feature (loose, feature-specific — not a shared
schema, since the three features show fundamentally different things):
- `household_snapshot`: `{"left_to_spend": ..., "not_saving": ..., "left_to_spend_weekly": ..., "not_saving_weekly": ..., "as_of": "..."}`
- `forecast`: `{"account_id": ..., "as_of": "...", "projected_balance": ..., "risk_date": ..., "risk_amount": ...}`
- `transactions`: `{"transaction_id": ..., "date": "...", "amount": ..., "description": ..., "category": ...}`

## UI touchpoints

- **Household Snapshot** (Dashboard card): one flag icon on the card
  header. The form has two optional expected-value fields (Left to Spend,
  Not Saving) plus a note — matches how Dan's spreadsheet correction
  showed up today (both numbers off together).
- **Forecast page**: flag icon near the balance-risk callout / chart
  summary for the account being viewed. Captures account + as-of date +
  displayed projected balance/risk date.
- **Transactions**: flag icon per row (visible on hover when Parallel Ops
  is on). Captures that transaction's id, date, amount, description,
  category as displayed.

## Review surface

New Settings tab, **"Verification Feedback"** — a new tab rather than
folding into an existing one, since this is a data-quality queue, not a
household-membership or preferences concern. Lists open flags grouped by
feature, each row showing observed values, expected value, note, and when
it was flagged. Dan (or I, reading the same table) can mark a flag resolved
once a fix lands and he's confirmed it. No auto-resolution — there's no
reliable way to detect "this exact instance is now correct" without Dan
re-checking, so resolution stays manual (YAGNI).

I read the queue directly against the DB (or a simple `GET
/verification-flags` endpoint) between sessions — no separate export step
needed.

## Out of scope

- Auto-resolving flags when I believe the underlying bug is fixed.
- Notifications/reminders about open flags — it's a list we both check when
  working the area, not a nagging system (would undercut "fully passive").
- Extending Parallel Ops to other pages beyond the three named here.

## Today's investigation (Household Snapshot)

Not part of the feature build, but the concrete example that prompted it:
Dan's spreadsheet shows Left to Spend $945.85 / Not Saving $671.91
(updated 8/11); the app showed Left to Spend -$6,999.59.

A live re-sync (triggered during this investigation) confirms Chase
Sapphire's $10,528.54 balance is accurate per Chase itself right now — not
stale, not a sync bug. The likely root cause is in
`backend/services/budget_snapshot.py`: `left_to_spend` (line 169) still
subtracts the **entire** card balance (`card_balances`), the same
pre-live-sync assumption that was already identified as broken and fixed
for `not_saving` on 2026-08-09 (see that function's own comment: before
live bank sync, `current_balance` tracked `balance_due` closely enough that
subtracting the full balance was harmless; live sync now keeps
`current_balance` accurate to the minute, so the gap is real and material).

Swapping `card_balances` for the same `new_spending_total` term already
used in `not_saving` gets closer ($1,955.33 vs. $945.85) but not exact —
a second factor is still unaccounted for. Not shipping a guessed fix on a
financial formula that's still off by ~$1,000. Once this feature exists,
logging this exact case through it (or Dan sharing the spreadsheet's actual
Left to Spend cell formula) is the fastest path to closing the gap
precisely instead of iterating blind.
