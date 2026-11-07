"""Every headline figure with its explain tree, collected for change history.

`collect_headline_metrics` is the one place that lists which figures history
records; each reading is the value and receipt another surface already shows
(the snapshot, the month summary, Available to Spend, the pending-adjusted
checking balance, each card's next payment), never a second recipe.
`collect_sources` records what those figures were computed from (pending rows
and the newest row ids) so a later diff can say what changed underneath.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend import models, schemas
from backend.services.available_to_spend import available_to_spend
from backend.services.budget_snapshot import _cc_basis_note, compute_budget_snapshot
from backend.services.card_payment_model import card_payments
from backend.services.explain import ExplainBuilder
from backend.services.month_summary import build_month_summary
from backend.services.pending import checking_pending_rows
from backend.services.primary_account import primary_checking
from backend.services.real_spend import active_cards
from backend.schemas import ExplainChild

ZERO = Decimal("0")
CARD_WINDOW_DAYS = 75

# Fixed headline keys, in recording order. Card payments follow as
# `card_payment:<card id>`, one per active card.
METRIC_KEYS: tuple[str, ...] = (
    "leftover", "left_to_spend", "spendable_week", "spendable_today",
    "safety_margin", "safety_margin_week", "safety_margin_today", "next_month_minimum",
    "lookahead_minimum", "available_to_spend", "checking_balance",
)


@dataclass(frozen=True)
class MetricReadingData:
    key: str
    label: str
    value: Decimal
    explain: schemas.Explanation


def _checking_balance_reading(
    db: Session, account: models.Account, as_of: date,
) -> MetricReadingData:
    posted = Decimal(str(account.current_balance))
    rows = checking_pending_rows(db, account, as_of)
    builder = ExplainBuilder("Checking balance").start("Posted balance", posted)
    pending = ZERO
    if rows:
        children = [
            ExplainChild(label=r.description, amount=Decimal(str(r.amount))) for r in rows
        ]
        pending = sum((c.amount for c in children), ZERO)
        if pending:
            builder.add("Pending", pending, children=children)
    value = posted + pending
    return MetricReadingData(
        "checking_balance", "Checking balance", value, builder.build(value),
    )


def _card_payment_readings(
    db: Session, user: models.User, account: models.Account, as_of: date,
) -> list[MetricReadingData]:
    payments = card_payments(
        db, user, account, as_of, as_of + timedelta(days=CARD_WINDOW_DAYS),
        include_unbilled_card_bills=True, today=as_of,
    )
    next_by_card: dict[int, object] = {}
    for p in sorted(payments, key=lambda p: p.due):
        next_by_card.setdefault(p.card_id, p)
    out: list[MetricReadingData] = []
    for card in sorted(active_cards(db, user.id), key=lambda c: c.id):
        p = next_by_card.get(card.id)
        if p is None:
            value = ZERO
            explain = (
                ExplainBuilder(f"{card.name} next payment")
                .start(f"No payment due in the next {CARD_WINDOW_DAYS} days", value)
                .build(value)
            )
        else:
            value = abs(p.amount)
            explain = (
                ExplainBuilder(f"{card.name} next payment")
                .start(f"Next payment, due {p.due:%b %-d}", value, note=_cc_basis_note(p))
                .build(value)
            )
        out.append(MetricReadingData(
            f"card_payment:{card.id}", f"{card.name} next payment", value, explain,
        ))
    return out


def collect_headline_metrics(
    db: Session, user: models.User, as_of: date,
) -> list[MetricReadingData]:
    """Every headline figure with its receipt; `[]` without a primary checking account."""
    account = primary_checking(db, user.id)
    if account is None:
        return []
    snap = compute_budget_snapshot(db, user, account.id, as_of)
    month = build_month_summary(db, user.id, as_of.year, as_of.month)
    available = available_to_spend(db, user, as_of)

    def reading(key: str, label: str, value: Decimal, explain: schemas.Explanation):
        return MetricReadingData(key, label, value, explain)

    ex = snap.explain
    readings = [
        reading("leftover", "Leftover", month.left_over, month.explain["left_over"]),
        reading("left_to_spend", "Left to Spend", snap.left_to_spend, ex["left_to_spend"]),
        reading("spendable_week", "Spendable this week", snap.left_to_spend_weekly, ex["spendable_week"]),
        reading("spendable_today", "Spendable today", snap.spendable_today, ex["spendable_today"]),
        reading("safety_margin", "Safety Margin", snap.safety_margin, ex["safety_margin"]),
        reading("safety_margin_week", "Safety Margin (this week)", snap.safety_margin_weekly,
                ex["safety_margin_week"]),
        reading("safety_margin_today", "Safety Margin today", snap.safety_margin_today,
                ex["safety_margin_today"]),
        reading("next_month_minimum", "Lowest next month", snap.next_month_minimum,
                ex["next_month_minimum"]),
        reading("lookahead_minimum", "3-month low", snap.lookahead_minimum, ex["lookahead_minimum"]),
        reading("available_to_spend", "Available to Spend", available.available, available.explain),
        _checking_balance_reading(db, account, as_of),
    ]
    return readings + _card_payment_readings(db, user, account, as_of)


def collect_sources(db: Session, user: models.User, as_of: date) -> dict:
    """What the figures were computed from, JSON-safe (amounts as strings):
    pending rows on active cards and the primary checking, plus the newest
    actual transaction and card transaction ids."""
    cards = {c.id: c for c in active_cards(db, user.id)}
    card_pending = []
    if cards:
        pending_rows = db.query(models.CardPendingTransaction).filter(
            models.CardPendingTransaction.user_id == user.id,
            models.CardPendingTransaction.card_id.in_(list(cards)),
        ).order_by(models.CardPendingTransaction.card_id, models.CardPendingTransaction.id).all()
        card_pending = [
            {
                "card_id": r.card_id, "card": cards[r.card_id].name,
                "external_id": r.external_id, "merchant": r.merchant,
                "amount": str(Decimal(str(r.amount))),
            }
            for r in pending_rows
        ]
    account = primary_checking(db, user.id)
    checking_pending = []
    if account is not None:
        checking_pending = [
            {
                "account_id": account.id, "account": account.name,
                "external_id": r.external_id, "description": r.description,
                "amount": str(Decimal(str(r.amount))),
            }
            for r in checking_pending_rows(db, account, as_of)
        ]
    max_txn = db.query(func.max(models.Transaction.id)).filter(
        models.Transaction.user_id == user.id, models.Transaction.is_actual == True,
    ).scalar()
    max_card_txn = db.query(func.max(models.CreditCardTransaction.id)).filter(
        models.CreditCardTransaction.user_id == user.id,
    ).scalar()
    return {
        "card_pending": card_pending,
        "checking_pending": checking_pending,
        "max_txn_id": max_txn or 0,
        "max_card_txn_id": max_card_txn or 0,
    }
