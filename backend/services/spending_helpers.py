from datetime import date
from decimal import Decimal
from sqlalchemy import or_
from sqlalchemy.orm import Session
from backend import models

NOT_SAVINGS = or_(
    models.Transaction.category_id.is_(None),
    models.Category.type != models.CategoryType.savings,
)


def merchant_totals(
    db: Session,
    user_id: int,
    start: date,
    end: date,
    *,
    account_id: int | None = None,
    card_id: int | None = None,
    limit: int = 50,
) -> list[tuple[str, Decimal, int]]:
    """Returns [(name, total, count), ...] sorted by total descending.

    Combines checking-account expense transactions (keyed by description) and
    credit-card charges (keyed by merchant) — same behavior as the existing
    /spending/by-merchant endpoint.
    """
    totals: dict[str, Decimal] = {}
    counts: dict[str, int] = {}

    checking_q = (
        db.query(models.Transaction)
        .outerjoin(models.Category, models.Transaction.category_id == models.Category.id)
        .filter(
            models.Transaction.user_id == user_id,
            models.Transaction.is_actual == True,
            models.Transaction.date >= start,
            models.Transaction.date <= end,
            models.Transaction.amount < 0,
            NOT_SAVINGS,
        )
    )
    if account_id:
        checking_q = checking_q.filter(models.Transaction.account_id == account_id)
    for t in checking_q.all():
        key = t.description or "Unknown"
        totals[key] = totals.get(key, Decimal("0")) + abs(t.amount)
        counts[key] = counts.get(key, 0) + 1

    card_q = db.query(models.CreditCardTransaction).filter(
        models.CreditCardTransaction.user_id == user_id,
        models.CreditCardTransaction.date >= start,
        models.CreditCardTransaction.date <= end,
        models.CreditCardTransaction.amount > 0,
    )
    if card_id:
        card_q = card_q.filter(models.CreditCardTransaction.card_id == card_id)
    for t in card_q.all():
        key = t.merchant or "Unknown"
        totals[key] = totals.get(key, Decimal("0")) + t.amount
        counts[key] = counts.get(key, 0) + 1

    sorted_entries = sorted(totals.items(), key=lambda x: x[1], reverse=True)[:limit]
    return [(name, total, counts[name]) for name, total in sorted_entries]
