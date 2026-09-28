"""Which budget lines are assigned out of the leftover, and how their
allocations resolve under the per-user carry-forward setting.

One place for the rule so the Budget page, the Spending page and the weekly
email can't disagree about whether a bucket is "not assigned yet".
"""
from __future__ import annotations
from sqlalchemy.orm import Session
from backend import models

# Already subtracted inside budget_snapshot's `leftover`. Letting them be
# assigned from the leftover again would count them twice.
LEFTOVER_COMMITTED_NAMES = frozenset({"Savings", "Groceries"})


def assignable_category_ids(db: Session, user_id: int) -> set[int]:
    """Leaf, discretionary expense categories with no active bills.

    A category with active recurring items is committed -- its amount is the
    sum of its bills. Giving it a manual budget too is how Subscriptions
    ended up counted twice (once inside leftover, once as an allocation).
    """
    cats = db.query(models.Category).filter(
        models.Category.user_id == user_id,
        models.Category.type == models.CategoryType.expense,
        models.Category.is_discretionary == True,
    ).all()
    parent_ids = {
        pid for (pid,) in db.query(models.Category.parent_id).filter(
            models.Category.user_id == user_id,
            models.Category.parent_id.isnot(None),
        ).all()
    }
    billed_ids = {
        cid for (cid,) in db.query(models.RecurringItem.category_id).filter(
            models.RecurringItem.user_id == user_id,
            models.RecurringItem.type == models.RecurringType.expense,
            models.RecurringItem.is_active == True,
            models.RecurringItem.category_id.isnot(None),
        ).all()
    }
    return {
        c.id for c in cats
        if c.id not in parent_ids
        and c.id not in billed_ids
        and c.name not in LEFTOVER_COMMITTED_NAMES
    }


def drop_uncarried_defaults(
    allocations: list[models.BudgetAllocation],
    user: models.User,
    assignable_ids: set[int],
) -> list[models.BudgetAllocation]:
    """With carry-forward off, an assignable bucket's month=0 row does not
    stand in for a month nobody assigned. The row is ignored, not deleted,
    so turning the setting back on restores it."""
    if user.budget_carry_forward:
        return list(allocations)
    return [a for a in allocations if not (a.month == 0 and a.category_id in assignable_ids)]
