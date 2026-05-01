import calendar
from datetime import date
from decimal import Decimal
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, cast, String
from sqlalchemy.orm import Session
from backend import models
from backend import schemas
from backend.dependencies import get_db, get_current_user

router = APIRouter(prefix="/spending", tags=["spending"])


@router.get("/monthly", response_model=list[schemas.MonthlySpendingEntry])
def spending_monthly(
    start: date = Query(...),
    end: date = Query(...),
    account_id: Optional[int] = None,
    card_id: Optional[int] = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    results: dict[str, dict] = {}

    # Checking transactions (expenses only = negative amounts)
    checking_q = db.query(models.Transaction).filter(
        models.Transaction.user_id == user.id,
        models.Transaction.is_actual == True,
        models.Transaction.date >= start,
        models.Transaction.date <= end,
        models.Transaction.amount < 0,
    )
    if account_id:
        checking_q = checking_q.filter(models.Transaction.account_id == account_id)
    for t in checking_q.all():
        month = t.date.strftime("%Y-%m")
        if month not in results:
            results[month] = {"checking": Decimal("0"), "cards": Decimal("0")}
        results[month]["checking"] += abs(t.amount)

    # Card transactions (charges only = positive amounts)
    card_q = db.query(models.CreditCardTransaction).filter(
        models.CreditCardTransaction.user_id == user.id,
        models.CreditCardTransaction.date >= start,
        models.CreditCardTransaction.date <= end,
        models.CreditCardTransaction.amount > 0,
    )
    if card_id:
        card_q = card_q.filter(models.CreditCardTransaction.card_id == card_id)
    for t in card_q.all():
        month = t.date.strftime("%Y-%m")
        if month not in results:
            results[month] = {"checking": Decimal("0"), "cards": Decimal("0")}
        results[month]["cards"] += t.amount

    return [
        schemas.MonthlySpendingEntry(
            month=month,
            total=data["checking"] + data["cards"],
            checking=data["checking"],
            cards=data["cards"],
        )
        for month, data in sorted(results.items())
    ]


@router.get("/monthly-by-category", response_model=list[schemas.MonthlyCategoryRow])
def spending_monthly_by_category(
    start: date = Query(...),
    end: date = Query(...),
    account_id: Optional[int] = None,
    card_id: Optional[int] = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    categories = db.query(models.Category).filter(models.Category.user_id == user.id).all()
    cat_map = {c.id: c for c in categories}

    def top_id(cat_id: int) -> Optional[int]:
        c = cat_map.get(cat_id)
        if c is None:
            return None
        return c.id if c.parent_id is None else c.parent_id

    results: dict[str, dict[int, Decimal]] = {}

    checking_q = db.query(models.Transaction).filter(
        models.Transaction.user_id == user.id,
        models.Transaction.is_actual == True,
        models.Transaction.date >= start,
        models.Transaction.date <= end,
        models.Transaction.amount < 0,
    )
    if account_id:
        checking_q = checking_q.filter(models.Transaction.account_id == account_id)
    for t in checking_q.all():
        if not t.category_id:
            continue
        tc = top_id(t.category_id)
        if tc is None:
            continue
        month = t.date.strftime("%Y-%m")
        results.setdefault(month, {})
        results[month][tc] = results[month].get(tc, Decimal("0")) + abs(t.amount)

    card_q = db.query(models.CreditCardTransaction).filter(
        models.CreditCardTransaction.user_id == user.id,
        models.CreditCardTransaction.date >= start,
        models.CreditCardTransaction.date <= end,
        models.CreditCardTransaction.amount > 0,
    )
    if card_id:
        card_q = card_q.filter(models.CreditCardTransaction.card_id == card_id)
    for t in card_q.all():
        if not t.category_id:
            continue
        tc = top_id(t.category_id)
        if tc is None:
            continue
        month = t.date.strftime("%Y-%m")
        results.setdefault(month, {})
        results[month][tc] = results[month].get(tc, Decimal("0")) + t.amount

    top_cats = sorted(
        [c for c in categories if c.parent_id is None and c.type == "expense"],
        key=lambda c: c.sort_order,
    )

    output = []
    for month in sorted(results.keys()):
        month_data = results[month]
        total = sum(month_data.values(), Decimal("0"))
        cats = [
            schemas.CategoryMonthlyTotal(
                category_id=tc.id,
                category_name=tc.name,
                color=tc.color,
                total=month_data.get(tc.id, Decimal("0")),
            )
            for tc in top_cats
            if month_data.get(tc.id, Decimal("0")) > 0
        ]
        output.append(schemas.MonthlyCategoryRow(month=month, total=total, categories=cats))
    return output


@router.get("/by-category", response_model=schemas.SpendingOverview)
def spending_by_category(
    start: date = Query(...),
    end: date = Query(...),
    account_id: Optional[int] = None,
    card_id: Optional[int] = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    categories = db.query(models.Category).filter(
        models.Category.user_id == user.id,
    ).all()
    cat_map = {c.id: c for c in categories}

    cards = db.query(models.CreditCard).filter(
        models.CreditCard.user_id == user.id,
    ).all()
    card_map = {c.id: c.name for c in cards}

    # Checking actuals (expenses only)
    checking_q = db.query(models.Transaction).filter(
        models.Transaction.user_id == user.id,
        models.Transaction.is_actual == True,
        models.Transaction.date >= start,
        models.Transaction.date <= end,
    )
    if account_id:
        checking_q = checking_q.filter(models.Transaction.account_id == account_id)
    checking_txns = checking_q.all()

    # Card charges
    card_q = db.query(models.CreditCardTransaction).filter(
        models.CreditCardTransaction.user_id == user.id,
        models.CreditCardTransaction.date >= start,
        models.CreditCardTransaction.date <= end,
    )
    if card_id:
        card_q = card_q.filter(models.CreditCardTransaction.card_id == card_id)
    card_txns = card_q.all()

    # Build sub-category → {source_label: amount}
    sub_breakdown: dict[int, dict[str, Decimal]] = {}

    for t in checking_txns:
        if t.amount >= 0 or not t.category_id:
            continue
        sub_breakdown.setdefault(t.category_id, {})
        label = "Checking"
        sub_breakdown[t.category_id][label] = (
            sub_breakdown[t.category_id].get(label, Decimal("0")) + abs(t.amount)
        )

    for t in card_txns:
        if t.amount <= 0 or not t.category_id:
            continue
        sub_breakdown.setdefault(t.category_id, {})
        label = card_map.get(t.card_id, "Credit Card")
        sub_breakdown[t.category_id][label] = (
            sub_breakdown[t.category_id].get(label, Decimal("0")) + t.amount
        )

    # Get budget allocations for period
    month_numbers = _months_in_range(start, end)
    budgets = db.query(models.BudgetAllocation).filter(
        models.BudgetAllocation.user_id == user.id,
        models.BudgetAllocation.year.in_([start.year, end.year]),
        models.BudgetAllocation.month.in_([0] + month_numbers),
    ).all()
    budget_by_cat: dict[int, Decimal] = {}
    for b in sorted(budgets, key=lambda x: x.month):
        budget_by_cat[b.category_id] = b.budgeted_amount

    # Build top-level → sub-categories
    top_categories = [c for c in categories if c.parent_id is None and c.type == "expense"]
    result: list[schemas.SpendingTopLevel] = []
    total_budgeted = Decimal("0")
    total_actual = Decimal("0")

    for top in sorted(top_categories, key=lambda c: c.sort_order):
        children_out: list[schemas.SpendingSubCategory] = []
        top_actual = Decimal("0")

        for child in sorted(top.children, key=lambda c: c.sort_order):
            breakdown = sub_breakdown.get(child.id, {})
            actual = sum(breakdown.values(), Decimal("0"))
            budgeted = budget_by_cat.get(child.id, Decimal("0"))
            top_actual += actual
            children_out.append(schemas.SpendingSubCategory(
                category_id=child.id,
                category_name=child.name,
                color=child.color,
                budgeted=budgeted,
                actual=actual,
                variance=budgeted - actual,
                breakdown_by_source=breakdown,
            ))

        # Also catch transactions categorized directly to top-level
        top_direct = sub_breakdown.get(top.id, {})
        top_actual += sum(top_direct.values(), Decimal("0"))
        top_budgeted = budget_by_cat.get(top.id, Decimal("0"))

        total_budgeted += top_budgeted
        total_actual += top_actual

        result.append(schemas.SpendingTopLevel(
            category_id=top.id,
            category_name=top.name,
            color=top.color,
            budgeted=top_budgeted,
            actual=top_actual,
            variance=top_budgeted - top_actual,
            children=children_out,
        ))

    return schemas.SpendingOverview(
        start_date=start,
        end_date=end,
        categories=result,
        total_budgeted=total_budgeted,
        total_actual=total_actual,
        total_variance=total_budgeted - total_actual,
    )


@router.get("/by-card", response_model=list[schemas.SpendingTopLevel])
def spending_by_card(
    card_id: int,
    start: date = Query(...),
    end: date = Query(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    card = db.query(models.CreditCard).filter(
        models.CreditCard.id == card_id,
        models.CreditCard.user_id == user.id,
    ).first()
    if not card:
        return []

    categories = db.query(models.Category).filter(
        models.Category.user_id == user.id,
    ).all()

    txns = db.query(models.CreditCardTransaction).filter(
        models.CreditCardTransaction.card_id == card_id,
        models.CreditCardTransaction.user_id == user.id,
        models.CreditCardTransaction.date >= start,
        models.CreditCardTransaction.date <= end,
        models.CreditCardTransaction.amount > 0,
    ).all()

    sub_totals: dict[int, Decimal] = {}
    for t in txns:
        if t.category_id:
            sub_totals[t.category_id] = sub_totals.get(t.category_id, Decimal("0")) + t.amount

    cat_map = {c.id: c for c in categories}
    top_categories = [c for c in categories if c.parent_id is None and c.type == "expense"]
    result: list[schemas.SpendingTopLevel] = []

    for top in sorted(top_categories, key=lambda c: c.sort_order):
        children_out = []
        top_actual = Decimal("0")
        for child in sorted(top.children, key=lambda c: c.sort_order):
            actual = sub_totals.get(child.id, Decimal("0"))
            top_actual += actual
            children_out.append(schemas.SpendingSubCategory(
                category_id=child.id,
                category_name=child.name,
                color=child.color,
                budgeted=Decimal("0"),
                actual=actual,
                variance=Decimal("0"),
                breakdown_by_source={card.name: actual} if actual else {},
            ))
        result.append(schemas.SpendingTopLevel(
            category_id=top.id,
            category_name=top.name,
            color=top.color,
            budgeted=Decimal("0"),
            actual=top_actual,
            variance=Decimal("0"),
            children=children_out,
        ))
    return result


@router.get("/available-to-spend", response_model=schemas.AvailableToSpend)
def available_to_spend(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    today = date.today()
    first = today.replace(day=1)
    last = today.replace(day=calendar.monthrange(today.year, today.month)[1])

    income_items = db.query(models.RecurringItem).filter(
        models.RecurringItem.user_id == user.id,
        models.RecurringItem.type == models.RecurringType.income,
        models.RecurringItem.is_active == True,
        models.RecurringItem.frequency == models.RecurringFrequency.monthly,
    ).all()
    monthly_income = sum((item.amount for item in income_items), Decimal("0"))

    expense_items = db.query(models.RecurringItem).filter(
        models.RecurringItem.user_id == user.id,
        models.RecurringItem.type == models.RecurringType.expense,
        models.RecurringItem.is_active == True,
    ).all()
    committed_expenses = Decimal("0")
    for item in expense_items:
        if item.frequency == models.RecurringFrequency.monthly:
            committed_expenses += item.amount
        elif item.frequency == models.RecurringFrequency.yearly and item.month_of_year == today.month:
            committed_expenses += item.amount

    txns = db.query(models.Transaction).filter(
        models.Transaction.user_id == user.id,
        models.Transaction.is_actual == True,
        models.Transaction.date >= first,
        models.Transaction.date <= last,
        models.Transaction.amount < 0,
    ).all()
    spent_this_month = sum((abs(t.amount) for t in txns), Decimal("0"))

    return schemas.AvailableToSpend(
        monthly_income=monthly_income,
        committed_expenses=committed_expenses,
        spent_this_month=spent_this_month,
        available=monthly_income - committed_expenses - spent_this_month,
    )


@router.get("/yearly-trends", response_model=list[schemas.YearlyTrendEntry])
def spending_yearly_trends(
    years: int = Query(default=3, ge=1, le=5),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    current_year = date.today().year
    result = []
    for year in range(current_year - years + 1, current_year + 1):
        months_data: dict[str, Decimal] = {str(m): Decimal("0") for m in range(1, 13)}
        txns = db.query(models.Transaction).filter(
            models.Transaction.user_id == user.id,
            models.Transaction.is_actual == True,
            models.Transaction.date >= date(year, 1, 1),
            models.Transaction.date <= date(year, 12, 31),
            models.Transaction.amount < 0,
        ).all()
        for t in txns:
            months_data[str(t.date.month)] += abs(t.amount)
        card_txns = db.query(models.CreditCardTransaction).filter(
            models.CreditCardTransaction.user_id == user.id,
            models.CreditCardTransaction.date >= date(year, 1, 1),
            models.CreditCardTransaction.date <= date(year, 12, 31),
            models.CreditCardTransaction.amount > 0,
        ).all()
        for t in card_txns:
            months_data[str(t.date.month)] += t.amount
        result.append(schemas.YearlyTrendEntry(year=year, months=months_data))
    return result


@router.get("/rolling-monthly", response_model=list[schemas.RollingMonthEntry])
def spending_rolling_monthly(
    months: int = Query(default=24, ge=1, le=60),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    today = date.today()
    # Calculate start: go back `months` calendar months
    start_year = today.year
    start_month = today.month - months + 1
    while start_month <= 0:
        start_month += 12
        start_year -= 1
    start = date(start_year, start_month, 1)

    results: dict[str, Decimal] = {}
    txns = db.query(models.Transaction).filter(
        models.Transaction.user_id == user.id,
        models.Transaction.is_actual == True,
        models.Transaction.date >= start,
        models.Transaction.date <= today,
        models.Transaction.amount < 0,
    ).all()
    for t in txns:
        key = t.date.strftime("%Y-%m")
        results[key] = results.get(key, Decimal("0")) + abs(t.amount)
    card_txns = db.query(models.CreditCardTransaction).filter(
        models.CreditCardTransaction.user_id == user.id,
        models.CreditCardTransaction.date >= start,
        models.CreditCardTransaction.date <= today,
        models.CreditCardTransaction.amount > 0,
    ).all()
    for t in card_txns:
        key = t.date.strftime("%Y-%m")
        results[key] = results.get(key, Decimal("0")) + t.amount

    return [
        schemas.RollingMonthEntry(month=m, total=results.get(m, Decimal("0")))
        for m in sorted(results.keys())
    ]


@router.get("/summary/{year}/{month}", response_model=schemas.MonthlySummary)
def monthly_summary(
    year: int,
    month: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    from backend.services.summary_generator import generate_summary
    return generate_summary(db, user.id, year, month)


def _months_in_range(start: date, end: date) -> list[int]:
    months = set()
    d = start.replace(day=1)
    while d <= end:
        months.add(d.month)
        if d.month == 12:
            d = d.replace(year=d.year + 1, month=1)
        else:
            d = d.replace(month=d.month + 1)
    return list(months)
