"""Auto-clear a card statement once synced payments prove it was paid in
full, and flag one that looks stale.

Root cause (confirmed live, 2026-09-30): CreditCard.balance_due is a
hand-entered last-statement amount that bank sync never touches (see
bank_sync_service.py's card sync branch). Once the user pays a statement,
current_balance drops to the real new-cycle balance but balance_due keeps
carrying the old statement total forever:
  - budget_snapshot.py's per-card "new card spending"
    (current_balance - balance_due + pending_charges) goes negative and
    inflates Left to Spend.
  - forecast_engine.py's payment_is_stale rolls a past next_payment_date
    forward and plans the same payment again.

The evidence of payment already exists: card payments and refunds import as
CreditCardTransaction rows with a NEGATIVE amount. This module sums those
credits since the statement closed and only ever clears on FULL coverage --
a partial payment is left alone (reducing balance_due would double-subtract
once a later, real payoff supersedes it); the stale-statement warning below
covers that case instead.
"""
from __future__ import annotations
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from sqlalchemy import func
from sqlalchemy.orm import Session
from backend import models
from backend.services.forecast_engine import (
    _most_recent_occurrence_on_or_before,
    _next_occurrence_on_or_after,
)

logger = logging.getLogger(__name__)

# Full coverage allows for a penny of rounding slop between what's billed
# and what actually posts (card issuers occasionally settle a cent or two
# off a statement total) -- never for a real partial payment, which is
# always far more than a dollar short.
_FULL_COVERAGE_SLOP = Decimal("1.00")


def _clear_pending_if_balance_due_changed(card: models.CreditCard, previous_balance_due: Decimal) -> None:
    """A changed balance_due can only mean fresher data arrived -- whatever
    the new value now is, it makes the manual payment_sent_amount snapshot
    stale. No exact-amount agreement required, unlike transaction dedup.

    Lives here (not routers/credit_cards.py, its original home) so both the
    router's own hand-edit paths (update_card, record_payment) and this
    module's auto-clear can share one copy without a router<->service
    import cycle -- routers/credit_cards.py imports it back from here."""
    if card.payment_sent_pending_sync and card.balance_due != previous_balance_due:
        card.payment_sent_pending_sync = False
        card.payment_sent_amount = None


def statement_close_for(card: models.CreditCard, next_payment_date: date) -> date:
    """The close date of the statement that `next_payment_date` pays off:
    the most recent occurrence of `card.statement_day` strictly before it."""
    return _most_recent_occurrence_on_or_before(
        card.statement_day, next_payment_date - timedelta(days=1),
    )


def reconcile_statement_payment(db: Session, card: models.CreditCard, today: date) -> bool:
    """Clears `card.balance_due` to 0 and advances `next_payment_date` once
    this card's own transaction history proves the last statement was paid
    in full. Returns True if it cleared anything.

    Idempotent: a card already at balance_due == 0 has nothing to clear and
    returns False immediately -- a second call after a successful clear is
    always a no-op.
    """
    balance_due = Decimal(str(card.balance_due or 0))
    if balance_due <= 0:
        return False

    if card.next_payment_date is not None:
        close = statement_close_for(card, card.next_payment_date)
    else:
        close = _most_recent_occurrence_on_or_before(card.statement_day, today)

    credits = db.query(func.sum(-models.CreditCardTransaction.amount)).filter(
        models.CreditCardTransaction.card_id == card.id,
        models.CreditCardTransaction.user_id == card.user_id,
        models.CreditCardTransaction.amount < 0,
        models.CreditCardTransaction.date > close,
        models.CreditCardTransaction.date <= today,
    ).scalar() or Decimal("0")
    credits = Decimal(str(credits))

    if credits < balance_due - _FULL_COVERAGE_SLOP:
        return False  # partial payment -- reducing it here would double-subtract later

    previous_balance_due = balance_due
    card.balance_due = Decimal("0")
    card.balance_due_updated_at = datetime.utcnow()
    advance_after = card.next_payment_date if card.next_payment_date is not None else today
    card.next_payment_date = _next_occurrence_on_or_after(
        card.due_day, advance_after + timedelta(days=1),
    )
    _clear_pending_if_balance_due_changed(card, previous_balance_due)
    # Flush (not commit) -- callers (bank_sync_service's per-link sync,
    # reconcile_all_cards) own the transaction boundary and commit once at
    # their own natural end. Flushing here only makes this card's own write
    # visible to a subsequent read in the same transaction (idempotency
    # re-checks, direct callers/tests reading the card back).
    db.flush()
    return True


def statement_stale_reason(card: models.CreditCard, today: date) -> str | None:
    """Why `card.balance_due` looks like it was already paid and simply
    hasn't been (or can't be) auto-cleared yet -- surfaced as a warning
    rather than acted on, since neither signal alone is proof of full
    payment the way reconcile_statement_payment requires."""
    balance_due = Decimal(str(card.balance_due or 0))
    if balance_due <= 0:
        return None

    current_balance = Decimal(str(card.current_balance or 0))
    pending_charges = Decimal(str(card.pending_charges or 0))
    if current_balance + pending_charges < balance_due - _FULL_COVERAGE_SLOP:
        return "balance_below_statement"

    if card.next_payment_date is not None and card.next_payment_date < today:
        return "due_date_passed"

    return None


def reconcile_all_cards(db: Session, today: date) -> list[str]:
    """One-time catch-up across every active card. Not wired into any
    scheduled job -- the controller runs this once by hand against live
    data; ongoing reconciliation rides along with bank_sync_service instead.
    Returns the names of the cards it cleared."""
    cleared: list[str] = []
    cards = db.query(models.CreditCard).filter(models.CreditCard.is_active == True).all()
    for card in cards:
        if reconcile_statement_payment(db, card, today):
            cleared.append(card.name)
    db.commit()
    return cleared
