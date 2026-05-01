import calendar
from datetime import date
from decimal import Decimal
from collections import defaultdict
from sqlalchemy.orm import Session
from backend import models
from backend.schemas import MonthlySummary


def _month_spending_by_category(
    db: Session, user_id: int, year: int, month: int
) -> tuple[dict[int, Decimal], Decimal, Decimal]:
    """Returns (spending_by_category_id, total_debits, total_credits).

    Includes both checking transactions and credit card charges so totals
    match the budget overview rather than being understated.
    """
    start = date(year, month, 1)
    end = date(year, month, calendar.monthrange(year, month)[1])

    checking_txns = (
        db.query(models.Transaction)
        .filter(
            models.Transaction.user_id == user_id,
            models.Transaction.is_actual == True,
            models.Transaction.date >= start,
            models.Transaction.date <= end,
        )
        .all()
    )

    card_txns = (
        db.query(models.CreditCardTransaction)
        .filter(
            models.CreditCardTransaction.user_id == user_id,
            models.CreditCardTransaction.date >= start,
            models.CreditCardTransaction.date <= end,
        )
        .all()
    )

    by_cat: dict[int, Decimal] = defaultdict(Decimal)
    total_debits = Decimal("0")
    total_credits = Decimal("0")

    for t in checking_txns:
        if t.amount < 0:
            total_debits += abs(t.amount)
            if t.category_id:
                by_cat[t.category_id] += abs(t.amount)
        else:
            total_credits += t.amount

    for t in card_txns:
        if t.amount > 0:
            total_debits += t.amount
            if t.category_id:
                by_cat[t.category_id] += t.amount

    return dict(by_cat), total_debits, total_credits


def generate_summary(db: Session, user_id: int, year: int, month: int) -> MonthlySummary:
    by_cat, total_debits, total_credits = _month_spending_by_category(db, user_id, year, month)

    if not by_cat and total_debits == 0 and total_credits == 0:
        return MonthlySummary(
            year=year,
            month=month,
            top_category=None,
            top_category_amount=None,
            mom_delta=None,
            mom_delta_pct=None,
            net_cashflow=Decimal("0"),
            text="Not enough data yet for this month.",
        )

    top_cat_id = max(by_cat, key=lambda k: by_cat[k]) if by_cat else None
    top_cat_name: str | None = None
    top_cat_amount: Decimal | None = None
    if top_cat_id:
        cat_map = {c.id: c.name for c in db.query(models.Category).filter(
            models.Category.user_id == user_id).all()}
        top_cat_name = cat_map.get(top_cat_id)
        top_cat_amount = by_cat[top_cat_id]

    prior_year, prior_month = (year - 1, 12) if month == 1 else (year, month - 1)
    _, prior_debits, _ = _month_spending_by_category(db, user_id, prior_year, prior_month)
    mom_delta = total_debits - prior_debits if prior_debits > 0 else None
    mom_delta_pct: Decimal | None = None
    if prior_debits > 0:
        mom_delta_pct = Decimal(str(round(float((total_debits - prior_debits) / prior_debits * 100), 1)))

    net_cashflow = total_credits - total_debits

    parts: list[str] = []

    if top_cat_name and top_cat_amount:
        parts.append(f"Your top spending category was {top_cat_name} at ${top_cat_amount:,.2f}.")

    if mom_delta is not None and mom_delta_pct is not None:
        direction = "up" if mom_delta > 0 else "down"
        label = "more" if mom_delta > 0 else "less"
        parts.append(
            f"Overall spending was {direction} {abs(mom_delta_pct):.1f}% "
            f"(${abs(mom_delta):,.2f} {label}) vs. last month."
        )

    if net_cashflow >= 0:
        parts.append(f"You came out ahead by ${net_cashflow:,.2f} this month.")
    else:
        parts.append(f"You spent ${abs(net_cashflow):,.2f} more than you earned this month.")

    return MonthlySummary(
        year=year,
        month=month,
        top_category=top_cat_name,
        top_category_amount=top_cat_amount,
        mom_delta=mom_delta,
        mom_delta_pct=mom_delta_pct,
        net_cashflow=net_cashflow,
        text=" ".join(parts),
    )
