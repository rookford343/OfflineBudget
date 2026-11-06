import calendar
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
from backend import models
from backend import schemas
from backend.dependencies import get_db, get_current_user
from backend.services.spending_helpers import filter_real_spend, is_card_payment, NOT_SAVINGS, merchant_totals
from backend.services.real_spend import ClassifiedRow, classified_rows
from backend.services.summary_generator import generate_weekly_digest
from backend.services.budget_snapshot import compute_budget_snapshot
from backend.services.recent_activity import get_recent_activity

# Bands on the stacked monthly chart before the tail collapses into "Other".
_MAX_STACK_CATEGORIES = 8
# Sentinel for the synthetic "Other" band; negative so it can never collide
# with a real category id.
_OTHER_CATEGORY_ID = -1

router = APIRouter(prefix="/spending", tags=["spending"])


def _spend_rows(db: Session, user_id: int, start: date, end: date, **filters) -> list[ClassifiedRow]:
    """Rows the real-spending rule (services/real_spend.py) calls spend, with
    their signed amounts (refunds negative). Every Spending page chart reads
    through this, so a bar, its drill-down and the category view agree."""
    return [r for r in classified_rows(db, user_id, start, end, **filters) if r.verdict.kind == "spend"]


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
    for r in _spend_rows(db, user.id, start, end, account_id=account_id, card_id=card_id):
        month = r.row.date.strftime("%Y-%m")
        bucket = results.setdefault(month, {"checking": Decimal("0"), "cards": Decimal("0")})
        bucket["checking" if r.source == "checking" else "cards"] += r.verdict.amount

    return [
        schemas.MonthlySpendingEntry(
            month=month,
            total=data["checking"] + data["cards"],
            checking=data["checking"],
            cards=data["cards"],
        )
        for month, data in sorted(results.items())
    ]


@router.get("/transactions", response_model=list[schemas.SpendingLineItem])
def spending_line_items(
    start: date = Query(...),
    end: date = Query(...),
    account_id: Optional[int] = None,
    card_id: Optional[int] = None,
    limit: int = 25,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """The rows behind a spending total, largest first.

    Filters are kept identical to /monthly on purpose: the drill-down exists to
    explain a bar, so anything excluded from the bar (internal transfers, card
    payoffs) must be excluded here too. Reading the raw transaction list
    instead put "Transfer to Savings" at the top of a panel captioned
    "transfers excluded" -- consistent numbers depend on one shared predicate,
    not two similar ones.
    """
    items: list[schemas.SpendingLineItem] = []
    for r in _spend_rows(db, user.id, start, end, account_id=account_id, card_id=card_id):
        if r.source == "checking":
            description = r.row.description or "(no description)"
        else:
            description = r.row.merchant or "(no merchant)"
        items.append(schemas.SpendingLineItem(
            date=r.row.date, description=description,
            amount=r.verdict.amount, source=r.source,
        ))

    items.sort(key=lambda i: i.amount, reverse=True)
    return items[:limit]


@router.get("/recent", response_model=list[schemas.RecentActivityItem])
def spending_recent(
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """The Dashboard's 'Recent transactions' card: newest checking + card
    activity merged into one feed, same exclusions as the Spending page."""
    return get_recent_activity(db, user.id, limit)


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

    # Group by the budget category the transaction is actually assigned to --
    # the leaf -- rather than rolling everything up into Necessities/Wants/
    # Charity. The three top-level buckets are a classification of spending,
    # not a thing you budget against, so a chart built on them can't answer
    # "which category ran hot this month". Transactions filed directly on a
    # parent keep that parent as their own group instead of being dropped.
    def group_id(cat_id: int) -> Optional[int]:
        c = cat_map.get(cat_id)
        return None if c is None else c.id

    results: dict[str, dict[int, Decimal]] = {}
    for r in _spend_rows(db, user.id, start, end, account_id=account_id, card_id=card_id):
        if not r.category_id:
            continue
        tc = group_id(r.category_id)
        if tc is None:
            continue
        month = r.row.date.strftime("%Y-%m")
        results.setdefault(month, {})
        results[month][tc] = results[month].get(tc, Decimal("0")) + r.verdict.amount

    # Leaf categories are numerous enough that stacking every one of them
    # produces an unreadable chart, so only the biggest get their own band
    # across the whole range and the tail collapses into a single "Other".
    # Ranking spans the range rather than each month so a category keeps the
    # same colour band month to month.
    span_totals: dict[int, Decimal] = {}
    for month_data in results.values():
        for cid, amt in month_data.items():
            span_totals[cid] = span_totals.get(cid, Decimal("0")) + amt
    ranked = sorted(span_totals.items(), key=lambda kv: kv[1], reverse=True)
    named_ids = {cid for cid, _ in ranked[:_MAX_STACK_CATEGORIES]}

    output = []
    for month in sorted(results.keys()):
        month_data = results[month]
        total = sum(month_data.values(), Decimal("0"))
        cats = [
            schemas.CategoryMonthlyTotal(
                category_id=cid,
                category_name=cat_map[cid].name,
                color=cat_map[cid].color,
                total=amt,
            )
            for cid, amt in sorted(
                ((cid, amt) for cid, amt in month_data.items() if cid in named_ids and amt > 0),
                key=lambda kv: span_totals[kv[0]], reverse=True,
            )
        ]
        other = sum(
            (amt for cid, amt in month_data.items() if cid not in named_ids),
            Decimal("0"),
        )
        if other > 0:
            cats.append(schemas.CategoryMonthlyTotal(
                category_id=_OTHER_CATEGORY_ID, category_name="Other",
                color="#9ca3af", total=other,
            ))
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

    cards = db.query(models.CreditCard).filter(
        models.CreditCard.user_id == user.id,
    ).all()
    card_map = {c.id: c.name for c in cards}

    # Build sub-category -> {source_label: amount} from the real-spending
    # rule: refunds net, so a line (and its breakdown) can go negative.
    sub_breakdown: dict[int, dict[str, Decimal]] = {}
    for r in _spend_rows(db, user.id, start, end, account_id=account_id, card_id=card_id):
        if not r.category_id:
            continue
        label = "Checking" if r.source == "checking" else card_map.get(r.row.card_id, "Credit Card")
        sub_breakdown.setdefault(r.category_id, {})
        sub_breakdown[r.category_id][label] = (
            sub_breakdown[r.category_id].get(label, Decimal("0")) + r.verdict.amount
        )

    # Budgets come from the Set Budgets plan (Committed from Recurring +
    # Flexible, a parent line counting as its group's total), scaled to the
    # range. Reading raw allocations here added a parent line to its
    # children's lines and disagreed with Track Budgets for the same month.
    from backend.services.budget_plan import plan_budgets_for_range
    row_budget, top_budget = plan_budgets_for_range(db, user, start, end)

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
            budgeted = row_budget.get(child.id, Decimal("0"))
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
        # The group's Budget from the plan: its rows' Budgets, or its parent
        # line when that is larger (the line is the group's total).
        top_budgeted = top_budget.get(top.id, Decimal("0"))

        total_budgeted += top_budgeted
        total_actual += top_actual

        result.append(schemas.SpendingTopLevel(
            category_id=top.id,
            category_name=top.name,
            color=top.color,
            budgeted=top_budgeted,
            actual=top_actual,
            variance=top_budgeted - top_actual,
            is_discretionary=bool(getattr(top, "is_discretionary", False)),
            children=children_out,
        ))

    # Discretionary is a LEAF property, not a top-level one: Groceries sits
    # under "Necessities" (fixed) while Shopping/Food & Drinks sit under
    # "Wants". Summing only top-level rows would file Groceries as fixed and
    # miss it entirely. So walk every category and attribute each one's own
    # spend by its own flag, parent be damned.
    disc_actual = Decimal("0")
    disc_budgeted = Decimal("0")
    for cat in categories:
        if not getattr(cat, "is_discretionary", False):
            continue
        own_spend = sum(sub_breakdown.get(cat.id, {}).values(), Decimal("0"))
        disc_actual += own_spend
        disc_budgeted += row_budget.get(cat.id, Decimal("0"))

    return schemas.SpendingOverview(
        start_date=start,
        end_date=end,
        categories=result,
        total_budgeted=total_budgeted,
        total_actual=total_actual,
        total_variance=total_budgeted - total_actual,
        discretionary_actual=disc_actual,
        discretionary_budgeted=disc_budgeted,
        fixed_actual=total_actual - disc_actual,
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

    sub_totals: dict[int, Decimal] = {}
    for r in _spend_rows(db, user.id, start, end, card_id=card_id, include_checking=False):
        if r.category_id:
            sub_totals[r.category_id] = sub_totals.get(r.category_id, Decimal("0")) + r.verdict.amount
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


def _committed_card_bills_fired(db: Session, user_id: int, start: date, end: date) -> Decimal:
    """Card-linked bills in committed_expenses below (monthly items, and
    yearly items in their month, at item.amount) whose due day falls in
    [start, end]. Kept to this endpoint's own committed recipe so the
    add-back removes exactly what it subtracted: the weekly pacer moved to
    the month base's card-bill list (2026-11), which also holds weekly,
    biweekly and quarterly bills and entered statement amounts that this
    card's committed figure doesn't, so sharing it here would drop those
    bills from both sides. Goes away when Available to Spend is rebuilt on
    the month base (docs/superpowers/specs/2026-11-06-calculation-consistency-design.md)."""
    items = db.query(models.RecurringItem).filter(
        models.RecurringItem.user_id == user_id,
        models.RecurringItem.type == models.RecurringType.expense,
        models.RecurringItem.is_active == True,
        models.RecurringItem.card_id.isnot(None),
    ).all()
    total = Decimal("0")
    day = start
    while day <= end:
        last_day_of_month = calendar.monthrange(day.year, day.month)[1]
        for item in items:
            if item.start_date > day or (item.end_date and item.end_date < day):
                continue
            if item.frequency == models.RecurringFrequency.monthly:
                fires = True
            elif item.frequency == models.RecurringFrequency.yearly:
                fires = item.month_of_year == day.month
            else:
                fires = False
            if not fires:
                continue
            due_day = item.day_of_month if item.day_of_month > 0 else last_day_of_month
            if min(due_day, last_day_of_month) == day.day:
                total += item.amount
        day += timedelta(days=1)
    return total


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

    # "Spent So Far" means spending NOT already represented in Committed Bills,
    # because the two are subtracted from the same income. Two bugs followed
    # from ignoring that:
    #
    #   1. Rows tied to a recurring item were counted here AND in committed
    #      expenses above, so every posted bill was deducted twice.
    #   2. Card charges were not counted at all, only checking. For anyone who
    #      puts most spending on a card that is the larger half, and it made a
    #      single week's digest exceed the whole month's figure on this card.
    txns = (
        db.query(models.Transaction)
        .outerjoin(models.Category, models.Transaction.category_id == models.Category.id)
        .filter(
            models.Transaction.user_id == user.id,
            models.Transaction.is_actual == True,
            models.Transaction.date >= first,
            models.Transaction.date <= last,
            models.Transaction.amount < 0,
            # Already committed above; counting the posted transaction too is
            # the double-deduction described in (1).
            models.Transaction.recurring_item_id.is_(None),
            NOT_SAVINGS,
        )
    ).all()
    # Transfers and card payoffs are not this month's discretionary spend --
    # a payoff settles charges already counted on the card side.
    txns = filter_real_spend(db, user.id, txns)
    spent_this_month = sum((abs(t.amount) for t in txns), Decimal("0"))

    card_rows = db.query(models.CreditCardTransaction).filter(
        models.CreditCardTransaction.user_id == user.id,
        models.CreditCardTransaction.date >= first,
        models.CreditCardTransaction.date <= last,
        models.CreditCardTransaction.amount > 0,
    ).all()
    card_spend = sum(
        (t.amount for t in card_rows if not is_card_payment(t.merchant)), Decimal("0"),
    )
    # Card-linked recurring items are inside committed_expenses too, so remove
    # the ones that have actually fired so far this month -- not the whole
    # month's worth, or an early-month view would over-credit charges that
    # haven't happened yet.
    card_committed_so_far = _committed_card_bills_fired(db, user.id, first, today)
    spent_this_month += max(card_spend - card_committed_so_far, Decimal("0"))

    # pending_charges is the user's own hand-tracked read of real, already-made
    # card spend that hasn't itemized into credit_card_transactions yet --
    # bank sync (and CSV import) only produce itemized rows once a charge
    # actually posts, which can lag the real purchase by days. Every OTHER
    # place in this app that answers "how much has really been spent"
    # (budget_snapshot.py's Left to Spend, forecast_engine.py's carried
    # balance) already folds this in; this endpoint didn't, so a real,
    # already-confirmed charge the user knows about (2026-09-02: $500.00 on
    # Chase, current_balance already reflects it) stayed invisible here,
    # showing "Spent So Far: $0.00" the same day it happened. Not double-
    # counted against card_spend above: pending_charges is specifically the
    # portion NOT YET itemized, by the same convention _fresh_pending_charges
    # and the carried-balance formula already rely on elsewhere. Freshness-
    # checked the same way (stale or unstamped reads as zero), so a forgotten
    # figure doesn't silently linger here either.
    from backend.services.forecast_engine import _fresh_pending_charges
    active_cards = db.query(models.CreditCard).filter(
        models.CreditCard.user_id == user.id,
        models.CreditCard.is_active == True,
    ).all()
    spent_this_month += sum((_fresh_pending_charges(c, today) for c in active_cards), Decimal("0"))

    return schemas.AvailableToSpend(
        monthly_income=monthly_income,
        committed_expenses=committed_expenses,
        spent_this_month=spent_this_month,
        available=monthly_income - committed_expenses - spent_this_month,
    )


@router.get("/budget-snapshot", response_model=schemas.BudgetSnapshot)
def budget_snapshot(
    account_id: int = Query(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    account = db.query(models.Account).filter(
        models.Account.id == account_id,
        models.Account.user_id == user.id,
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return compute_budget_snapshot(db, user, account_id)


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
        for r in _spend_rows(db, user.id, date(year, 1, 1), date(year, 12, 31)):
            months_data[str(r.row.date.month)] += r.verdict.amount
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

    results: dict[str, dict[str, Decimal]] = {}
    for r in _spend_rows(db, user.id, start, today):
        key = r.row.date.strftime("%Y-%m")
        bucket = results.setdefault(key, {"checking": Decimal("0"), "cards": Decimal("0")})
        bucket["checking" if r.source == "checking" else "cards"] += r.verdict.amount

    return [
        schemas.RollingMonthEntry(
            month=m,
            total=results[m]["checking"] + results[m]["cards"],
            checking=results[m]["checking"],
            cards=results[m]["cards"],
        )
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


@router.get("/sankey/{year}/{month}", response_model=schemas.SankeyResponse)
def spending_sankey(
    year: int,
    month: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    first_day = date(year, month, 1)
    last_day = date(year, month, calendar.monthrange(year, month)[1])

    income_totals: dict[str, Decimal] = {}
    expense_totals: dict[str, Decimal] = {}

    # The real-spending rule decides every flow: transfers and card payoffs
    # are neither income nor spending, refunds net against their category,
    # and an income-category debit (a paycheck reversal) reduces income.
    for r in classified_rows(db, user.id, first_day, last_day):
        cat_name = r.row.category.name if r.row.category else "Uncategorized"
        if r.verdict.kind == "income":
            income_totals[cat_name] = income_totals.get(cat_name, Decimal("0")) + r.verdict.amount
        elif r.verdict.kind == "spend":
            expense_totals[cat_name] = expense_totals.get(cat_name, Decimal("0")) + r.verdict.amount

    # A flow diagram can't draw a zero or negative flow, so a category whose
    # refunds met or exceeded its charges (or a fully reversed income line)
    # is left off the diagram; the Spending page totals still carry it.
    income_totals = {k: v for k, v in income_totals.items() if v > 0}
    expense_totals = {k: v for k, v in expense_totals.items() if v > 0}

    # More than _MAX_STACK_CATEGORIES distinct expense categories makes the
    # diagram unreadable -- collapse the tail into "Other", same pattern the
    # stacked monthly-by-category chart already uses. "Uncategorized" is
    # diagnostic (it's the signal the user needs to notice he should categorize
    # more), so it's exempt from collapsing regardless of its size.
    ranked_expenses = sorted(
        (kv for kv in expense_totals.items() if kv[0] != "Uncategorized"),
        key=lambda kv: kv[1], reverse=True,
    )
    named_expense_names = {name for name, _ in ranked_expenses[:_MAX_STACK_CATEGORIES]}
    other_total = sum(
        (amt for name, amt in ranked_expenses[_MAX_STACK_CATEGORIES:]),
        Decimal("0"),
    )
    grouped_expense_totals: dict[str, Decimal] = {
        name: amt for name, amt in expense_totals.items()
        if name == "Uncategorized" or name in named_expense_names
    }
    if other_total > 0:
        if "Other" in grouped_expense_totals:
            # A real category is named "Other" -- add collapsed tail to it
            grouped_expense_totals["Other"] += other_total
        else:
            # No collision, assign normally
            grouped_expense_totals["Other"] = other_total
    expense_totals = grouped_expense_totals

    nodes: list[schemas.SankeyNode] = []
    links: list[schemas.SankeyLink] = []

    for name in income_totals:
        nodes.append(schemas.SankeyNode(id=f"income:{name}", name=name, type="income"))
    for name in expense_totals:
        nodes.append(schemas.SankeyNode(id=f"expense:{name}", name=name, type="expense"))

    # Total income pool node that aggregates all income
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


@router.get("/weekly-digest", response_model=schemas.WeeklyDigest)
def get_weekly_digest(
    account_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    return generate_weekly_digest(db, user, account_id)


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

    from backend.services.bonus_plans import (
        bonus_gross, is_bonus_shaped, payout_date, plans_by_item, salary_for_year,
    )
    from backend.services.forecast_engine import pay_year_dates, paycheck_item_ids

    # Raise-aware salary for the year, falling back to the flat figure.
    salary = salary_for_year(user, year) or Decimal(str(user.annual_salary))

    # The year's bonuses (pay date, gross); unknown amounts are skipped.
    plans = {
        item_id: plan for item_id, plan in plans_by_item(db, user.id).items()
        if is_bonus_shaped(plan.recurring_item) and plan.recurring_item.is_active
    }
    bonuses = []
    for plan in plans.values():
        gross = bonus_gross(plan, user, year)
        if gross is not None:
            bonuses.append((payout_date(plan.recurring_item, year), gross))

    # Paychecks in the year, and left after the pay stub's date, from the
    # same paycheck items the forecast uses, counted across the whole year
    # from each item's schedule pattern (pay_year_dates honors end_date but
    # ignores start_date, which is usually only when the item was entered,
    # unless the item replaces one that ended earlier in the year; a year no
    # item applies to is counted in full on today's schedule).
    as_of = user.tax_withholding_as_of
    income_items = db.query(models.RecurringItem).filter(
        models.RecurringItem.user_id == user.id,
        models.RecurringItem.type == models.RecurringType.income,
        models.RecurringItem.is_active == True,
    ).all()
    pay_ids = paycheck_item_ids(income_items, user.ss_gross_per_paycheck, set(plans))
    paychecks_in_year = paychecks_remaining = None
    if pay_ids:
        pay_items = [i for i in income_items if i.id in pay_ids]
        dates = pay_year_dates(pay_items, year)
        paychecks_in_year = len(dates)
        if as_of is None or as_of.year < year:
            paychecks_remaining = paychecks_in_year
        else:
            paychecks_remaining = sum(1 for d in dates if d > as_of)
    # When no paycheck item matches, estimate_taxes assumes 26 a year.

    def _dec(v):
        return Decimal(str(v)) if v is not None else None

    result = estimate_taxes(
        filing_status=user.tax_filing_status or "single",
        state=user.tax_state or "TX",
        gross_income=salary,
        other_income=Decimal(str(user.other_income or 0)),
        deductible_expenses=total_deductible,
        federal_withheld=Decimal(str(user.federal_withholding_ytd or 0)),
        state_withheld=Decimal(str(user.state_withholding_ytd or 0)),
        year=year,
        bonuses=bonuses,
        pretax_per_paycheck=_dec(user.pretax_per_paycheck),
        federal_per_paycheck=_dec(user.federal_withheld_per_paycheck),
        state_per_paycheck=_dec(user.state_withheld_per_paycheck),
        withholding_as_of=as_of,
        paychecks_in_year=paychecks_in_year,
        paychecks_remaining=paychecks_remaining,
    )
    result["year"] = year
    # result["bracket_year"] is the table year actually used (the nearest
    # bundled one when `year` isn't bundled), so the UI can warn on a mismatch
    # rather than silently applying another year's brackets.
    result["itemized_breakdown"] = {
        "mortgage_interest": float(user.itemized_mortgage_interest or 0),
        "donations": float(user.itemized_donations or 0),
        "salt": float(user.itemized_salt or 0),
        "property_tax": float(user.itemized_property_tax or 0),
        "other": float(user.itemized_other or 0),
        "transaction_deductibles": float(deductible_amount),
    }
    return result
