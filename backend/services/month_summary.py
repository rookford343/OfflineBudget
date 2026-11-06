"""Real month totals for the Recurring page.

Unlike services/recurring_math.monthly_equivalent (a smoothed "what does this
cost per month on average" figure used by /recurring/breakdown), this answers
"what actually lands in this specific calendar month": every day of the month
is walked through forecast_engine._fires_on, the same predicate build_forecast
itself uses, so this can never disagree with the day-by-day cash forecast on
start/end dates, quarterly/yearly firing months, or last-day (day_of_month=0)
handling.

The numbers come from services/month_base.build_month_base, which the
Dashboard's Household Snapshot Leftover reads too -- so this strip's Left
over (after the Groceries budget and Savings set aside) IS that Leftover for
the same month. See month_base's docstring for the counting rules.

Scoped to the user, not an account -- like /recurring/breakdown, this covers
every active recurring item the user owns regardless of which account it's
on, since the Recurring page has no per-account context to filter by.
"""
from __future__ import annotations
from sqlalchemy.orm import Session
from backend import models, schemas
from backend.schemas import ExplainChild
from backend.services.explain import ExplainBuilder
from backend.services.month_base import build_month_base


def build_month_summary(db: Session, user_id: int, year: int, month: int) -> schemas.MonthSummaryOut:
    user = db.query(models.User).filter(models.User.id == user_id).one()
    base = build_month_base(db, user, year, month)

    expense_builder = ExplainBuilder("Expenses this month").start(
        "Monthly bills", base.monthly_bills_total,
        note="Every weekly, biweekly and monthly bill charged this month",
        children=[ExplainChild(label=f"{b.name} ({b.date:%b %-d})", amount=b.amount,
                               note="actual statement amount" if b.overridden else None)
                  for b in base.monthly_bills],
    )
    for p in base.periodic_due:
        expense_builder.add(f"{p.name} ({p.date:%b %-d})", p.amount,
                            note=f"{p.frequency.value if hasattr(p.frequency, 'value') else p.frequency} bill due this month")

    # Each paycheck's Social Security boost is its own child row, so the
    # figure sits in an amount (masked with balances hidden), never a note.
    income_children: list[ExplainChild] = []
    for i in base.income_items:
        income_children.append(ExplainChild(label=f"{i.name} ({i.date:%b %-d})", amount=i.amount - i.ss_boost))
        if i.ss_boost:
            income_children.append(ExplainChild(
                label=f"Social Security max ({i.date:%b %-d})", amount=i.ss_boost,
                note="Wage base met, so Social Security is no longer withheld",
            ))
    left_builder = ExplainBuilder("Left over").start(
        "Income", base.income_total, children=income_children,
    ).subtract("Expenses this month", base.expense_total)
    for o in base.one_offs:
        direction = o.direction.value if hasattr(o.direction, "value") else str(o.direction)
        label = f"{o.name} ({o.date:%b %-d})"
        note = "one-off, settled" if o.settled else "planned one-off"
        if direction == "inflow":
            left_builder.add(label, o.amount, note=note)
        else:
            left_builder.subtract(label, o.amount, note=note)
    left_builder.subtract(
        "Savings set aside", base.committed_savings,
        note=("None: your savings strategy pulls from savings instead"
              if user.savings_strategy == "pull_from_savings" else "This month's Savings budget"),
    ).subtract("Groceries budget", base.groceries_budget, note="This month's Groceries budget")
    explain = {
        "expense_total": expense_builder.build(base.expense_total),
        "left_over": left_builder.build(base.left_over),
    }

    return schemas.MonthSummaryOut(
        year=year, month=month,
        income_items=base.income_items, income_total=base.income_total,
        ss_boost_total=base.ss_boost_total,
        monthly_bills=base.monthly_bills, monthly_bills_total=base.monthly_bills_total,
        periodic_due=base.periodic_due, periodic_total=base.periodic_total,
        expense_total=base.expense_total,
        one_offs=base.one_offs, one_off_out_total=base.one_off_out_total,
        one_off_in_total=base.one_off_in_total,
        left_over_before_budgets=base.left_over_before_budgets,
        savings_budget=base.savings_budget, committed_savings=base.committed_savings,
        groceries_budget=base.groceries_budget,
        left_over=base.left_over,
        explain=explain,
    )
