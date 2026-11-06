"""Settle a planned one-off once its real charge shows up in a bank sync.

A PlannedExpense is a prediction that only left the forecast when the user
settled it by hand. Until then it double-counted:

  - card-routed (`card_id`): the plan is its own "<name> (via <card>)" line
    on the card's payoff date, while the real charge -- pending first
    (inside the cycle estimate's `pending`), posted later (inside the card
    balance) -- is paid off by the card's own payoff/estimate line;
  - checking-routed (`account_id`): nothing suppresses a planned line
    against a real transaction that already moved the balance, so a charge
    or deposit that lands before `expected_date` was counted twice.

Run once per user after every bank sync (bank_sync_service.settle_after_sync).
Matching, per unsettled plan routed to a card or an account:

  - same card (`card_id` wins) or same account (`account_id`);
  - same direction: outflow = charge/debit, inflow = refund/credit;
  - |charge| within $1.00 of the planned amount;
  - charge dated in [expected_date - 7 days, expected_date + 14 days];
  - pending rows and posted rows both count; card payments and transfers
    between the user's own accounts never do.

Each real charge settles at most one plan. Pairs are taken best-first
(closest amount, then closest date). Plans that are already settled claim
their charge first, against `actual_amount`, so a charge that settled plan A
while pending can't settle plan B again once it posts under a new row.

Savings-funded plans (`funding_account_id`) are never auto-settled: settling
also removes the projected funding transfer from the forecast, and nothing
records whether that transfer really happened. They still claim their
charge, so it can't settle some other plan instead. Plans with neither a
card nor an account apply to every account and are left alone.

Never un-settles. Flushes only; the caller commits.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from backend import models
from backend.services.card_matching import match_payment_card
from backend.services.spending_helpers import is_card_payment, looks_like_internal_transfer

logger = logging.getLogger(__name__)

AMOUNT_TOLERANCE = Decimal("1.00")
DAYS_BEFORE = 7
DAYS_AFTER = 14


@dataclass(frozen=True)
class Settlement:
    planned_expense_id: int
    settled_on: date
    actual_amount: Decimal


@dataclass(frozen=True)
class _Charge:
    key: tuple[str, int]  # (table, row id) -- one real charge, one plan
    target: tuple[str, int]  # ("card", card_id) or ("account", account_id)
    is_inflow: bool
    amount: Decimal  # magnitude
    date: date


def apply_settlement(expense: models.PlannedExpense, settled_on: date, actual_amount: Decimal | None) -> None:
    """The one place a settlement is written -- the manual settle endpoint
    and auto-settle both go through it. Deliberately leaves `amount` alone:
    the estimate beside the actual is what makes the next estimate better.
    A linked Adventures TripItem needs nothing here: sync_trip_planned_expenses
    treats a settled row as history and marks its item paid."""
    expense.settled_on = settled_on
    expense.actual_amount = actual_amount


def _target(pe: models.PlannedExpense) -> tuple[str, int] | None:
    if pe.card_id is not None:
        return ("card", pe.card_id)
    if pe.account_id is not None:
        return ("account", pe.account_id)
    return None


def _charges(db: Session, user_id: int, lo: date, hi: date) -> list[_Charge]:
    """Every real money movement in [lo, hi] a plan could stand for, signed
    into (direction, magnitude). Card tables: positive = charge. Checking
    tables: negative = money out."""
    out: list[_Charge] = []
    cards = db.query(models.CreditCard).filter(models.CreditCard.user_id == user_id).all()

    def card_row(table: str, row, merchant: str | None) -> None:
        if row.amount == 0 or is_card_payment(merchant):
            return
        out.append(_Charge((table, row.id), ("card", row.card_id), row.amount < 0, abs(row.amount), row.date))

    def account_row(table: str, row) -> None:
        if row.amount == 0:
            return
        if match_payment_card(cards, row.description) is not None or looks_like_internal_transfer(row.description):
            return
        out.append(_Charge((table, row.id), ("account", row.account_id), row.amount > 0, abs(row.amount), row.date))

    for r in db.query(models.CardPendingTransaction).filter(
        models.CardPendingTransaction.user_id == user_id,
        models.CardPendingTransaction.date.between(lo, hi),
    ).all():
        card_row("card_pending", r, r.merchant)
    for r in db.query(models.CreditCardTransaction).filter(
        models.CreditCardTransaction.user_id == user_id,
        models.CreditCardTransaction.date.between(lo, hi),
    ).all():
        card_row("card_posted", r, r.merchant)
    for r in db.query(models.AccountPendingTransaction).filter(
        models.AccountPendingTransaction.user_id == user_id,
        models.AccountPendingTransaction.date.between(lo, hi),
    ).all():
        account_row("account_pending", r)
    for r in db.query(models.Transaction).filter(
        models.Transaction.user_id == user_id,
        models.Transaction.is_actual == True,
        models.Transaction.date.between(lo, hi),
    ).all():
        account_row("account_posted", r)
    return out


def _ranked_pairs(plans: list[tuple[models.PlannedExpense, Decimal]], charges: list[_Charge]):
    """(amount gap, date gap, plan, charge) for every compatible pair, best first."""
    by_target: dict[tuple[str, int], list[_Charge]] = {}
    for c in charges:
        by_target.setdefault(c.target, []).append(c)
    pairs = []
    for pe, want in plans:
        is_inflow = pe.direction == models.PlannedDirection.inflow
        lo = pe.expected_date - timedelta(days=DAYS_BEFORE)
        hi = pe.expected_date + timedelta(days=DAYS_AFTER)
        for c in by_target.get(_target(pe), ()):
            gap = abs(c.amount - want)
            if c.is_inflow != is_inflow or gap > AMOUNT_TOLERANCE or not lo <= c.date <= hi:
                continue
            pairs.append((gap, abs((c.date - pe.expected_date).days), pe, c))
    pairs.sort(key=lambda p: (p[0], p[1], p[2].expected_date, p[2].id, p[3].date, p[3].key))
    return pairs


def auto_settle_planned_expenses(db: Session, user_id: int) -> list[Settlement]:
    routed = (
        models.PlannedExpense.user_id == user_id,
        (models.PlannedExpense.card_id.isnot(None)) | (models.PlannedExpense.account_id.isnot(None)),
    )
    open_plans = db.query(models.PlannedExpense).filter(
        *routed, models.PlannedExpense.settled_on.is_(None),
    ).all()
    if not open_plans:
        return []

    lo = min(pe.expected_date for pe in open_plans) - timedelta(days=DAYS_BEFORE)
    hi = max(pe.expected_date for pe in open_plans) + timedelta(days=DAYS_AFTER)
    charges = _charges(db, user_id, lo, hi)
    if not charges:
        return []

    # Settled plans whose window could reach a charge in [lo, hi]. Only those
    # with an actual_amount ever matched real money ("settled, never
    # happened" is recorded with no amount).
    settled_plans = db.query(models.PlannedExpense).filter(
        *routed,
        models.PlannedExpense.settled_on.isnot(None),
        models.PlannedExpense.actual_amount.isnot(None),
        models.PlannedExpense.expected_date.between(lo - timedelta(days=DAYS_AFTER), hi + timedelta(days=DAYS_BEFORE)),
    ).all()

    claimed: set[tuple[str, int]] = set()
    done: set[int] = set()
    for _gap, _days, pe, c in _ranked_pairs([(pe, abs(pe.actual_amount)) for pe in settled_plans], charges):
        if pe.id not in done and c.key not in claimed:
            done.add(pe.id)
            claimed.add(c.key)

    pairs = _ranked_pairs([(pe, abs(pe.amount)) for pe in open_plans], charges)
    settled: list[Settlement] = []
    for gap, days, pe, c in pairs:
        if pe.id in done or c.key in claimed:
            continue
        done.add(pe.id)
        claimed.add(c.key)
        ties = sum(1 for g, d, p, o in pairs if p.id == pe.id and (g, d) == (gap, days)
                   and o.key != c.key and o.key not in claimed)
        if ties:
            logger.info(
                "Planned expense %s: %d equally good charges; settled against %s",
                pe.id, ties + 1, c.key,
            )
        if pe.funding_account_id is not None:
            logger.info("Planned expense %s matched %s but is savings-funded; left for the user", pe.id, c.key)
            continue
        apply_settlement(pe, c.date, c.amount)
        settled.append(Settlement(pe.id, c.date, c.amount))
        logger.info("Planned expense %s auto-settled on %s against %s", pe.id, c.date, c.key)
    db.flush()
    return settled


def settle_after_sync(db: Session, user_ids) -> None:
    """Run auto-settle once per user after a sync's providers have all
    finished, committing per user. A failure here must never fail the sync
    that already committed, nor stop the next user."""
    for user_id in sorted(set(user_ids)):
        try:
            auto_settle_planned_expenses(db, user_id)
            db.commit()
        except Exception as exc:  # noqa: BLE001 -- best-effort after a committed sync
            logger.error("Planned-expense auto-settle failed for user %s: %s", user_id, exc)
            db.rollback()
