"""Zero-based view of the month: what is already committed (bills, Savings,
Groceries) and how much of the rest has been assigned to buckets.

Reads `leftover` from budget_snapshot and never changes it -- classifying a
bill only moves it between committed rows, so the total is fixed.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import date
from decimal import Decimal
from sqlalchemy.orm import Session
from backend import models, schemas
from backend.services.budget_buckets import assignable_category_ids, drop_uncarried_defaults
from backend.services.budget_snapshot import leftover_children, leftover_parts, leftover_share
from backend.services.explain import ExplainBuilder
from backend.services.recurring_math import monthly_equivalent

ZERO = Decimal("0")


def compute_left_to_budget(db: Session, user: models.User, year: int, month: int) -> schemas.LeftToBudgetOut:
    as_of = date(year, month, 1)
    parts = leftover_parts(db, user, as_of)

    categories = db.query(models.Category).filter(models.Category.user_id == user.id).all()
    cat_by_id = {c.id: c for c in categories}
    cat_id_by_name = {c.name: c.id for c in categories}

    items = db.query(models.RecurringItem).filter(
        models.RecurringItem.user_id == user.id,
        models.RecurringItem.type == models.RecurringType.expense,
        models.RecurringItem.is_active == True,
    ).all()

    bills_by_cat: dict[int | None, list[schemas.CommittedBill]] = defaultdict(list)
    for item in items:
        share = leftover_share(item, as_of)
        if share == ZERO:
            continue
        bills_by_cat[item.category_id].append(
            schemas.CommittedBill(recurring_item_id=item.id, name=item.name, amount=share)
        )

    def row(cid: int | None, name: str, bills: list[schemas.CommittedBill]) -> schemas.CommittedRow:
        bills = sorted(bills, key=lambda b: b.amount, reverse=True)
        return schemas.CommittedRow(
            category_id=cid, category_name=name,
            amount=sum((b.amount for b in bills), ZERO), items=bills,
        )

    committed = [
        row(cid, cat_by_id[cid].name, bills)
        for cid, bills in bills_by_cat.items()
        if cid is not None and cid in cat_by_id
    ]
    committed.sort(key=lambda r: r.amount, reverse=True)
    # A bill pointing at a category that no longer exists is as unclassified
    # as one with no category at all.
    orphaned = [b for cid, bills in bills_by_cat.items() if cid is None or cid not in cat_by_id for b in bills]
    if orphaned:
        committed.append(row(None, "Unclassified", orphaned))
    if parts.committed_savings:
        committed.append(schemas.CommittedRow(
            category_id=cat_id_by_name.get("Savings"), category_name="Savings", amount=parts.committed_savings,
        ))
    if parts.groceries_budget:
        committed.append(schemas.CommittedRow(
            category_id=cat_id_by_name.get("Groceries"), category_name="Groceries", amount=parts.groceries_budget,
        ))

    uncategorized = [i for i in items if i.category_id is None or i.category_id not in cat_by_id]

    assignable_ids = assignable_category_ids(db, user.id)
    allocations = db.query(models.BudgetAllocation).filter(
        models.BudgetAllocation.user_id == user.id,
        models.BudgetAllocation.year == year,
        models.BudgetAllocation.month.in_([0, month]),
        models.BudgetAllocation.category_id.in_(list(assignable_ids)),
    ).all() if assignable_ids else []
    allocations = drop_uncarried_defaults(allocations, user, assignable_ids)
    budget_by_cat: dict[int, Decimal] = {}
    for a in sorted(allocations, key=lambda x: x.month):  # month-specific wins
        budget_by_cat[a.category_id] = a.budgeted_amount

    assignable = [
        schemas.AssignableRow(
            category_id=c.id, category_name=c.name,
            assigned=budget_by_cat.get(c.id, ZERO), is_set=c.id in budget_by_cat,
        )
        for c in sorted((cat_by_id[i] for i in assignable_ids), key=lambda c: (c.sort_order, c.name))
    ]
    assigned_total = sum((r.assigned for r in assignable), ZERO)

    unassigned_builder = ExplainBuilder("Left to budget").start(
        "Leftover", parts.leftover,
        note="Income after bills, savings and groceries",
        children=leftover_children(parts),
    )
    for row in assignable:
        if row.assigned:
            unassigned_builder.subtract(row.category_name, row.assigned, note="Assigned this month")
    explain_unassigned = unassigned_builder.build(parts.leftover - assigned_total)

    return schemas.LeftToBudgetOut(
        year=year, month=month,
        leftover=parts.leftover,
        committed=committed,
        unclassified_count=len(uncategorized),
        unclassified_amount=sum((monthly_equivalent(i) for i in uncategorized), ZERO),
        assignable=assignable,
        assigned_total=assigned_total,
        unassigned=parts.leftover - assigned_total,
        carry_forward=bool(user.budget_carry_forward),
        explain_unassigned=explain_unassigned,
    )
