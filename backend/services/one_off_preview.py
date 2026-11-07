"""Preview a draft one-off against the real Safety Margin, writing nothing.

Reuses `compute_budget_snapshot` and `card_payment_plan` with a transient
PlannedExpense in a ScenarioProposal -- the same path a scenario takes -- so
the preview cannot drift from what the Dashboard shows after the one-off is
committed. Spendable this week is deliberately not previewed: the snapshot
keeps proposals out of its flat monthly aggregates, so it would not move here
but would after commit.
"""
import logging
from datetime import date, timedelta

from sqlalchemy.orm import Session

from backend import models, schemas
from backend.services.budget_snapshot import compute_budget_snapshot
from backend.services.card_payment_model import card_payoff_on
from backend.services.forecast_engine import ScenarioProposal, _card_payoff_date_for_charge

logger = logging.getLogger(__name__)


def preview_one_off(
    db: Session, user: models.User, account_id: int, draft: schemas.PlannedExpenseCreate,
) -> schemas.OneOffPreviewOut:
    # Mirrors the fields create_planned_expense persists, so the preview
    # matches what committing the same draft produces.
    pe = models.PlannedExpense(
        id=-1, user_id=user.id, name=draft.name, amount=draft.amount,
        expected_date=draft.expected_date, notes=draft.notes,
        category_id=draft.category_id, account_id=draft.account_id,
        card_id=draft.card_id, direction=draft.direction,
    )
    proposal = ScenarioProposal(expenses=(pe,))

    base = compute_budget_snapshot(db, user, account_id)
    with_it = compute_budget_snapshot(db, user, account_id, proposal=proposal)

    card_payment = None
    if draft.card_id is not None:
        account = db.query(models.Account).filter(
            models.Account.id == account_id, models.Account.user_id == user.id,
        ).first()
        card = db.query(models.CreditCard).filter(
            models.CreditCard.id == draft.card_id, models.CreditCard.user_id == user.id,
            models.CreditCard.is_active == True,
        ).first()
        if account is not None and card is not None:
            today = date.today()
            due = _card_payoff_date_for_charge(card, draft.expected_date)
            end = max(draft.expected_date, due) + timedelta(days=1)
            before = card_payoff_on(db, user, account, card, due, today, end, None)
            after = card_payoff_on(db, user, account, card, due, today, end, proposal)
            card_payment = schemas.CardPaymentBeforeAfter(
                card_id=card.id, due=due, before=before, after=after, delta=after - before)

    if db.new or db.dirty:
        logger.warning("one-off preview left pending session changes; rolling back")
        db.rollback()

    return schemas.OneOffPreviewOut(
        safety_margin_weekly=schemas.BeforeAfter(
            before=base.safety_margin_weekly, after=with_it.safety_margin_weekly),
        safety_margin=schemas.BeforeAfter(before=base.safety_margin, after=with_it.safety_margin),
        card_payment=card_payment,
    )
