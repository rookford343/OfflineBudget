"""Card spending this month, per card: the one recipe behind Left to Spend
and Available to Spend.

A card whose feed itemizes its charges is read from its posted rows. A card
whose feed sends balances only (the user's Apple Card via SimpleFIN,
2026-10-30) has no rows to sum, so both figures fall back to its balance:
current_balance - balance_due + fresh pending. Both callers use the helpers
here, so the fallback cannot drift between them.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy.orm import Session, joinedload

from backend import models
from backend.services.pending import card_pending
from backend.services.real_spend import classify_card

TRANSACTION_FED_WINDOW_DAYS = 60


def transaction_fed_card_ids(
    db: Session, user_id: int, active_cards: list, as_of: date,
) -> set[int]:
    """Active cards with at least one bank-sync or CSV-imported transaction
    in the 60 days up to `as_of`. A card outside this set has a feed that
    sends balances only, so summing its transactions would read zero; the
    balance-based figure is used instead. Manual rows don't count: a
    hand-entered charge doesn't mean the feed itemizes the rest."""
    ids = [c.id for c in active_cards]
    if not ids:
        return set()
    rows = db.query(models.CreditCardTransaction.card_id).filter(
        models.CreditCardTransaction.user_id == user_id,
        models.CreditCardTransaction.card_id.in_(ids),
        models.CreditCardTransaction.source.in_([
            models.CardTransactionSource.bank_sync, models.CardTransactionSource.csv_import,
        ]),
        models.CreditCardTransaction.date >= as_of - timedelta(days=TRANSACTION_FED_WINDOW_DAYS),
        models.CreditCardTransaction.date <= as_of,
    ).distinct().all()
    return {card_id for (card_id,) in rows}


def balance_based_card_spend(card, as_of: date) -> Decimal:
    """Spend since the last statement for a card with no itemized feed:
    current_balance - balance_due + fresh pending (pending is inside it)."""
    return card.current_balance - card.balance_due + card_pending(card, as_of)


def posted_card_spending(
    db: Session, user_id: int, active_cards: list, as_of: date,
) -> dict[int, Decimal]:
    """Per active card: posted card transactions dated from the 1st of
    `as_of`'s month through `as_of`. Charges add, returns subtract (the
    card convention, positive = charge), and card payments are skipped, per
    the real-spending rule (services/real_spend.classify_card). Pending rows
    live in their own table and are counted separately."""
    totals = {c.id: Decimal("0.00") for c in active_cards}
    if not totals:
        return totals
    rows = db.query(models.CreditCardTransaction).options(
        joinedload(models.CreditCardTransaction.category),
    ).filter(
        models.CreditCardTransaction.user_id == user_id,
        models.CreditCardTransaction.card_id.in_(list(totals)),
        models.CreditCardTransaction.date >= as_of.replace(day=1),
        models.CreditCardTransaction.date <= as_of,
    ).all()
    for t in rows:
        verdict = classify_card(t)
        if verdict.kind == "spend":
            totals[t.card_id] += verdict.amount
    return totals


class CardMonthSpending(NamedTuple):
    by_card: dict[int, Decimal]       # posted for fed cards; balance-based (pending inside) otherwise
    fed_ids: set[int]
    pending_by_card: dict[int, Decimal]

    @property
    def pending_outside(self) -> Decimal:
        """Fresh pending on fed cards, which `by_card` does not include."""
        return sum((p for cid, p in self.pending_by_card.items() if cid in self.fed_ids), Decimal("0"))


def card_month_spending(
    db: Session, user_id: int, active_cards: list, as_of: date,
) -> CardMonthSpending:
    fed_ids = transaction_fed_card_ids(db, user_id, active_cards, as_of)
    by_card = posted_card_spending(db, user_id, active_cards, as_of)
    pending = {c.id: card_pending(c, as_of) for c in active_cards}
    for c in active_cards:
        if c.id not in fed_ids:
            by_card[c.id] = balance_based_card_spend(c, as_of)
    return CardMonthSpending(by_card, fed_ids, pending)
