"""Build a group of installment legs for a split one-off.

See docs/superpowers/specs/2026-11-20-split-one-off-installments-design.md. A
split one-off is 2-6 dated `PlannedExpense` rows ("legs") that together stand
in for a single purchase billed over time -- Leia's $600.00 dental work paid
in two $300.00 installments, say. Every leg:

  - shares one `account_id`/`card_id`, set once for the whole group (no
    per-leg override -- the UI never asks for one);
  - is outflow-only (a split one-off is never modelled as income);
  - gets its ordinal baked into `name` at creation ("Leia dental (1 of 2)"),
    never recomputed later, so renaming or reordering legs after creation
    can't desync the label from reality;
  - leaves the funding fields (`funding_account_id`/`funding_amount`/
    `funding_lead_days`) null -- this flow never exposes them, so a split
    purchase is always paid out of cash flow, never savings;
  - links back to the group via `installment_group_id`, set to the first
    (lowest-ordinal) leg's own id once that id exists.

Flushes only; the caller commits -- same convention as apply_settlement and
auto_settle_planned_expenses.
"""
from sqlalchemy.orm import Session

from backend import models, schemas

MIN_INSTALLMENTS = 2
MAX_INSTALLMENTS = 6


def create_installment_group(
    db: Session, user: models.User, body: schemas.PlannedExpenseInstallmentsCreate,
) -> list[models.PlannedExpense]:
    n = len(body.legs)
    legs = [
        models.PlannedExpense(
            user_id=user.id,
            name=f"{body.name} ({i} of {n})",
            amount=leg.amount,
            expected_date=leg.expected_date,
            direction=models.PlannedDirection.outflow,
            notes=body.notes,
            category_id=body.category_id,
            account_id=body.account_id,
            card_id=body.card_id,
        )
        for i, leg in enumerate(body.legs, start=1)
    ]
    for leg in legs:
        db.add(leg)
    db.flush()

    group_id = legs[0].id
    for leg in legs:
        leg.installment_group_id = group_id
    db.flush()

    return legs
