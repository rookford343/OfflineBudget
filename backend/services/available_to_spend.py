"""Available to Spend, figured "before budgets".

This month's income - bills - one-offs - real spending so far, without the
Groceries and Savings budgets. Left to Spend is the same idea after the
budgets and with its card-only spending view; `to_left_to_spend` walks from
one to the other so the two cards never look like they disagree.

Everything here reads the shared layer:

* income, bills and one-offs: `month_base.build_month_base` (Social Security
  boost, bill overrides, quarterly bills in their due month, savings-funded
  one-offs netted);
* spending: `real_spend.classified_rows` verdicts, month to date, refunds
  netting against spending (a refund never counts as income);
* card pending: `pending.card_pending`;
* the walk's tail: the rows of the snapshot's own Left to Spend explanation,
  so the walk can't drift from `compute_budget_snapshot(...).left_to_spend`.

"Spent so far" leaves out what bills and one-offs already hold:

* a checking row linked to a recurring item (it is that bill);
* card rows up to the card-linked bills that have fallen due so far (card
  rows carry no recurring link, so the bills are taken out by amount, as
  Left to Spend's "Card bills already charged" does), never below zero;
* a real charge matched to a settled one-off (same card or account, same
  amount, within `ONE_OFF_MATCH_DAYS` of its settled date), one row per
  one-off.

Card payments and transfers are already not spend (real_spend). Fresh
pending card charges are added on top.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from backend import models, schemas
from backend.services.explain import ExplainBuilder
from backend.services.month_base import MonthBase, build_month_base, card_bill_occurrences
from backend.services.pending import card_pending
from backend.services.primary_account import primary_checking
from backend.services.real_spend import ClassifiedRow, active_cards, classified_rows

ZERO = Decimal("0")
ONE_OFF_MATCH_DAYS = 3
_CENT = Decimal("0.01")


def _settled_one_off_row_ids(
    db: Session, base: MonthBase, spend_rows: list[ClassifiedRow],
) -> set[int]:
    """`id(row)` of the spend rows that settled one-offs already hold. Each
    settled outflow one-off claims at most one row, closest date first."""
    settled = [
        o for o in base.one_offs
        if o.settled and o.direction == models.PlannedDirection.outflow and o.planned_expense_id
    ]
    if not settled:
        return set()
    plans = {
        p.id: p for p in db.query(models.PlannedExpense).filter(
            models.PlannedExpense.id.in_([o.planned_expense_id for o in settled]),
        ).all()
    }
    claimed: set[int] = set()
    for o in sorted(settled, key=lambda o: o.date):
        plan = plans.get(o.planned_expense_id)
        if plan is None:
            continue
        best: ClassifiedRow | None = None
        for r in spend_rows:
            if id(r) in claimed or abs(r.verdict.amount - o.amount) >= _CENT:
                continue
            if plan.card_id is not None:
                if r.source != "card" or r.row.card_id != plan.card_id:
                    continue
            elif plan.account_id is not None:
                if r.source != "checking" or r.row.account_id != plan.account_id:
                    continue
            gap = abs((r.row.date - o.date).days)
            if gap > ONE_OFF_MATCH_DAYS:
                continue
            if best is None or gap < abs((best.row.date - o.date).days):
                best = r
        if best is not None:
            claimed.add(id(best))
    return claimed


def _income_children(base: MonthBase) -> list[schemas.ExplainChild]:
    children = [schemas.ExplainChild(
        label="Income this month", amount=base.income_total - base.ss_boost_total,
        note="Every paycheck and other income landing this month",
    )]
    if base.ss_boost_total:
        children.append(schemas.ExplainChild(
            label="Social Security max", amount=base.ss_boost_total,
            note="Wage base met, so paychecks no longer have Social Security withheld",
        ))
    return children


def available_to_spend(db: Session, user: models.User, as_of: date) -> schemas.AvailableToSpend:
    first = as_of.replace(day=1)
    base = build_month_base(db, user, as_of.year, as_of.month)

    rows = [
        r for r in classified_rows(db, user.id, first, as_of)
        if r.verdict.kind == "spend"
        # A checking row tied to a recurring item is that bill, already in bills.
        and not (r.source == "checking" and r.row.recurring_item_id is not None)
    ]
    held = _settled_one_off_row_ids(db, base, rows)
    rows = [r for r in rows if id(r) not in held]
    checking_spent = sum((r.verdict.amount for r in rows if r.source == "checking"), ZERO)
    card_posted = sum((r.verdict.amount for r in rows if r.source == "card"), ZERO)
    card_bills_charged = sum(
        (o.amount for o in card_bill_occurrences(base) if o.date <= as_of), ZERO,
    )
    card_spent = max(card_posted - card_bills_charged, ZERO)
    pending = sum((card_pending(c, as_of) for c in active_cards(db, user.id)), ZERO)
    spent = checking_spent + card_spent + pending

    income = base.income_total
    bills = base.expense_total
    one_offs_net = base.one_off_out_total - base.one_off_in_total
    available = income - bills - one_offs_net - spent

    explain = (
        ExplainBuilder("Available to Spend")
        .start("Income this month", income,
               note="Every paycheck and other income landing this month",
               children=_income_children(base))
        .subtract("Recurring bills this month", bills,
                  note="Every bill charged this month at this month's amount; quarterly and "
                       "yearly bills in the month they're due")
        .subtract("One-offs this month", one_offs_net,
                  note="Planned one-off purchases less one-off inflows landing this month")
        .subtract("Spent so far", spent,
                  note="Real spending this month not already in bills or one-offs, refunds "
                       "netted, plus card charges that haven't posted yet",
                  children=[
                      schemas.ExplainChild(label="Checking spending", amount=checking_spent),
                      schemas.ExplainChild(
                          label="Card spending", amount=card_spent,
                          note="Posted card purchases, less the card bills already counted above"),
                      schemas.ExplainChild(label="Pending card charges", amount=pending),
                  ])
        .build(available)
    )

    return schemas.AvailableToSpend(
        monthly_income=income, committed_expenses=bills, one_offs_net=one_offs_net,
        spent_this_month=spent, available=available, explain=explain,
        to_left_to_spend=_walk_to_left_to_spend(
            db, user, as_of, base, available, checking_spent, card_spent + pending,
        ),
    )


def _walk_to_left_to_spend(
    db: Session, user: models.User, as_of: date, base: MonthBase, available: Decimal,
    checking_spent: Decimal, card_and_pending_spent: Decimal,
) -> schemas.Explanation | None:
    account = primary_checking(db, user.id)
    if account is None:
        return None
    from backend.services.budget_snapshot import compute_budget_snapshot
    snapshot = compute_budget_snapshot(db, user, account.id, as_of)
    builder = (
        ExplainBuilder("From Available to Spend to Left to Spend")
        .start("Available to Spend", available)
        .subtract("Groceries budget", base.groceries_budget,
                  note="Set aside for groceries, so it isn't spendable")
        .subtract("Savings set aside", base.committed_savings,
                  note="Moved to savings each month, so it isn't spendable")
        .add("Checking spending so far", checking_spent,
             note="Left to Spend counts card spending only, so this comes back")
        .add("Card spending and pending so far", card_and_pending_spent,
             note="Added back here, then counted the way Left to Spend counts card spending")
    )
    # Left to Spend's own card rows, carried over as they are so the walk ends
    # on its figure exactly. The first row is its starting Leftover.
    for row in snapshot.explain["left_to_spend"].rows[1:]:
        if row.op in ("add", "subtract"):
            getattr(builder, row.op)(row.label, row.amount, row.note, row.children)
    return builder.build(snapshot.left_to_spend)
