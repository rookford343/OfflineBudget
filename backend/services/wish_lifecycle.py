"""Wish List lifecycle. Spec: docs/superpowers/specs/2026-10-07-wish-list-design.md"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from backend import models
from backend.services import scenario_service
from backend.services.wish_math import (
    net_price, financed_principal, payment_schedule, add_months, _trade_in_credit,
)
from backend.services.wish_plan import build_plan


class WishError(ValueError):
    pass


def ensure_wish_items(db: Session, user_id: int) -> None:
    have = {w.scenario_id for w in db.query(models.WishItem).filter(models.WishItem.user_id == user_id).all()}
    next_rank = (db.query(models.WishItem).filter(models.WishItem.user_id == user_id).count())
    for sc in db.query(models.ForecastScenario).filter(models.ForecastScenario.user_id == user_id).order_by(
            models.ForecastScenario.id).all():
        if sc.id not in have:
            db.add(models.WishItem(user_id=user_id, scenario_id=sc.id, rank=next_rank, price=Decimal("0"),
                                   trade_in_value=Decimal("0")))
            next_rank += 1
    db.flush()


def _own_item(db, user, item_id) -> models.WishItem:
    item = db.get(models.WishItem, item_id)
    if item is None or item.user_id != user.id:
        raise LookupError("Wish not found")
    return item


def _record(db, user, item, kind, row_id):
    db.add(models.WishCommitRow(user_id=user.id, wish_item_id=item.id, kind=kind, row_id=row_id))


def _expense(db, user, item, name, amount, when, card_id, direction=models.PlannedDirection.outflow):
    pe = models.PlannedExpense(user_id=user.id, name=name[:128], amount=amount, expected_date=when,
                               card_id=card_id, direction=direction)
    db.add(pe); db.flush()
    _record(db, user, item, "planned_expense", pe.id)


def commit_wish(db: Session, user, account_id: int, item_id: int, today: date) -> dict:
    """Commit a wish's scenario and lay down the real rows its chosen option
    implies.

    Every refusal below runs BEFORE scenario_service.commit_scenario is
    called, so a refusal never writes anything at all. commit_scenario
    commits its own transaction internally (a conditional UPDATE flips
    ForecastScenario.status draft -> committed, then db.commit()) -- a plain
    db.rollback() afterwards cannot undo that. So once it has run, any
    failure while building the purchase rows is caught and explicitly
    reversed with uncommit_scenario before re-raising, leaving no
    half-committed wish: either everything lands (the scenario is committed
    AND its purchase rows exist), or the scenario goes back to draft and no
    purchase row is left behind.

    build_plan's chosen option (`plan_option_id`) is only ever an errored
    option when every option on this item errored -- in that case
    `placement_date` can still be set from a target date, so the `when is
    None` check alone does not catch it. Refused explicitly here instead.
    """
    item = _own_item(db, user, item_id)
    if item.scenario.status == "committed":
        raise WishError("Already committed")

    plan = build_plan(db, user, account_id, today)
    entry = next(i for i in plan["items"] if i["id"] == item.id)
    when = entry["placement_date"]
    if when is None:
        raise WishError("This wish doesn't fit in the next 12 months and has no target date")

    chosen = next((o for o in entry["options"] if o["option_id"] == entry["plan_option_id"]), None)
    if chosen is None or chosen["error"] is not None:
        raise WishError(
            chosen["error"] if chosen is not None and chosen["error"] is not None
            else "No payment option is available for this wish"
        )

    option = next((o for o in item.options if o.id == entry["plan_option_id"]), None)
    name = item.scenario.name

    scenario_service.commit_scenario(db, user.id, item.scenario_id)
    try:
        if option is not None:
            if option.method in (models.WishMethod.full_checking, models.WishMethod.full_card):
                amt = net_price(item)
                if amt > 0:
                    _expense(db, user, item, name, amt, when,
                             option.card_id if option.method == models.WishMethod.full_card else None)
            else:
                down = Decimal(option.down_payment or 0)
                if down > 0:
                    _expense(db, user, item, f"{name}: down payment", down, when, option.card_id)
                sched = payment_schedule(financed_principal(item, option), option.apr or 0, option.months or 0)
                if len(sched) > 1:
                    # account_id is required on RecurringItem (NOT NULL) even
                    # when card_id is also set -- routers/recurring.py's
                    # RecurringCreate schema makes account_id mandatory
                    # unconditionally, and forecast_engine.build_forecast
                    # finds a card-paid recurring item by filtering on BOTH
                    # account_id and card_id (it's how a card's payoff gets
                    # attributed back to the checking account that ultimately
                    # feels it). Setting it to None here would violate the
                    # NOT NULL constraint and silently misroute the forecast.
                    rec = models.RecurringItem(
                        user_id=user.id, account_id=account_id, card_id=option.card_id,
                        name=f"{name}: payment"[:128], amount=sched[0],
                        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
                        day_of_month=add_months(when, 1).day, start_date=add_months(when, 1),
                        end_date=add_months(when, len(sched) - 1), is_active=True,
                    )
                    db.add(rec); db.flush()
                    _record(db, user, item, "recurring_item", rec.id)
                if sched:
                    _expense(db, user, item, f"{name}: final payment", sched[-1], add_months(when, len(sched)),
                             option.card_id)
        credit = _trade_in_credit(item)
        if credit > 0:
            _expense(db, user, item, f"{name}: trade-in credit", credit, item.trade_in_on, None,
                     direction=models.PlannedDirection.inflow)
        db.commit()
    except Exception:
        db.rollback()
        scenario_service.uncommit_scenario(db, user.id, item.scenario_id)
        raise
    return {"placement_date": when, "option_id": option.id if option else None}


def uncommit_wish(db: Session, user, item_id: int) -> dict:
    item = _own_item(db, user, item_id)
    rows = db.query(models.WishCommitRow).filter(models.WishCommitRow.wish_item_id == item.id).all()
    for r in rows:
        model = models.PlannedExpense if r.kind == "planned_expense" else models.RecurringItem
        obj = db.get(model, r.row_id)
        if obj is not None and obj.user_id == user.id:
            db.delete(obj)
        db.delete(r)
    db.flush()
    if item.scenario.status == "committed":
        scenario_service.uncommit_scenario(db, user.id, item.scenario_id)
    db.commit()
    return {"ok": True}
