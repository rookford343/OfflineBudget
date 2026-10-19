"""Set Budgets as one list: Committed (from Recurring) + Flexible = Budget.

Replaces the old Left to budget panel, whose "leftover" used a different
model of the month (monthly income only, quarterly bills smoothed, Savings
and Groceries pre-subtracted) and whose "assigned" counted only a narrow set
of buckets -- so it read "$0 assigned" next to a list of budget lines that
added up to thousands, and the two never reconciled.

The rules here:

* Committed comes from `build_month_summary`, the exact source of the
  Recurring tab's Income / Expenses / Left over strip, grouped by category.
  Planned one-offs count too, because that strip counts them. So
  income_total - committed_total == the Recurring tab's left_over, always.
* Flexible is the stored BudgetAllocation for the month, resolved the way
  compute_overview resolves it (month row beats the every-month row, and an
  assignable bucket's every-month row is ignored while carry-forward is off).
* Budget = Committed + Flexible, per category.
* A line stored on a PARENT category is the group's total. The group's
  committed and its children's flexible count inside it, and whatever is left
  shows as "rest". If the rows already exceed it, the rows win and the gap is
  reported -- bills can't be budgeted under, and counting the parent line on
  top of its children's bills would count the same dollars twice.

Read-only: nothing here writes budget data.
"""
from __future__ import annotations
from collections import defaultdict
from decimal import Decimal
from sqlalchemy.orm import Session
from backend import models, schemas
from backend.schemas import ExplainChild
from backend.services.budget_buckets import assignable_category_ids, drop_uncarried_defaults
from backend.services.budget_calculator import compute_overview
from backend.services.explain import ExplainBuilder
from backend.services.month_summary import build_month_summary

ZERO = Decimal("0")
UNCATEGORIZED = "Not in a category"


def _by_name(c: models.Category):
    return (c.name.lower(), c.id)


def _is_income(cat: models.Category) -> bool:
    return (cat.type.value if hasattr(cat.type, "value") else str(cat.type)) == "income"


def _items_by_category(db, user_id, summary, cat_ok):
    """{category_id or None: [PlanItem]} for this month's committed money.

    Occurrences of one recurring item are folded into a single item (a weekly
    bill fires four or five times). An item whose category is missing or is
    an income category lands under None.
    """
    rec_ids = {o.recurring_item_id for o in summary.monthly_bills + summary.periodic_due}
    rec_cat = {
        i.id: i.category_id for i in db.query(models.RecurringItem).filter(
            models.RecurringItem.user_id == user_id,
            models.RecurringItem.id.in_(rec_ids),
        ).all()
    } if rec_ids else {}
    pe_ids = {o.planned_expense_id for o in summary.one_offs}
    pe_cat = {
        p.id: p.category_id for p in db.query(models.PlannedExpense).filter(
            models.PlannedExpense.user_id == user_id,
            models.PlannedExpense.id.in_(pe_ids),
        ).all()
    } if pe_ids else {}

    def usable(cid):
        return cid if cid is not None and cat_ok(cid) else None

    folded: dict[tuple, schemas.PlanItem] = {}
    where: dict[tuple, int | None] = {}
    for o in summary.monthly_bills + summary.periodic_due:
        key = ("r", o.recurring_item_id)
        if key in folded:
            folded[key].amount += o.amount
            folded[key].times += 1
        else:
            folded[key] = schemas.PlanItem(name=o.name, amount=o.amount, recurring_item_id=o.recurring_item_id)
            where[key] = usable(rec_cat.get(o.recurring_item_id))
    for o in summary.one_offs:
        if o.direction != models.PlannedDirection.outflow:
            continue
        key = ("p", o.planned_expense_id)
        folded[key] = schemas.PlanItem(name=o.name, amount=o.amount, planned_expense_id=o.planned_expense_id)
        where[key] = usable(pe_cat.get(o.planned_expense_id))

    out: dict[int | None, list[schemas.PlanItem]] = defaultdict(list)
    for key, item in folded.items():
        out[where[key]].append(item)
    for items in out.values():
        items.sort(key=lambda i: (-i.amount, i.name))
    return out


def compute_budget_plan(db: Session, user: models.User, year: int, month: int) -> schemas.BudgetPlanOut:
    summary = build_month_summary(db, user.id, year, month)
    categories = db.query(models.Category).filter(models.Category.user_id == user.id).all()
    plan_cats = {c.id: c for c in categories if not _is_income(c)}
    children_of: dict[int, list[models.Category]] = defaultdict(list)
    for c in plan_cats.values():
        if c.parent_id is not None and c.parent_id in plan_cats:
            children_of[c.parent_id].append(c)

    items_by_cat = _items_by_category(db, user.id, summary, lambda cid: cid in plan_cats)
    committed_of = {cid: sum((i.amount for i in items), ZERO) for cid, items in items_by_cat.items()}

    # Flexible: the same month resolution as compute_overview, plus which
    # categories actually have a governing allocation (a $0 line is a line).
    assignable_ids = assignable_category_ids(db, user.id)
    allocations = db.query(models.BudgetAllocation).filter(
        models.BudgetAllocation.user_id == user.id,
        models.BudgetAllocation.year == year,
        models.BudgetAllocation.month.in_([0, month]),
    ).all()
    allocations = drop_uncarried_defaults(allocations, user, assignable_ids)
    flex_of: dict[int, Decimal] = {}
    for a in sorted(allocations, key=lambda x: x.month):  # month-specific wins
        flex_of[a.category_id] = a.budgeted_amount

    overview = {r.category_id: r for r in compute_overview(db, user.id, year, month)}

    def own_actual(cid: int) -> Decimal:
        # compute_overview rolls children into their parent's actual_total.
        rolled = overview[cid].actual_total if cid in overview else ZERO
        return rolled - sum((overview[k.id].actual_total for k in children_of.get(cid, []) if k.id in overview), ZERO)

    def make_row(c: models.Category, *, own_bills_only: bool = False) -> schemas.PlanRow:
        committed = committed_of.get(c.id, ZERO)
        flexible = ZERO if own_bills_only else flex_of.get(c.id, ZERO)
        return schemas.PlanRow(
            category_id=c.id,
            category_name=f"{c.name} (own bills)" if own_bills_only else c.name,
            committed=committed, flexible=flexible, budget=committed + flexible,
            is_set=(not own_bills_only) and c.id in flex_of,
            is_assignable=c.id in assignable_ids,
            editable=not own_bills_only,
            items=items_by_cat.get(c.id, []),
        )

    def shown(r: schemas.PlanRow) -> bool:
        return r.committed != ZERO or r.is_set

    def line(cid: int, name: str, *, is_group: bool, committed, flexible, budget, actual) -> schemas.PlanTrackLine:
        ov = overview.get(cid)
        return schemas.PlanTrackLine(
            category_id=cid, category_name=name, is_group=is_group,
            committed=committed, flexible=flexible, budget=budget, actual_total=actual,
            rollover_enabled=bool(ov.rollover_enabled) if ov else False,
            rollover_balance=ov.rollover_balance if ov else ZERO,
        )

    groups: list[schemas.PlanGroup] = []
    lines: list[schemas.PlanTrackLine] = []

    for parent in sorted((c for c in plan_cats.values() if c.id in children_of), key=_by_name):
        rows = [make_row(k) for k in sorted(children_of[parent.id], key=_by_name)]
        if committed_of.get(parent.id):
            rows.insert(0, make_row(parent, own_bills_only=True))
        rows = [r for r in rows if shown(r)]
        has_line = parent.id in flex_of
        if not rows and not has_line:
            continue
        committed = sum((r.committed for r in rows), ZERO)
        row_flex = sum((r.flexible for r in rows), ZERO)
        if has_line:
            p = flex_of[parent.id]
            budget = max(p, committed + row_flex)
            group = schemas.PlanGroup(
                group_id=parent.id, group_name=parent.name, kind="parent", rows=rows,
                committed=committed, flexible=budget - committed, budget=budget,
                parent_line=p, rest=budget - committed - row_flex,
                parent_line_short=max(ZERO, committed + row_flex - p),
            )
            if budget != ZERO:
                lines.append(line(parent.id, parent.name, is_group=True, committed=committed,
                                  flexible=budget - committed, budget=budget,
                                  actual=overview[parent.id].actual_total if parent.id in overview else ZERO))
        else:
            group = schemas.PlanGroup(
                group_id=parent.id, group_name=parent.name, kind="parent", rows=rows,
                committed=committed, flexible=row_flex, budget=committed + row_flex,
            )
            for r in rows:
                if r.budget != ZERO:
                    lines.append(line(r.category_id, r.category_name, is_group=False,
                                      committed=r.committed, flexible=r.flexible, budget=r.budget,
                                      actual=own_actual(r.category_id)))
        groups.append(group)

    # Top-level categories with no children: the "Other" group, as in the
    # category picker.
    loose = [c for c in plan_cats.values()
             if c.id not in children_of and (c.parent_id is None or c.parent_id not in plan_cats)]
    other_rows = [r for r in (make_row(c) for c in sorted(loose, key=_by_name)) if shown(r)]
    if other_rows:
        groups.append(schemas.PlanGroup(
            group_name="Other", kind="other", rows=other_rows,
            committed=sum((r.committed for r in other_rows), ZERO),
            flexible=sum((r.flexible for r in other_rows), ZERO),
            budget=sum((r.budget for r in other_rows), ZERO),
        ))
        for r in other_rows:
            if r.budget != ZERO:
                lines.append(line(r.category_id, r.category_name, is_group=False,
                                  committed=r.committed, flexible=r.flexible, budget=r.budget,
                                  actual=own_actual(r.category_id)))

    category_budget_total = sum((g.budget for g in groups), ZERO)

    loose_items = items_by_cat.get(None, [])
    bills = [i for i in loose_items if i.recurring_item_id is not None]
    one_offs = [i for i in loose_items if i.planned_expense_id is not None]
    unc_rows = []
    for name, items in (("Unclassified bills", bills), ("Planned one-offs", one_offs)):
        if items:
            total = sum((i.amount for i in items), ZERO)
            unc_rows.append(schemas.PlanRow(
                category_name=name, committed=total, flexible=ZERO, budget=total,
                is_set=False, editable=False, items=items,
            ))
    if unc_rows:
        unc_total = sum((r.committed for r in unc_rows), ZERO)
        groups.append(schemas.PlanGroup(
            group_name=UNCATEGORIZED, kind="uncategorized", rows=unc_rows,
            committed=unc_total, flexible=ZERO, budget=unc_total,
        ))

    income_total = summary.income_total + summary.one_off_in_total
    committed_total = sum((g.committed for g in groups), ZERO)
    flexible_total = sum((g.flexible for g in groups), ZERO)
    left_to_assign = income_total - committed_total - flexible_total

    income_children: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for o in summary.income_items:
        income_children[o.name] += o.amount
    for o in summary.one_offs:
        if o.direction == models.PlannedDirection.inflow:
            income_children[f"{o.name} (one-off)"] += o.amount
    explain = (
        ExplainBuilder("Left to assign")
        .start("Income this month", income_total, note="Recurring income plus planned inflows",
               children=[ExplainChild(label=k, amount=v) for k, v in income_children.items()])
        .subtract("Committed", committed_total,
                  note="Recurring bills and planned one-offs this month, from the Recurring tab",
                  children=[ExplainChild(label=g.group_name, amount=g.committed)
                            for g in groups if g.committed != ZERO])
        .subtract("Flexible", flexible_total,
                  note="What you've added on top of the bills",
                  children=[ExplainChild(label=g.group_name, amount=g.flexible)
                            for g in groups if g.flexible != ZERO])
        .build(left_to_assign)
    )

    unclassified_count = len({i.recurring_item_id for i in bills})

    return schemas.BudgetPlanOut(
        year=year, month=month,
        income_total=income_total,
        committed_total=committed_total,
        flexible_total=flexible_total,
        budget_total=committed_total + flexible_total,
        left_to_assign=left_to_assign,
        recurring_left_over=summary.left_over,
        category_budget_total=category_budget_total,
        unclassified_count=unclassified_count,
        carry_forward=bool(user.budget_carry_forward),
        groups=groups,
        lines=lines,
        explain_left_to_assign=explain,
    )


def plan_budgets_for_range(db: Session, user: models.User, start, end) -> tuple[dict[int, Decimal], dict[int, Decimal]]:
    """Plan Budgets for any date range, for the Spending page.

    Returns ({category_id: row Budget}, {top-level category_id: group Budget}).
    Each month's plan is scaled by the share of that month the range covers,
    so a full single month reads exactly what Set and Track show. A
    childless top-level category's group Budget is its own row Budget.
    """
    from calendar import monthrange
    from datetime import date as _date

    rows: dict[int, Decimal] = defaultdict(lambda: ZERO)
    tops: dict[int, Decimal] = defaultdict(lambda: ZERO)
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        days = monthrange(y, m)[1]
        lo, hi = max(_date(y, m, 1), start), min(_date(y, m, days), end)
        if hi >= lo:
            share = Decimal((hi - lo).days + 1) / Decimal(days)
            plan = compute_budget_plan(db, user, y, m)
            for g in plan.groups:
                if g.kind == "uncategorized":
                    continue
                if g.kind == "parent" and g.group_id is not None:
                    tops[g.group_id] += g.budget * share
                for r in g.rows:
                    if r.category_id is None:
                        continue
                    if r.editable:
                        rows[r.category_id] += r.budget * share
                    if g.kind == "other":
                        tops[r.category_id] += r.budget * share
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return dict(rows), dict(tops)
