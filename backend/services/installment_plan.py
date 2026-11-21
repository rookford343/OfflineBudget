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


def _detach_trip_items(db: Session, user: models.User, expense: models.PlannedExpense) -> None:
    for item in db.query(models.TripItem).filter(
        models.TripItem.planned_expense_id == expense.id,
        models.TripItem.user_id == user.id,
    ).all():
        item.planned_expense_id = None


def _is_cleared(pe: models.PlannedExpense) -> bool:
    return pe.settled_on is not None and pe.actual_amount is not None


def _refund_watches(db: Session, user: models.User, group_id: int) -> list[models.PlannedExpense]:
    """Every refund-watch row already open against this group, for this
    user. These share the same self-referencing `installment_group_id` FK
    as every other leg, so a caller re-pointing survivors off a departing
    anchor (see `_retarget_group`) has to fold these in too -- they're
    deliberately excluded from `cancel_installment_group`'s own `siblings`
    query (they never participate in cascade decisions and are never
    swept), but excluding them there doesn't mean they're exempt from
    FK bookkeeping when the anchor they point at goes away."""
    return db.query(models.PlannedExpense).filter(
        models.PlannedExpense.installment_group_id == group_id,
        models.PlannedExpense.user_id == user.id,
        models.PlannedExpense.is_refund_watch.is_(True),
    ).all()


def _retarget_group(
    db: Session, departing: models.PlannedExpense, survivors: list[models.PlannedExpense], group_id: int,
) -> int:
    """`installment_group_id` is a self-referencing FK to the group's anchor
    leg (its own id, set once at creation -- see create_installment_group).
    When the row ABOUT TO BE DELETED is that anchor (`departing.id ==
    group_id`) and at least one other row will still exist afterward, every
    survivor has to be re-pointed to a new anchor -- the lowest id among
    them -- *before* the old anchor is deleted, or the survivors are left
    referencing a row that no longer exists and SQLite's FK check (on, same
    as production) rejects the delete. Returns the group id survivors (and
    any refund-watch row about to be created) should use from here on; a
    no-op when `departing` isn't the anchor, or nothing survives it."""
    if departing.id != group_id or not survivors:
        return group_id
    new_group_id = min(s.id for s in survivors)
    for s in survivors:
        s.installment_group_id = new_group_id
    db.flush()
    return new_group_id


def cancel_installment_group(db: Session, user: models.User, expense: models.PlannedExpense) -> None:
    group_id = expense.installment_group_id
    siblings = db.query(models.PlannedExpense).filter(
        models.PlannedExpense.installment_group_id == group_id,
        models.PlannedExpense.user_id == user.id,
        models.PlannedExpense.is_refund_watch.is_(False),
    ).all()

    if not any(not _is_cleared(s) for s in siblings):
        # Every leg in the group already cleared -- there's nothing left to
        # cancel, so this is just a single history row going away. The row
        # leaving might be the group's anchor itself, in which case whatever
        # else survives -- including any refund-watch already open against
        # this group, which shares the FK but is never part of `siblings`
        # -- needs a new one first (see _retarget_group).
        survivors = [s for s in siblings if s.id != expense.id]
        if expense.id == group_id:
            survivors += _refund_watches(db, user, group_id)
        # The returned id is never used again here: nothing downstream in
        # this branch creates a row that would need it, since "fully
        # resolved" never spawns a refund-watch -- the mutation inside
        # _retarget_group (not its return value) is what matters.
        _retarget_group(db, expense, survivors, group_id)
        _detach_trip_items(db, user, expense)
        db.delete(expense)
        db.flush()
        return

    cleared = [s for s in siblings if _is_cleared(s)]
    uncleared = [s for s in siblings if not _is_cleared(s)]
    old_anchor = next((s for s in uncleared if s.id == group_id), None)

    # Cleared legs survive as history (and get a refund-watch) -- re-point
    # them off the old anchor *before* anything is deleted, while it still
    # exists to validate the intermediate state. Any refund-watch already
    # open against this group from an earlier, partial cancel shares the
    # same FK and has to move with them even though it's excluded from
    # `siblings` (and from the cascade itself -- Review Focus #5).
    new_group_id = group_id
    if old_anchor is not None:
        survivors_to_retarget = cleared + _refund_watches(db, user, group_id)
        new_group_id = _retarget_group(db, old_anchor, survivors_to_retarget, group_id)

    # Create the refund-watch rows BEFORE deleting anything below. SQLite
    # reuses a freed integer id as soon as it becomes the new max+1 (this
    # table has no AUTOINCREMENT keyword), so inserting first -- while the
    # uncleared legs it's replacing still occupy their ids -- keeps a new
    # refund-watch row from ever landing on the very id a swept sibling just
    # vacated.
    for sibling in cleared:
        db.add(models.PlannedExpense(
            user_id=user.id,
            name=f"{sibling.name} — refund expected",
            amount=sibling.actual_amount,
            expected_date=date.today(),
            direction=models.PlannedDirection.inflow,
            account_id=sibling.account_id,
            card_id=sibling.card_id,
            category_id=sibling.category_id,
            installment_group_id=new_group_id,
            is_refund_watch=True,
        ))
    if cleared:
        db.flush()

    # Uncleared, non-anchor legs can always be deleted safely -- nothing
    # else is ever FK-linked to a non-anchor leg's own id.
    for sibling in uncleared:
        if sibling is old_anchor:
            continue
        _detach_trip_items(db, user, sibling)
        db.delete(sibling)
    if any(s is not old_anchor for s in uncleared):
        db.flush()

    # The anchor itself can only be deleted last, once every row that used
    # to reference it has either been swept above or re-pointed above.
    if old_anchor is not None:
        _detach_trip_items(db, user, old_anchor)
        db.delete(old_anchor)
        db.flush()
