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
            rollover_enabled=cat.rollover_enabled,
            rollover_balance=cat.rollover_balance or Decimal("0"),
        ))

    # Roll subcategory actuals up into parent rows
    row_by_cat_id = {r.category_id: r for r in rows}
    for row in rows:
        if row.parent_id is not None and row.parent_id in row_by_cat_id:
            parent = row_by_cat_id[row.parent_id]
            parent.actual_checking += row.actual_checking
            parent.actual_cards += row.actual_cards
            parent.actual_total += row.actual_total
            parent.variance = parent.budgeted - parent.actual_total

    return rows


def apply_rollover(db: Session, user_id: int, year: int, month: int) -> int:
    """Set each rollover-enabled category's rollover_balance to max(0, budgeted - actual) for the given month.

    Returns the number of categories updated.
    """
    rows = compute_overview(db, user_id, year, month)
    rollover_ids = [r.category_id for r in rows if r.rollover_enabled]
    if not rollover_ids:
        return 0

    cat_map = {
        c.id: c
        for c in db.query(models.Category).filter(
            models.Category.id.in_(rollover_ids),
            models.Category.user_id == user_id,
        ).all()
    }

    updated = 0
    for row in rows:
        if not row.rollover_enabled:
            continue
        cat = cat_map.get(row.category_id)
        if cat:
            cat.rollover_balance = max(Decimal("0"), row.budgeted - row.actual_total)
            updated += 1
    db.commit()
    return updated
