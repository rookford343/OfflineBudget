# Second-Hop Credit Card Carry-Forward — Design

## Problem

`forecast_engine.py`'s per-card payoff logic already derives one real,
evidence-based cycle beyond today (`derived_due`/`derived_amount`: current
balance minus what's already billed, plus subscriptions still due before
close). Every cycle after that falls straight to the card's flat
`monthly_spend_estimate`, injected once per month on the due date.

Verified against Dan's own spreadsheet (`data/transaction_files/Budget.xlsx`,
`2026 Forecast` sheet): this gap is real but narrower than "every future
cycle should chain." Only the cycle immediately after `derived_due` needed
a fix — Dan edited exactly one cell (`Q13`, the October 26 Credit Card
Payment row) to replace its `Budget!M2` (flat estimate) term with
`'2026 Overview'!B19`, his hand-tracked live "pending charges" total
($134.31 as of 2026-08-28). The cycles after that (`Q24`/November,
`P35`/December) still use the original flat-estimate formula, untouched.
September's own cycle (`K33`) is a fully hand-typed number, not a formula —
consistent with `derived_due` already being the app's best real answer for
the *first* upcoming cycle.

So the fix is: extend the existing real-data derivation exactly one hop
further, seeded by live `pending_charges` instead of a second flat
estimate. Nothing beyond that second hop changes.

## Why `pending_charges`, not another guess

`pending_charges` already exists on `CreditCard` and already feeds
`derived_amount` for the *first* cycle (`carried = current_balance +
pending_charges - balance_due`). Today it sits at `$0` in the database —
Dan tracks the real number ($134.31) by hand in the spreadsheet only,
never having had a reason to enter it into the app. The field is already
editable on the Credit Cards page's add/edit form; no new UI is needed to
capture it.

Confirmed with Dan (2026-08-28): for the second-hop cycle, `pending_charges`
**replaces** the flat estimate outright — it is not blended with
`monthly_spend_estimate`, and no subscription/"upcoming" term is added on
top. This mirrors how Dan updates his own spreadsheet: a rough, real,
currently-known number now, hand-raised closer to the due date as more
spend actually posts (the same way September's row became a hardcoded
exact figure once known). If `pending_charges` is `0`, the second-hop
injection is skipped entirely and that month falls through to the existing
flat-estimate path unchanged.

## Data model

One new column on `CreditCard`, added via the existing idempotent
`ALTER TABLE` convention in `backend/database.py`'s `upgrade_schema()`:

```python
"ALTER TABLE credit_cards ADD COLUMN pending_charges_updated_at DATETIME",
```

`models.CreditCard` gains a matching `Mapped[datetime | None]` field.
`schemas.CreditCardOut` exposes it read-only (same pattern as the payment
marker's fields) — it is only ever set by the two write paths below, never
accepted directly in a request body.

## Freshness: stamping and auto-clear

**Stamping.** `routers/credit_cards.py`'s `update_card` (the generic
`PATCH`, already the only write path for `pending_charges` — confirmed via
`grep`, the field has exactly one writer today) captures
`card.pending_charges` before the `setattr` loop runs, same as the payment
marker's `_clear_pending_if_balance_due_changed` pattern. After the loop,
if the value changed, stamp `card.pending_charges_updated_at =
datetime.utcnow()`. If the new value is `0`, clear the timestamp to `None`
instead (nothing pending, nothing to date).

**Auto-clear on sync.** `bank_sync_service.py`'s credit-card-link branch,
immediately after the existing `card.current_balance = -balance` line
(same site as the payment marker's C2 fix): if `pending_charges > 0`, zero
it and clear `pending_charges_updated_at`. Bank sync just refreshed
`current_balance` with everything the bank knows as of now, so a manually
tracked "extra, not-yet-synced" pending figure is stale by definition the
moment a fresher real number arrives — exactly the reasoning the payment
marker's own auto-clear already applies to `balance_due`.

**7-day staleness at read time.** No cron job, no background sweep —
matches this codebase's existing lazy, compute-time-check pattern (the
payment marker's own auto-clear is likewise triggered only when something
reads/writes the field, never on a schedule). Add a small helper in
`forecast_engine.py`:

```python
def _fresh_pending_charges(card: "models.CreditCard", today: date) -> Decimal:
    if not card.pending_charges or card.pending_charges <= 0:
        return Decimal("0")
    if card.pending_charges_updated_at is None:
        # Existing rows predate this feature, or the timestamp was cleared
        # by a sync/zeroing — a nonzero value with no known age is treated
        # as already stale rather than silently trusted.
        return Decimal("0")
    if (today - card.pending_charges_updated_at.date()).days > 7:
        return Decimal("0")
    return Decimal(str(card.pending_charges))
```

This helper is used for the **second-hop cycle only** (below). The
existing first-cycle `carried` calculation keeps reading
`card.pending_charges` directly, unchanged — freshness enforcement is new
scope, and widening it to the first cycle's already-shipped, already-tested
formula is out of scope for this change.

## Computation — the second hop

Immediately after `forecast_engine.py`'s existing `derived_due`/
`derived_amount` block (the code that already exists, unchanged), compute
one further cycle:

```python
second_close = _next_occurrence_on_or_after(
    card.statement_day, derived_due + timedelta(days=1)
) if derived_due is not None else None
second_due = (
    _next_occurrence_on_or_after(card.due_day, second_close + timedelta(days=1))
    if second_close is not None else None
)
second_amount = _fresh_pending_charges(card, today) if second_due is not None else Decimal("0")
```

`second_close`/`second_due` only exist when `derived_due` itself exists —
there is no real second-hop cycle to compute if there was no real
first-hop cycle to anchor it to (a card with no `current_balance`/
`balance_due` signal at all skips both, falling through entirely to the
flat-estimate path, unchanged from today).

Injection, mirroring the existing `derived_due` injection at
`cc_estimates_by_date` (not `cc_payments` — this is still an estimate, not
a locked/actual figure, same distinction the code already draws for
`derived_due`):

```python
if (
    second_due is not None
    and start_date <= second_due <= end_date
    and second_amount > 0
):
    cc_estimates_by_date.setdefault(second_due, []).append((card.name, second_amount))
```

**Suppression.** `_covered_by_real_payment` currently checks only
`derived_due`'s month against `next_payment`'s month. Extend it to also
match `second_due`'s month — but only when `second_amount > 0`. Without
that guard, a stale or zero `pending_charges` would suppress the flat
estimate for that month (because `second_due` is still set) while
injecting nothing to replace it, silently dropping the month's money
entirely — the same failure class the `derived_amount > 0` guards
elsewhere in this file already exist to prevent. Final version:

```python
def _covered_by_real_payment(when: date) -> bool:
    if derived_due is not None and (derived_due.year, derived_due.month) == (when.year, when.month):
        return True
    if second_due is not None and second_amount > 0 and (second_due.year, second_due.month) == (when.year, when.month):
        return True
    return (
        next_payment is not None
        and next_payment.year == when.year
        and next_payment.month == when.month
        and bool(card.balance_due and card.balance_due > 0)
    )
```

Cycles beyond the second hop (three or more statement closes out) are
untouched — they keep using `monthly_spend_estimate` exactly as they do
today, matching Dan's own unedited November (`Q24`) and December (`P35`)
spreadsheet cells.

## Non-goals

- No change to the first cycle's `derived_due`/`derived_amount` formula or
  its existing tests.
- No blending of `pending_charges` with `monthly_spend_estimate` for the
  second hop — confirmed explicitly, it replaces the estimate outright.
- No subscription/"upcoming" term added to the second hop's amount.
- No third-hop or open-ended recursive chain — scope is exactly one
  additional cycle past what already exists.
- No background job or scheduled sweep for the 7-day staleness rule —
  enforced only where the value is read (forecast computation).

## Testing

Following `test_forecast_spreadsheet_gaps_20260814.py`'s established
pattern:

- Second-hop amount equals fresh `pending_charges` when set and recent.
- Second-hop injection skipped entirely when `pending_charges` is `0`
  (falls through to flat estimate for that month, unchanged).
- Second-hop injection skipped when `pending_charges_updated_at` is more
  than 7 days old (falls through to flat estimate for that month).
- Second-hop injection skipped when `pending_charges_updated_at` is `None`
  even though `pending_charges > 0` (pre-existing-row / cleared-timestamp
  case).
- Flat `monthly_spend_estimate` still fires normally for the third hop and
  beyond, unaffected by any of the above.
- `_covered_by_real_payment` suppression: flat estimate does not
  double-fire in the second hop's month when a fresh pending amount was
  injected there.

`backend/tests/test_cc_payment_injection.py`: no changes expected, but run
to confirm no regression (it exercises the first-cycle injection paths
this change sits directly next to).

`backend/routers/credit_cards.py` / `test_credit_cards.py` (or wherever
`update_card` is currently tested): `pending_charges_updated_at` stamps on
a real change, clears when `pending_charges` is set back to `0`.

`backend/tests/test_bank_sync_service.py`: a card with `pending_charges >
0` gets both `pending_charges` and `pending_charges_updated_at` cleared
when a sync updates its `current_balance`, following the same shape as
the existing `test_a_bank_sync_clears_a_pending_marker` test for the
payment-marker feature.

## License / scope note

Entirely original to this codebase.
