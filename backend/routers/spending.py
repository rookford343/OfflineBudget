import calendar
from datetime import date
from decimal import Decimal
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, cast, String
from sqlalchemy.orm import Session, joinedload
from backend import models
from backend import schemas
from backend.dependencies import get_db, get_current_user
from backend.services.spending_helpers import NOT_SAVINGS, merchant_totals

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

    # Checking transactions (expenses only = negative amounts, exclude savings categories)
    checking_q = (
        db.query(models.Transaction)
        .outerjoin(models.Category, models.Transaction.category_id == models.Category.id)
        .filter(
            models.Transaction.user_id == user.id,
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

    checking_q = (
        db.query(models.Transaction)
        .outerjoin(models.Category, models.Transaction.category_id == models.Category.id)
        .filter(
            models.Transaction.user_id == user.id,
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

    # Checking actuals (expenses only, exclude savings categories)
    checking_q = (
        db.query(models.Transaction)
        .outerjoin(models.Category, models.Transaction.category_id == models.Category.id)
        .filter(
            models.Transaction.user_id == user.id,
            models.Transaction.is_actual == True,
            models.Transaction.date >= start,
            models.Transaction.date <= end,
            NOT_SAVINGS,
        )
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

    txns = (
        db.query(models.Transaction)
        .outerjoin(models.Category, models.Transaction.category_id == models.Category.id)
        .filter(
            models.Transaction.user_id == user.id,
            models.Transaction.is_actual == True,
            models.Transaction.date >= first,
            models.Transaction.date <= last,
            models.Transaction.amount < 0,
            NOT_SAVINGS,
        )
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
        txns = (
            db.query(models.Transaction)
            .outerjoin(models.Category, models.Transaction.category_id == models.Category.id)
            .filter(
                models.Transaction.user_id == user.id,
                models.Transaction.is_actual == True,
                models.Transaction.date >= date(year, 1, 1),
                models.Transaction.date <= date(year, 12, 31),
                models.Transaction.amount < 0,
                NOT_SAVINGS,
            )
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
    txns = (
        db.query(models.Transaction)
        .outerjoin(models.Category, models.Transaction.category_id == models.Category.id)
        .filter(
            models.Transaction.user_id == user.id,
            models.Transaction.is_actual == True,
            models.Transaction.date >= start,
            models.Transaction.date <= today,
            models.Transaction.amount < 0,
            NOT_SAVINGS,
        )
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


@router.get("/sankey/{year}/{month}", response_model=schemas.SankeyResponse)
def spending_sankey(
    year: int,
    month: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    first_day = date(year, month, 1)
    last_day = date(year, month, calendar.monthrange(year, month)[1])

    txns = db.query(models.Transaction).options(
        joinedload(models.Transaction.category)
    ).filter(
        models.Transaction.user_id == user.id,
        models.Transaction.is_actual == True,
        models.Transaction.date >= first_day,
        models.Transaction.date <= last_day,
    ).all()

    # Also include credit card transactions
    card_txns = db.query(models.CreditCardTransaction).options(
        joinedload(models.CreditCardTransaction.category)
    ).filter(
        models.CreditCardTransaction.user_id == user.id,
        models.CreditCardTransaction.date >= first_day,
        models.CreditCardTransaction.date <= last_day,
    ).all()

    income_totals: dict[str, Decimal] = {}
    expense_totals: dict[str, Decimal] = {}

    for t in txns:
        cat_name = t.category.name if t.category else "Uncategorized"
        cat_type = t.category.type if t.category else None
        if t.amount > 0:
            income_totals[cat_name] = income_totals.get(cat_name, Decimal("0")) + t.amount
        elif t.amount < 0 and cat_type != models.CategoryType.income:
            expense_totals[cat_name] = expense_totals.get(cat_name, Decimal("0")) + abs(t.amount)

    for t in card_txns:
        cat_name = t.category.name if t.category else "Uncategorized"
        if t.amount > 0:
            expense_totals[cat_name] = expense_totals.get(cat_name, Decimal("0")) + t.amount

    nodes: list[schemas.SankeyNode] = []
    links: list[schemas.SankeyLink] = []

    for name in income_totals:
        nodes.append(schemas.SankeyNode(id=f"income:{name}", name=name, type="income"))
    for name in expense_totals:
        nodes.append(schemas.SankeyNode(id=f"expense:{name}", name=name, type="expense"))

    # Total income pool node that aggregates all income
    total_income = sum(income_totals.values(), Decimal("0"))
    if income_totals and expense_totals:
        nodes.append(schemas.SankeyNode(id="income:__total__", name="Total Income", type="income_total"))
        for name, amount in income_totals.items():
            links.append(schemas.SankeyLink(source=f"income:{name}", target="income:__total__", value=amount))
        for name, amount in expense_totals.items():
            links.append(schemas.SankeyLink(source="income:__total__", target=f"expense:{name}", value=amount))

    return schemas.SankeyResponse(nodes=nodes, links=links)


# ── Merchant Spending ─────────────────────────────────────────────────────────

@router.get("/by-merchant", response_model=list[schemas.MerchantSpendingEntry])
def spending_by_merchant(
    start: date = Query(...),
    end: date = Query(...),
    account_id: Optional[int] = None,
    card_id: Optional[int] = None,
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    ranked = merchant_totals(db, user.id, start, end, account_id=account_id, card_id=card_id, limit=limit)
    return [schemas.MerchantSpendingEntry(name=name, total=total, count=count) for name, total, count in ranked]


# ── Tax Summary ───────────────────────────────────────────────────────────────

@router.get("/tax-summary")
def tax_summary(
    year: int,
    format: str = "json",
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    start = date(year, 1, 1)
    end = date(year, 12, 31)
    rows_q = (
        db.query(models.Transaction)
        .join(models.Category, models.Transaction.category_id == models.Category.id)
        .filter(
            models.Transaction.user_id == user.id,
            models.Transaction.date >= start,
            models.Transaction.date <= end,
            models.Transaction.is_actual == True,
            models.Category.tax_deductible == True,
        )
        .order_by(models.Transaction.date)
        .all()
    )
    rows = [
        schemas.TaxSummaryRow(
            date=t.date,
            description=t.description,
            amount=t.amount,
            category_name=t.category.name if t.category else "",
        )
        for t in rows_q
    ]
    total = sum(r.amount for r in rows)

    if format == "csv":
        import csv
        import io
        from fastapi.responses import StreamingResponse
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["Date", "Description", "Amount", "Category"])
        for r in rows:
            writer.writerow([str(r.date), r.description, float(r.amount), r.category_name])
        writer.writerow(["", "TOTAL", float(total), ""])
        buf.seek(0)
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=tax_summary_{year}.csv"},
        )

    return schemas.TaxSummaryResponse(year=year, rows=rows, total_amount=total)


@router.get("/tax-estimate")
def tax_estimate(
    year: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Return full tax liability estimate using the user's saved tax profile."""
    from backend.services.tax_service import estimate_taxes

    if not user.annual_salary:
        return {"error": "No tax profile configured. Add salary and filing info in Settings → Profile."}

    # Sum deductible transactions for the year
    from datetime import date as _date
    deductible = db.query(
        func.sum(models.Transaction.amount)
    ).join(
        models.Category, models.Transaction.category_id == models.Category.id
    ).filter(
        models.Transaction.user_id == user.id,
        models.Transaction.date >= _date(year, 1, 1),
        models.Transaction.date <= _date(year, 12, 31),
        models.Transaction.is_actual == True,
        models.Category.tax_deductible == True,
        models.Transaction.amount < 0,
    ).scalar() or Decimal("0")
    deductible_amount = abs(deductible)

    # Add manually entered itemized deductions from the user's tax profile
    itemized_total = sum(
        Decimal(str(v)) for v in [
            user.itemized_mortgage_interest,
            user.itemized_donations,
            user.itemized_salt,
            user.itemized_property_tax,
            user.itemized_other,
        ] if v is not None
    )
    total_deductible = deductible_amount + itemized_total

    result = estimate_taxes(
        filing_status=user.tax_filing_status or "single",
        state=user.tax_state or "TX",
        gross_income=Decimal(str(user.annual_salary)),
        other_income=Decimal(str(user.other_income or 0)),
        deductible_expenses=total_deductible,
        federal_withheld=Decimal(str(user.federal_withholding_ytd or 0)),
        state_withheld=Decimal(str(user.state_withholding_ytd or 0)),
    )
    result["year"] = year
    result["itemized_breakdown"] = {
        "mortgage_interest": float(user.itemized_mortgage_interest or 0),
        "donations": float(user.itemized_donations or 0),
        "salt": float(user.itemized_salt or 0),
        "property_tax": float(user.itemized_property_tax or 0),
        "other": float(user.itemized_other or 0),
        "transaction_deductibles": float(deductible_amount),
    }
    return result
