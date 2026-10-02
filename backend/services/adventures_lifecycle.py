"""Adventures lifecycle writes. Spec: docs/superpowers/specs/2026-10-01-adventures-design.md

A committed trip is mirrored 1:1 into PlannedExpense rows (one per item that
still owes cash), so the Forecast needs no changes. Links live on
TripItem.planned_expense_id. Callers own the transaction (no commits here).
FK enforcement is ON in production and tests, so a link is always nulled and
flushed BEFORE its PlannedExpense is deleted.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from backend import models
from backend.services.adventures import (
    cash_owed, trip_cash_total, points_used, partner_points_received, _partner_for,
)


class LifecycleError(ValueError):
    pass


def create_trip_from_template(db: Session, user_id: int, *, name: str, destination: str | None,
                              start_date: date, end_date: date, travelers: int,
                              default_card_id: int | None) -> models.Trip:
    if end_date < start_date:
        raise LifecycleError("end date is before start date")
    trip = models.Trip(user_id=user_id, name=name, destination=destination, start_date=start_date,
                       end_date=end_date, travelers=max(travelers, 1),
                       status=models.TripStatus.planning, default_card_id=default_card_id)
    db.add(trip)
    db.flush()
    template = db.query(models.ChecklistTemplateItem).filter(
        models.ChecklistTemplateItem.user_id == user_id).order_by(
        models.ChecklistTemplateItem.sort_order, models.ChecklistTemplateItem.id).all()
    for i, t in enumerate(template):
        trip.items.append(models.TripItem(user_id=user_id, category=t.category, name=t.name,
                                          pricing=t.pricing, unit_cash=t.unit_cash,
                                          payment=models.TripPayment.cash, cash_copay=Decimal("0"),
                                          is_paid=False, sort_order=i))
    db.flush()
    return trip


def _unlink_and_delete(db: Session, item: models.TripItem, *, keep_settled: bool = True) -> None:
    if item.planned_expense_id is None:
        return
    pe = db.get(models.PlannedExpense, item.planned_expense_id)
    item.planned_expense_id = None
    db.flush()
    if pe is not None and not (keep_settled and pe.settled_on is not None):
        db.delete(pe)
        db.flush()


def sync_trip_planned_expenses(db: Session, trip: models.Trip) -> None:
    """Reconcile a COMMITTED trip's one-offs with its items. Idempotent. Paid
    items keep their (settled) row untouched. No-op unless committed."""
    if trip.status != models.TripStatus.committed:
        return
    for item in trip.items:
        if item.is_paid:
            continue
        pe = db.get(models.PlannedExpense, item.planned_expense_id) if item.planned_expense_id else None
        if pe is not None and pe.settled_on is not None:
            # Settled directly from the Planned page (e.g. reconciled while
            # the Adventures item was still marked unpaid) is history now --
            # sync must not rewrite or delete it.
            continue
        owed = cash_owed(item, trip)
        if owed <= 0:
            _unlink_and_delete(db, item)
            continue
        fields = dict(name=f"{trip.name}: {item.name}"[:128], amount=owed,
                      expected_date=item.charge_date or trip.start_date,
                      card_id=item.card_id or trip.default_card_id)
        if pe is None:
            pe = models.PlannedExpense(user_id=trip.user_id, direction=models.PlannedDirection.outflow,
                                       **fields)
            db.add(pe)
            db.flush()
            item.planned_expense_id = pe.id
        else:
            for k, v in fields.items():
                setattr(pe, k, v)
    db.flush()


def commit_trip(db: Session, trip: models.Trip) -> None:
    if trip.status != models.TripStatus.planning:
        raise LifecycleError("only a planning trip can be committed")
    trip.status = models.TripStatus.committed
    db.flush()
    sync_trip_planned_expenses(db, trip)


def uncommit_trip(db: Session, trip: models.Trip) -> None:
    if trip.status != models.TripStatus.committed:
        raise LifecycleError("only a committed trip can go back to planning")
    for item in trip.items:
        _unlink_and_delete(db, item)
    trip.status = models.TripStatus.planning
    db.flush()


def set_item_paid(db: Session, trip: models.Trip, item: models.TripItem, paid: bool, today: date) -> None:
    if item.is_paid == paid:
        return
    item.is_paid = paid
    pe = db.get(models.PlannedExpense, item.planned_expense_id) if item.planned_expense_id else None
    if pe is not None:
        pe.settled_on = today if paid else None
        pe.actual_amount = pe.amount if paid else None
    db.flush()
    if not paid:
        sync_trip_planned_expenses(db, trip)


def delete_item(db: Session, trip: models.Trip, item: models.TripItem) -> None:
    _unlink_and_delete(db, item)
    trip.items.remove(item)
    db.flush()
    sync_trip_planned_expenses(db, trip)


def delete_trip(db: Session, trip: models.Trip) -> None:
    for item in trip.items:
        _unlink_and_delete(db, item)
    db.delete(trip)
    db.flush()


def finish_plan(db: Session, trip: models.Trip, today: date) -> dict[int, int]:
    """Default balance deltas per program: transfers move points source ->
    partner, then each item's points come off its own program."""
    deltas: dict[int, int] = {}
    for it in trip.items:
        used = points_used(it)
        if it.transfer_from_program_id and it.transfer_points:
            deltas[it.transfer_from_program_id] = deltas.get(it.transfer_from_program_id, 0) - int(it.transfer_points)
            if it.points_program_id:
                partner = _partner_for(db, trip.user_id, it.transfer_from_program_id, it.points_program_id)
                if partner:
                    got = partner_points_received(partner, int(it.transfer_points), today)
                    deltas[it.points_program_id] = deltas.get(it.points_program_id, 0) + got
        if used and it.points_program_id:
            deltas[it.points_program_id] = deltas.get(it.points_program_id, 0) - used
    return deltas


def finish_trip(db: Session, trip: models.Trip, points_used_by_program: dict[int, int] | None,
                force: bool, today: date) -> dict[int, int]:
    """committed -> done. `points_used_by_program` overrides the items'
    points per program (the user's confirmed spend); transfers still apply."""
    if trip.status != models.TripStatus.committed:
        raise LifecycleError("only a committed trip can be finished")
    deltas = finish_plan(db, trip, today)
    if points_used_by_program:
        planned_use: dict[int, int] = {}
        for it in trip.items:
            if points_used(it) and it.points_program_id:
                planned_use[it.points_program_id] = planned_use.get(it.points_program_id, 0) + points_used(it)
        for pid, confirmed in points_used_by_program.items():
            deltas[pid] = deltas.get(pid, 0) + planned_use.get(pid, 0) - int(confirmed)
    programs = {pid: db.get(models.LoyaltyProgram, pid) for pid in deltas}
    negative = [p.name for pid, p in programs.items()
                if p is not None and p.user_id == trip.user_id and p.balance + deltas[pid] < 0]
    if negative and not force:
        raise LifecycleError("would go negative: " + ", ".join(sorted(negative)))
    now = datetime.now()   # local, matches date.today() in age_days
    for pid, p in programs.items():
        if p is None or p.user_id != trip.user_id or deltas[pid] == 0:
            continue
        p.balance = p.balance + deltas[pid]
        p.balance_updated_at = now
    trip.status = models.TripStatus.done
    db.flush()
    return deltas


def create_trip_fund(db: Session, trip: models.Trip) -> models.SavingsGoal:
    if trip.fund_goal_id is not None:
        raise LifecycleError("trip already has a fund")
    goal = models.SavingsGoal(user_id=trip.user_id, name=f"{trip.name} fund"[:128],
                              target_amount=trip_cash_total(trip),
                              target_date=trip.start_date - timedelta(days=7),
                              current_amount=Decimal("0"), is_active=True)
    db.add(goal)
    db.flush()
    trip.fund_goal_id = goal.id
    db.flush()
    return goal


def update_trip_fund_target(db: Session, trip: models.Trip) -> models.SavingsGoal:
    if trip.fund_goal_id is None:
        raise LifecycleError("trip has no fund")
    goal = db.get(models.SavingsGoal, trip.fund_goal_id)
    goal.target_amount = trip_cash_total(trip)
    goal.target_date = trip.start_date - timedelta(days=7)
    db.flush()
    return goal


def remove_trip_fund(db: Session, trip: models.Trip, delete_goal: bool) -> None:
    if trip.fund_goal_id is None:
        return
    goal = db.get(models.SavingsGoal, trip.fund_goal_id)
    trip.fund_goal_id = None
    db.flush()
    if delete_goal and goal is not None:
        db.delete(goal)
        db.flush()
