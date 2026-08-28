# "Payment Sent, Pending Sync" Marker — Design

Second attempt at this feature. First attempt (2026-08-27) was retracted
when `record_payment`/the Credit Cards page's Record Payment button turned
out to already exist. That was the wrong call: today (2026-08-28) proved
the gap is real. The real SimpleFIN-synced Chase autopay landed overnight
at $9,098.94 — not the $9,273.76 Dan had recorded as a workaround the day
before. The exact-amount-match dedup logic didn't recognize them as the
same event (by design — it deliberately never fuzzy-matches amounts, to
avoid conflating two genuinely different charges), so both sat in the
ledger as real transactions, double-subtracting checking until manually
found and deleted.

## Problem

`record_payment` is right for *logging a payment that already definitely
happened* — it creates a permanent, real `Transaction`. It's the wrong tool
for *"I know a payment is about to clear, don't know its exact final
amount yet, and want the forecast to reflect that provisionally until the
real sync confirms it"* — using it for that creates a real ledger entry
that can only be exactly matched by luck, and mismatches sit as silent
duplicates until someone notices the balance is wrong.

## Vision

The moment Dan knows a card payment is imminent or has happened, he can
flag it without committing a guessed amount to the permanent ledger. The
forecast and today's balance immediately reflect it. Once the real
transaction syncs in — whatever its exact amount turns out to be — the
flag steps aside cleanly on its own, with nothing to dedupe and nothing
left behind to find and delete later.

## Data Model

Two new columns on `CreditCard`, added via the existing idempotent
`ALTER TABLE` convention in `backend/database.py`'s `upgrade_schema()`
(same mechanism `pending_charges` used — no Alembic migration):

```python
"ALTER TABLE credit_cards ADD COLUMN payment_sent_pending_sync BOOLEAN DEFAULT 0",
"ALTER TABLE credit_cards ADD COLUMN payment_sent_amount NUMERIC(14,2)",
```

`payment_sent_amount` is a snapshot of `balance_due` captured at the
moment Dan flags the card — not a live reference to it. That snapshot is
exactly what makes the auto-clear condition below work: once the real
sync updates `balance_due` to anything else, the snapshot and the live
value diverge, which is the signal.

`models.CreditCard` gains matching `Mapped[bool]` (default `False`) and
`Mapped[Decimal | None]` fields. `schemas.CreditCardOut` exposes both
(read-only from the general shape's perspective — they're only ever set
via the two dedicated endpoints below, never through the generic
`PATCH /credit-cards/{id}` body).

## Computation — single injection point

`services/forecast_engine.py:592` is where `account.current_balance` seeds
the entire day-walk — both today's actual balance and every future
projection derive from this one line. Re-confirmed after yesterday's three
fixes: `budget_snapshot.py` has no independent read of the checking
account's raw `current_balance` (its figures route through
`_lookahead_minimum` → `build_forecast`), so this remains the one place
that needs to change.

```python
current_balance = Decimal(str(account.current_balance))
```

becomes (only when `account.type == models.AccountType.checking` — a
card's payment is only ever sent from checking, matching the existing
`injects_card_bills` guard already used elsewhere in this file for the
same reason):

```python
current_balance = Decimal(str(account.current_balance))
if account.type == models.AccountType.checking:
    pending_sent = db.query(models.CreditCard).filter(
        models.CreditCard.user_id == user_id,
        models.CreditCard.is_active == True,
        models.CreditCard.payment_sent_pending_sync == True,
    ).all()
    for card in pending_sent:
        current_balance -= Decimal(str(card.payment_sent_amount or 0))
```

This runs before the existing past-actuals reversal, so it flows correctly
into both the `start_date < today`, `start_date == today`, and
`start_date > today` branches without touching any of them.

**No change needed in `_lookahead_minimum`'s payoff-skip logic.** Verified
against today's fix (`_is_payoff_day`, matching `is_cc_locked` or a real
actual transaction's description against the card): the marker doesn't
create a discrete transaction or a dip-then-recover shape on any single
day — it's a flat reduction to the opening balance that every subsequent
day inherits equally. It isn't "an event to skip past," it's a correction
to what the true starting balance is. It should flow into the floor
calculation like any other accurate balance information, not be excluded
from it.

## Reconciliation (auto-clear)

No transaction matching of any kind — that's the entire point of this
being a marker instead of a ledger entry. The flag clears itself the
moment `card.balance_due` changes from the value captured in
`payment_sent_amount` at flag-time:

```python
if card.payment_sent_pending_sync and card.balance_due != card.payment_sent_amount:
    card.payment_sent_pending_sync = False
    card.payment_sent_amount = None
```

`balance_due` only ever changes via two real code paths in
`routers/credit_cards.py`:

- `record_payment` (line 129: `card.balance_due = max(0, balance_due -
  amount)`) — add the auto-clear check immediately after this line, since
  it's a single, unconditional assignment.
- `update_card` (lines 79-91, the generic `PATCH`) — sets arbitrary fields
  via `setattr(card, field, value)` in a loop over the request body, so
  `balance_due` isn't a single assignment to hook after. Capture
  `card.balance_due` before the loop runs, then after it, compare against
  the captured value and run the auto-clear check if they differ.

A changed value, whatever it now is, means fresher data has arrived and
the manual adjustment is stale by definition — this needs no exact-amount
agreement with anything, which is exactly the property that failed
yesterday.

## API

Two new endpoints on the existing `credit_cards` router, alongside
`payment`/`delete`:

- `POST /credit-cards/{id}/mark-payment-sent` — sets
  `payment_sent_pending_sync = True`, `payment_sent_amount = card.balance_due`.
  400s if `balance_due` is 0 (nothing to mark) or the flag is already set.
- `POST /credit-cards/{id}/clear-payment-sent` — manually clears both
  fields, for flagging in error or wanting to revert before the real sync
  catches up.

## UI

One toggle on the Credit Cards page (`frontend/src/pages/CreditCards.tsx`),
next to the existing `$` Record Payment button on each card: "Mark payment
as sent" when unset, "Payment sent — awaiting sync (undo)" when set.
Mutation invalidates `["credit-cards"]`, `["accounts"]`,
`["forecast-quarters"]`, and `["forecast-multi-year"]` on success — the
same invalidation set the earlier planned-expense cache-staleness fix
established, so the balance updates everywhere immediately rather than
requiring a manual refresh.

## Testing

Following this repo's established pytest pattern for `forecast_engine.py`
and `budget_snapshot.py` (see `test_forecast_spreadsheet_gaps_20260814.py`):
a fixture card with `payment_sent_pending_sync=True` and a known
`payment_sent_amount`, asserting the forecast's opening balance for the
linked checking account is reduced by exactly that amount; a second test
asserting a `balance_due` change (via a simulated `record_payment` call)
clears the flag and the adjustment no longer applies. API tests for both
new endpoints follow `test_cc_payment_injection.py`'s request/response
pattern.

## License / scope note

Entirely original to this codebase.
