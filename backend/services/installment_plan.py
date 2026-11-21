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
import logging
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from backend import models, schemas
from backend.services.budget_snapshot import compute_budget_snapshot
from backend.services.forecast_engine import ScenarioProposal, _card_payoff_date_for_charge

logger = logging.getLogger(__name__)

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


def preview_installment_group(
    db: Session, user: models.User, account_id: int, body: schemas.PlannedExpenseInstallmentsCreate,
) -> schemas.InstallmentsPreviewOut:
    """Combined Safety Margin preview for a whole group of installment legs
    at once -- the group analogue of `one_off_preview.preview_one_off`.

    Builds one transient `PlannedExpense` per leg (negative ids, never
    `db.add()`ed -- see `ScenarioProposal`'s own id convention in
    `forecast_engine.py`) and splices them all into a single
    `ScenarioProposal`, so the preview walks the exact same forecast path a
    committed group would, just without persisting anything.

    When `card_id` is set, legs due the same statement cycle collapse into
    one `CardPaymentImpact` with their amounts summed -- so two installments
    due the same cycle still show as a single line, matching today's
    single-leg behaviour, while installments spanning multiple cycles show
    one line per distinct due date."""
    n = len(body.legs)
    legs = [
        models.PlannedExpense(
            id=-(i + 1),
            user_id=user.id,
            name=f"{body.name} ({i + 1} of {n})",
            amount=leg.amount,
            expected_date=leg.expected_date,
            notes=body.notes,
            category_id=body.category_id,
            account_id=body.account_id,
            card_id=body.card_id,
            direction=models.PlannedDirection.outflow,
        )
        for i, leg in enumerate(body.legs)
    ]
    proposal = ScenarioProposal(expenses=tuple(legs))

    base = compute_budget_snapshot(db, user, account_id)
    with_it = compute_budget_snapshot(db, user, account_id, proposal=proposal)

    card_payments: list[schemas.CardPaymentImpact] = []
    if body.card_id is not None:
        card = db.query(models.CreditCard).filter(
            models.CreditCard.id == body.card_id, models.CreditCard.user_id == user.id,
            models.CreditCard.is_active == True,
        ).first()
        if card is not None:
            by_due: dict[date, Decimal] = {}
            for leg in legs:
                due = _card_payoff_date_for_charge(card, leg.expected_date)
                by_due[due] = by_due.get(due, Decimal("0")) + leg.amount
            card_payments = [
                schemas.CardPaymentImpact(card_id=card.id, due=due, amount=amount)
                for due, amount in sorted(by_due.items())
            ]

    if db.new or db.dirty:
        logger.warning("installment group preview left pending session changes; rolling back")
        db.rollback()

    return schemas.InstallmentsPreviewOut(
        safety_margin_weekly=schemas.BeforeAfter(
            before=base.safety_margin_weekly, after=with_it.safety_margin_weekly),
        safety_margin=schemas.BeforeAfter(before=base.safety_margin, after=with_it.safety_margin),
        card_payments=card_payments,
    )
