from calendar import monthrange
from datetime import date
from decimal import Decimal
from sqlalchemy.orm import Session
from backend import models
from backend.schemas import BudgetOverviewRow


def compute_overview(
    db: Session,
    user_id: int,
    year: int,
    month: int,
) -> list[BudgetOverviewRow]:
    start = date(year, month, 1)
    end = date(year, month, monthrange(year, month)[1])

    # All categories for user
    categories = db.query(models.Category).filter(
        models.Category.user_id == user_id,
    ).all()
    cat_map = {c.id: c for c in categories}

    # Budget allocations — prefer month-specific, fall back to month=0
    allocations = db.query(models.BudgetAllocation).filter(
        models.BudgetAllocation.user_id == user_id,
        models.BudgetAllocation.year == year,
        models.BudgetAllocation.month.in_([0, month]),
    ).all()
    budget_by_cat: dict[int, Decimal] = {}
    for a in sorted(allocations, key=lambda x: x.month):  # month=0 first, overridden by specific
        budget_by_cat[a.category_id] = a.budgeted_amount

    # Actual checking account spending
    checking_txns = db.query(models.Transaction).filter(
        models.Transaction.user_id == user_id,
        models.Transaction.is_actual == True,
        models.Transaction.date >= start,
        models.Transaction.date <= end,
        models.Transaction.category_id != None,
    ).all()
    checking_by_cat: dict[int, Decimal] = {}
    for t in checking_txns:
        if t.amount < 0:  # only expenses
            checking_by_cat[t.category_id] = checking_by_cat.get(t.category_id, Decimal("0")) + abs(t.amount)

    # Credit card spending
    card_txns = db.query(models.CreditCardTransaction).filter(
        models.CreditCardTransaction.user_id == user_id,
        models.CreditCardTransaction.date >= start,
        models.CreditCardTransaction.date <= end,
        models.CreditCardTransaction.category_id != None,
    ).all()
    cards_by_cat: dict[int, Decimal] = {}
    for t in card_txns:
        if t.amount > 0:  # charges
            cards_by_cat[t.category_id] = cards_by_cat.get(t.category_id, Decimal("0")) + t.amount

    rows: list[BudgetOverviewRow] = []
    for cat in sorted(categories, key=lambda c: (c.sort_order, c.name)):
        budgeted = budget_by_cat.get(cat.id, Decimal("0"))
        actual_checking = checking_by_cat.get(cat.id, Decimal("0"))
        actual_cards = cards_by_cat.get(cat.id, Decimal("0"))
        actual_total = actual_checking + actual_cards
        rows.append(BudgetOverviewRow(
            category_id=cat.id,
            category_name=cat.name,
            parent_id=cat.parent_id,
            budgeted=budgeted,
            actual_checking=actual_checking,
            actual_cards=actual_cards,
            actual_total=actual_total,
            variance=budgeted - actual_total,
        ))
    return rows
