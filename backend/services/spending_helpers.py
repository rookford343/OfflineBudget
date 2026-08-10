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

    Refunds/credits net against the matching charge rather than being
    dropped. On the card side this is unconditional -- CreditCardTransaction
    only ever holds charges and their refunds, never unrelated income, so a
    negative amount is always a credit against that same merchant's spend.
    On the checking side a positive amount could just as easily be a
    paycheck, a Zelle from a relative, or a transfer from savings -- none of
    which should net against "spending". A checking credit only nets in when
    its description exactly matches a debit description already counted in
    this window, which is what a same-merchant refund looks like and what an
    unrelated deposit never does.
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
    debit_rows = checking_q.all()
    debit_descriptions = {t.description for t in debit_rows if t.description}
    for t in debit_rows:
        key = t.description or "Unknown"
        totals[key] = totals.get(key, Decimal("0")) + abs(t.amount)
        counts[key] = counts.get(key, 0) + 1

    if debit_descriptions:
        refund_q = db.query(models.Transaction).filter(
            models.Transaction.user_id == user_id,
            models.Transaction.is_actual == True,
            models.Transaction.date >= start,
            models.Transaction.date <= end,
            models.Transaction.amount > 0,
            models.Transaction.description.in_(debit_descriptions),
        )
        if account_id:
            refund_q = refund_q.filter(models.Transaction.account_id == account_id)
        for t in refund_q.all():
            key = t.description or "Unknown"
            totals[key] = totals.get(key, Decimal("0")) - t.amount

    card_q = db.query(models.CreditCardTransaction).filter(
        models.CreditCardTransaction.user_id == user_id,
        models.CreditCardTransaction.date >= start,
        models.CreditCardTransaction.date <= end,
    )
    if card_id:
        card_q = card_q.filter(models.CreditCardTransaction.card_id == card_id)
    for t in card_q.all():
        key = t.merchant or "Unknown"
        totals[key] = totals.get(key, Decimal("0")) + t.amount
        if t.amount > 0:
            counts[key] = counts.get(key, 0) + 1

    sorted_entries = sorted(totals.items(), key=lambda x: x[1], reverse=True)[:limit]
    return [(name, total, counts[name]) for name, total in sorted_entries]


def category_totals_for_range(db: Session, user_id: int, start: date, end: date) -> dict[int | None, Decimal]:
    """Sum of expense spending per category_id across checking + credit-card
    transactions in [start, end]. Savings-type categories are excluded, matching
    the rest of the app's spending totals. Transactions with no category_id are
    grouped under the `None` key so callers can surface an "Uncategorized"
    bucket instead of silently dropping that spend.

    Refunds/credits net against the matching charge rather than being
    dropped -- see merchant_totals' docstring for why the card side nets
    unconditionally while the checking side only nets a credit whose
    description matches an already-counted debit (a same-merchant refund,
    not unrelated income landing in the same category).
    """
    totals: dict[int | None, Decimal] = {}

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
    debit_rows = checking_q.all()
    debit_descriptions = {t.description for t in debit_rows if t.description}
    for t in debit_rows:
        totals[t.category_id] = totals.get(t.category_id, Decimal("0")) + abs(t.amount)

    if debit_descriptions:
        refund_q = db.query(models.Transaction).filter(
            models.Transaction.user_id == user_id,
            models.Transaction.is_actual == True,
            models.Transaction.date >= start,
            models.Transaction.date <= end,
            models.Transaction.amount > 0,
            models.Transaction.description.in_(debit_descriptions),
        )
        for t in refund_q.all():
            totals[t.category_id] = totals.get(t.category_id, Decimal("0")) - t.amount

    card_q = (
        db.query(models.CreditCardTransaction)
        .outerjoin(models.Category, models.CreditCardTransaction.category_id == models.Category.id)
        .filter(
            models.CreditCardTransaction.user_id == user_id,
            models.CreditCardTransaction.date >= start,
            models.CreditCardTransaction.date <= end,
            or_(
                models.CreditCardTransaction.category_id.is_(None),
                models.Category.type != models.CategoryType.savings,
            ),
        )
    )
    for t in card_q.all():
        totals[t.category_id] = totals.get(t.category_id, Decimal("0")) + t.amount

    return totals
