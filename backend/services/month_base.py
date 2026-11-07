"""One month's money, as both the Recurring page and the Household Snapshot
count it.

The Recurring page's "Left over" and the Dashboard's "Leftover" used to be
two different models of the month and disagreed every month (the user,
2026-11): the snapshot took monthly income items only, each bill's base
amount, quarterly bills spread over three months, and subtracted the
Groceries and Savings budgets; the Recurring strip took every real
occurrence at this month's amount but no budgets. Both now read this one
function, so they agree to the cent:

* Income: every income occurrence landing this month (any frequency), at
  this month's amount (a BillAmountOverride wins for its own date), plus the
  Social Security boost once the wage base is met (forecast_engine's
  ss_paycheck_boosts, the same rules the forecast's paycheck lines use).
* Bills: every expense occurrence this month at this month's amount --
  weekly and biweekly bills each time they fire, quarterly and yearly bills
  whole in the month they're due (no /3 spreading), matching the cash
  forecast and the Budget page's Committed list.
* Planned one-offs landing this month (settled ones at their real amount
  and date): outflows subtract, inflows add. A purchase funded from savings
  also adds its funding transfer, in the month the forecast books it
  (expected_date - funding_lead_days), so checking nets to zero as it does
  on the Forecast tab and only an uncovered remainder moves Leftover.
* Then the month's Groceries budget and the Savings set aside (zero under
  the "pull_from_savings" strategy, where the year is funded by a bonus).

Items with include_in_forecast=False (income that is real but already spoken
for, e.g. a bonus modelled as 1/12th a month) count in neither: this is the
month's real cash. (Confirmed by the user, 2026-11: such income stays out of
Leftover.) credit_card_payment items never count -- they pay off card
charges already counted elsewhere.
"""
from __future__ import annotations
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from sqlalchemy.orm import Session
from backend import models, schemas
from backend.services.forecast_engine import _fires_on, ss_paycheck_boosts

ZERO = Decimal("0")

_MONTHLY_LIKE = {
    models.RecurringFrequency.monthly,
    models.RecurringFrequency.weekly,
    models.RecurringFrequency.biweekly,
}


def budget_allocation_total(
    db: Session, user_id: int, category_name: str, year: int, month: int,
) -> Decimal:
    """The budgeted amount for a category, honouring a month-specific override.

    month == 0 is the "all months" default and 1-12 overrides it. Sorting
    ascending and taking the last row means a month-specific figure wins --
    the same resolution budget_calculator.compute_overview uses (see its
    month.in_([0, month]) query). This used to filter month == 0 only, so
    setting, say, a higher December savings target left the snapshot still
    quoting the annual default.
    """
    rows = (
        db.query(models.BudgetAllocation)
        .join(models.Category, models.Category.id == models.BudgetAllocation.category_id)
        .filter(
            models.BudgetAllocation.user_id == user_id,
            models.Category.name == category_name,
            models.BudgetAllocation.year == year,
            models.BudgetAllocation.month.in_([0, month]),
        )
        .order_by(models.BudgetAllocation.month)
        .all()
    )
    return rows[-1].budgeted_amount if rows else ZERO


@dataclass
class MonthBase:
    year: int
    month: int
    income_items: list[schemas.MonthIncomeOccurrence] = field(default_factory=list)
    monthly_bills: list[schemas.MonthlyBillOccurrence] = field(default_factory=list)
    periodic_due: list[schemas.PeriodicDueOccurrence] = field(default_factory=list)
    one_offs: list[schemas.OneOffOccurrence] = field(default_factory=list)
    income_total: Decimal = ZERO        # includes ss_boost_total
    ss_boost_total: Decimal = ZERO
    monthly_bills_total: Decimal = ZERO
    periodic_total: Decimal = ZERO
    expense_total: Decimal = ZERO
    one_off_out_total: Decimal = ZERO
    one_off_in_total: Decimal = ZERO
    # income - expenses - one-off outflows + one-off inflows: what the
    # Budget page's Committed list reconciles to.
    left_over_before_budgets: Decimal = ZERO
    savings_budget: Decimal = ZERO
    committed_savings: Decimal = ZERO
    groceries_budget: Decimal = ZERO
    # left_over_before_budgets - committed_savings - groceries_budget: the
    # Recurring strip's Left over and the Dashboard's Leftover.
    left_over: Decimal = ZERO


def _counts(item) -> bool:
    return (
        item.type != models.RecurringType.credit_card_payment
        and getattr(item, "include_in_forecast", True) is not False
    )


def _funding_inflow(pe: models.PlannedExpense, year: int, month: int) -> schemas.OneOffOccurrence | None:
    """The savings transfer that funds an outflow one-off, as an inflow row,
    when it lands in this month. Same amount and date the forecast uses
    (forecast_engine.build_forecast's funding_by_date): funding_amount, else
    the purchase amount, on expected_date minus funding_lead_days. So a fully
    funded purchase nets to zero here as it does in checking, and a partly
    funded one moves Leftover by the uncovered remainder only. card_id stays
    None: the transfer reaches checking, not the card, so Left to Spend's
    card add-back (one_offs_on_card) never sees it.

    Counted for settled purchases too: their real transfer posted like the
    purchase did, and dropping it would put the whole purchase back on the
    month. A one-off funded from its own account moves nothing."""
    if (
        pe.funding_account_id is None
        or pe.direction != models.PlannedDirection.outflow
        or pe.funding_account_id == pe.account_id
    ):
        return None
    fund_date = pe.expected_date - timedelta(days=pe.funding_lead_days or 0)
    if (fund_date.year, fund_date.month) != (year, month):
        return None
    move = pe.funding_amount if pe.funding_amount is not None else pe.amount
    return schemas.OneOffOccurrence(
        planned_expense_id=pe.id, name=f"{pe.name} (funded from savings)", date=fund_date,
        amount=abs(move), direction=models.PlannedDirection.inflow,
        settled=pe.settled_on is not None, card_id=None,
    )


def card_bill_occurrences(base: MonthBase, *, include_proposed: bool = False) -> list:
    """Card-linked bill occurrences in the month base -- every weekly,
    biweekly, monthly, quarterly and yearly charge to a card landing this
    month, at this month's amount (an entered statement amount wins). The
    'Credit Card Bills' list behind budget_snapshot's cc_budget_total and
    charged_so_far, and the card bills the weekly pacer takes out of card
    spend.

    Read off build_month_base so an add-back matches what Leftover
    subtracted occurrence for occurrence. Until 2026-11 this was a separate
    query that skipped weekly/biweekly bills and used each item's base
    amount, so a weekly card bill came off Left to Spend twice (as a bill
    and as posted card spending) and an entered statement amount left the
    difference behind. Before that, yearly items counted in all twelve
    months ($500.00/yr of annual card subscriptions treated as monthly).

    A scenario's proposed items (negative ids) are left out by default: they
    are not charged to the card, so nothing in card spending needs adding
    back, and the weekly pacer's card-bill take-out must not count them. The
    Safety Margin's card-bills total passes `include_proposed=True`: the
    safety walk drops this month's card bills from the card payment on the
    assumption that total subtracts them, proposals included.
    """
    return [
        o for o in (*base.monthly_bills, *base.periodic_due)
        if o.card_id is not None and (include_proposed or (o.recurring_item_id or 0) > 0)
    ]


def build_month_base(
    db: Session, user: models.User, year: int, month: int,
    extra_items: list[models.RecurringItem] | None = None,
) -> MonthBase:
    """`extra_items` are a scenario's never-persisted proposed recurring items
    (budget_snapshot passes them), counted by the same rules as real ones."""
    last_day = monthrange(year, month)[1]
    days = [date(year, month, d) for d in range(1, last_day + 1)]
    month_start, month_end = days[0], days[-1]

    items = db.query(models.RecurringItem).filter(
        models.RecurringItem.user_id == user.id,
        models.RecurringItem.is_active == True,
        models.RecurringItem.type != models.RecurringType.credit_card_payment,
        # Real but not cash landing this month -- e.g. an annual bonus
        # modelled as 1/12th per month for budget planning. build_forecast
        # excludes these from the day-by-day forecast the same way; this has
        # to agree with it or "real cash this month" stops being true.
        models.RecurringItem.include_in_forecast == True,
    ).order_by(models.RecurringItem.id).all()
    items = items + [i for i in (extra_items or []) if _counts(i)]

    # Keyed by (recurring_item_id, due_date) so a lookup during the day walk
    # is exact -- mirrors build_forecast's own bill_actuals map.
    overrides: dict[tuple[int, date], Decimal] = {
        (o.recurring_item_id, o.due_date): o.actual_amount
        for o in db.query(models.BillAmountOverride).filter(
            models.BillAmountOverride.user_id == user.id,
            models.BillAmountOverride.due_date >= month_start,
            models.BillAmountOverride.due_date <= month_end,
        ).all()
    }

    income_items_all = [i for i in items if i.type == models.RecurringType.income]
    boosts = ss_paycheck_boosts(db, user, income_items_all, year, month)

    base = MonthBase(year=year, month=month)
    for item in items:
        for d in days:
            if not _fires_on(item, d):
                continue
            override = overrides.get((item.id, d))
            amount = override if override is not None else item.amount
            overridden = override is not None

            if item.type == models.RecurringType.income:
                boost = boosts.get((item.id, d), ZERO)
                base.income_items.append(schemas.MonthIncomeOccurrence(
                    recurring_item_id=item.id, name=item.name, date=d,
                    amount=amount + boost, ss_boost=boost,
                ))
            elif item.frequency in _MONTHLY_LIKE:
                base.monthly_bills.append(schemas.MonthlyBillOccurrence(
                    recurring_item_id=item.id, name=item.name, date=d, amount=amount,
                    overridden=overridden, card_id=item.card_id,
                ))
            else:  # quarterly / yearly
                base.periodic_due.append(schemas.PeriodicDueOccurrence(
                    recurring_item_id=item.id, name=item.name, frequency=item.frequency,
                    date=d, amount=amount, overridden=overridden, card_id=item.card_id,
                ))

    base.income_items.sort(key=lambda o: o.date)
    base.monthly_bills.sort(key=lambda o: o.date)
    base.periodic_due.sort(key=lambda o: o.date)

    base.income_total = sum((o.amount for o in base.income_items), ZERO)
    base.ss_boost_total = sum((o.ss_boost for o in base.income_items), ZERO)
    base.monthly_bills_total = sum((o.amount for o in base.monthly_bills), ZERO)
    base.periodic_total = sum((o.amount for o in base.periodic_due), ZERO)
    base.expense_total = base.monthly_bills_total + base.periodic_total

    # Not scoped by expected_date up front because the effective date can be
    # settled_on, which may differ from expected_date -- filtered below.
    planned = db.query(models.PlannedExpense).filter(models.PlannedExpense.user_id == user.id).all()
    for pe in planned:
        settled = pe.settled_on is not None
        if settled:
            eff_date = pe.settled_on
            eff_amount = pe.actual_amount if pe.actual_amount is not None else pe.amount
        else:
            eff_date = pe.expected_date
            eff_amount = pe.amount
        if eff_date.year != year or eff_date.month != month:
            continue
        base.one_offs.append(schemas.OneOffOccurrence(
            planned_expense_id=pe.id, name=pe.name, date=eff_date,
            amount=abs(eff_amount), direction=pe.direction, settled=settled,
            card_id=pe.card_id,
        ))
    for pe in planned:
        funding = _funding_inflow(pe, year, month)
        if funding is not None:
            base.one_offs.append(funding)
    base.one_offs.sort(key=lambda o: o.date)
    base.one_off_out_total = sum(
        (o.amount for o in base.one_offs if o.direction == models.PlannedDirection.outflow), ZERO,
    )
    base.one_off_in_total = sum(
        (o.amount for o in base.one_offs if o.direction == models.PlannedDirection.inflow), ZERO,
    )

    base.left_over_before_budgets = (
        base.income_total - base.expense_total - base.one_off_out_total + base.one_off_in_total
    )
    base.savings_budget = budget_allocation_total(db, user.id, "Savings", year, month)
    base.groceries_budget = budget_allocation_total(db, user.id, "Groceries", year, month)
    # Under "pull_from_savings" the monthly transfer is not a commitment --
    # the year is funded by a bonus, not by saving out of each paycheck.
    base.committed_savings = ZERO if user.savings_strategy == "pull_from_savings" else base.savings_budget
    base.left_over = base.left_over_before_budgets - base.committed_savings - base.groceries_budget
    return base
