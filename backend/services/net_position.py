"""Net Position and each card's cycle figures, computed once on the backend.

Net Position is the checking balances minus the card statements due; the
Dashboard's receipt (explain) is built from the same variables, so it replays
to the displayed figure. The card cycle figures read pending through
`card_pending`, never the raw hand-typed field (docs/architecture.md,
"Net Position" and "Cycle spend").
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from backend import models, schemas
from backend.services.explain import ExplainBuilder
from backend.services.pending import card_pending

ZERO = Decimal("0")


def card_cycle_figures(card: models.CreditCard, today: date) -> tuple[Decimal, Decimal, Decimal]:
    """(pending_effective, spent_this_cycle, after_pending) for one card.

    spent_this_cycle is what the card has gained since the statement closed,
    floored at 0 (a stale balance_due larger than the balance reads as 0).
    after_pending is the balance as if pending charges go through.
    """
    balance = Decimal(str(card.current_balance))
    due = Decimal(str(card.balance_due))
    pending = card_pending(card, today)
    return pending, max(ZERO, balance - due + pending), balance + pending


def net_position(db: Session, user_id: int) -> schemas.NetPositionOut:
    accounts = db.query(models.Account).filter(
        models.Account.user_id == user_id,
        models.Account.is_active == True,
        models.Account.type == models.AccountType.checking,
    ).order_by(models.Account.id).all()
    cards = db.query(models.CreditCard).filter(
        models.CreditCard.user_id == user_id,
        models.CreditCard.is_active == True,
    ).order_by(models.CreditCard.id).all()
    checking_total = sum((Decimal(str(a.current_balance)) for a in accounts), ZERO)
    cards_due_total = sum((Decimal(str(c.balance_due)) for c in cards), ZERO)
    net = checking_total - cards_due_total
    explain = (
        ExplainBuilder("Net Position")
        .start("Checking", checking_total, children=[
            schemas.ExplainChild(label=a.name, amount=Decimal(str(a.current_balance))) for a in accounts
        ])
        .subtract("Card statements due", cards_due_total, children=[
            schemas.ExplainChild(label=c.name, amount=Decimal(str(c.balance_due))) for c in cards
        ])
        .build(net)
    )
    return schemas.NetPositionOut(
        checking_total=checking_total, cards_due_total=cards_due_total,
        net_position=net, explain=explain,
    )
