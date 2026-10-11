"""Adventures: pure trip money/points rules, wallet math, and seeding.

Spec: docs/superpowers/specs/2026-10-01-adventures-design.md. The rules here
are pure functions of ORM rows (no writes) except `ensure_adventures_seeded`.
Lifecycle writes (commit, sync, finish, fund) live in adventures_lifecycle.py.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

from sqlalchemy.orm import Session

from backend import models
from backend.models import TripCategory as C, TripPricing as P

# Rules: Pure functions for cash/points calculations

CENT = Decimal("0.01")


def _q(v: Decimal) -> Decimal:
    return v.quantize(CENT, rounding=ROUND_HALF_UP)


def nights(trip: models.Trip) -> int:
    return max((trip.end_date - trip.start_date).days, 0)


def days(trip: models.Trip) -> int:
    return nights(trip) + 1


def multiplier(item: models.TripItem, trip: models.Trip) -> int:
    p = item.pricing
    if p == models.TripPricing.per_day:
        return days(trip)
    if p == models.TripPricing.per_night:
        return nights(trip)
    if p == models.TripPricing.per_person:
        return trip.travelers
    if p == models.TripPricing.per_person_day:
        return trip.travelers * days(trip)
    return 1


def is_auto_buffer(item: models.TripItem) -> bool:
    return (item.name.strip().lower() == "buffer"
            and item.pricing == models.TripPricing.flat and item.unit_cash is None)


def points_used(item: models.TripItem) -> int:
    if item.payment in (models.TripPayment.points, models.TripPayment.mix):
        return int(item.points_price or 0)
    return 0


def _raw_cash_price(item: models.TripItem, trip: models.Trip) -> Decimal:
    return _q(Decimal(item.unit_cash or 0) * multiplier(item, trip))


def _owed_from_price(item: models.TripItem, price: Decimal) -> Decimal:
    copay = Decimal(item.cash_copay or 0)
    if item.payment == models.TripPayment.points:
        return _q(copay)
    if item.payment == models.TripPayment.mix:
        return _q(Decimal(item.mix_cash or 0) + copay)
    return price


def buffer_amount(trip: models.Trip) -> Decimal:
    """10% of the cash owed on every non-auto-buffer item (spec Rules)."""
    others = sum((_owed_from_price(i, _raw_cash_price(i, trip))
                  for i in trip.items if not is_auto_buffer(i)), Decimal("0"))
    return _q(others * Decimal("0.10"))


def cash_price(item: models.TripItem, trip: models.Trip) -> Decimal:
    if is_auto_buffer(item):
        return buffer_amount(trip)
    return _raw_cash_price(item, trip)


def cash_owed(item: models.TripItem, trip: models.Trip) -> Decimal:
    return _owed_from_price(item, cash_price(item, trip))


def trip_cash_total(trip: models.Trip) -> Decimal:
    return sum((cash_owed(i, trip) for i in trip.items), Decimal("0"))


def value_cpp(item: models.TripItem, trip: models.Trip) -> Decimal | None:
    pts = points_used(item)
    if pts <= 0:
        return None
    numerator = cash_price(item, trip) - Decimal(item.cash_copay or 0)
    if item.payment == models.TripPayment.mix:
        numerator -= Decimal(item.mix_cash or 0)
    if numerator <= 0:
        return None
    return _q(numerator / Decimal(pts) * 100)


def bonus_active(partner: models.TransferPartner, today: date) -> bool:
    return partner.bonus_pct is not None and (
        partner.bonus_ends_on is None or today <= partner.bonus_ends_on)


def effective_ratio(partner: models.TransferPartner, today: date) -> Decimal:
    ratio = Decimal(partner.ratio)
    if bonus_active(partner, today):
        ratio = ratio * (1 + Decimal(partner.bonus_pct) / 100)
    return ratio


def source_points_needed(partner: models.TransferPartner, target_points: int, today: date) -> int:
    """Rounded UP so a transfer is never short (Global Constraints)."""
    return int((Decimal(target_points) / effective_ratio(partner, today)).to_integral_value(rounding=ROUND_CEILING))


def partner_points_received(partner: models.TransferPartner, source_points: int, today: date) -> int:
    """Rounded DOWN -- programs credit whole points only."""
    return int((Decimal(source_points) * effective_ratio(partner, today)).to_integral_value(rounding=ROUND_FLOOR))


CHASE_UR = "Chase Ultimate Rewards"
STARTER_AIRLINES = [
    "Aer Lingus AerClub", "Air Canada Aeroplan", "Air France/KLM Flying Blue",
    "British Airways Executive Club", "Emirates Skywards", "Iberia Plus",
    "JetBlue TrueBlue", "Singapore KrisFlyer", "Southwest Rapid Rewards",
    "United MileagePlus", "Virgin Atlantic Flying Club",
]
STARTER_HOTELS = ["World of Hyatt", "Marriott Bonvoy", "IHG One Rewards"]

STARTER_TEMPLATE: list[tuple[C, str, P]] = [
    (C.getting_there, "Flights", P.per_person),
    (C.getting_there, "Airport parking or rides", P.flat),
    (C.getting_there, "Checked bags", P.per_person),
    (C.getting_there, "Rental car or trains", P.flat),
    (C.getting_there, "Gas & tolls", P.flat),
    (C.staying, "Lodging", P.per_night),
    (C.staying, "Resort / city taxes", P.per_night),
    (C.daily, "Food", P.per_person_day),
    (C.daily, "Local transport", P.per_day),
    (C.daily, "Tips", P.per_day),
    (C.before, "Passports / visas", P.per_person),
    (C.before, "Travel insurance", P.flat),
    (C.before, "International phone plan", P.flat),
    (C.before, "Dog boarding", P.per_night),
    (C.before, "Kid gear rental", P.flat),
    (C.while_there, "Activities & tickets", P.flat),
    (C.while_there, "Souvenirs", P.flat),
    (C.while_there, "Buffer", P.flat),
]


def ensure_adventures_seeded(db: Session, user_id: int) -> None:
    """Seed starter programs+partners and the checklist template, each only
    when the user has zero rows of that kind -- idempotent with no flag column
    (spec: `users` is not altered)."""
    has_programs = db.query(models.LoyaltyProgram.id).filter(
        models.LoyaltyProgram.user_id == user_id).first() is not None
    if not has_programs:
        chase = models.LoyaltyProgram(user_id=user_id, name=CHASE_UR,
                                      kind=models.LoyaltyKind.bank, balance=0, sort_order=0)
        db.add(chase)
        db.flush()
        order = 1
        for kind, names in ((models.LoyaltyKind.airline, STARTER_AIRLINES),
                            (models.LoyaltyKind.hotel, STARTER_HOTELS)):
            for name in names:
                p = models.LoyaltyProgram(user_id=user_id, name=name, kind=kind,
                                          balance=0, sort_order=order)
                db.add(p)
                db.flush()
                db.add(models.TransferPartner(user_id=user_id, from_program_id=chase.id,
                                              to_program_id=p.id, ratio=Decimal("1")))
                order += 1
    has_template = db.query(models.ChecklistTemplateItem.id).filter(
        models.ChecklistTemplateItem.user_id == user_id).first() is not None
    if not has_template:
        for i, (category, name, pricing) in enumerate(STARTER_TEMPLATE):
            db.add(models.ChecklistTemplateItem(user_id=user_id, category=category, name=name,
                                                pricing=pricing, unit_cash=None, sort_order=i))
    db.flush()


# ── Wallet math ──────────────────────────────────────────────────────────────

_OPEN = (models.TripStatus.planning, models.TripStatus.committed)


def reserved_by_program(db: Session, user_id: int, exclude_trip_id: int | None = None,
                        today: date | None = None) -> dict[int, int]:
    """Points spoken for by open (planning/committed) trips: each item's own
    points, plus source points of any attached transfer -- net of the partner
    points that transfer credits to the item's own program. Reserved can go
    negative for a program that's a net receiver, which means a net credit."""
    if today is None:
        today = date.today()
    q = db.query(models.Trip).filter(models.Trip.user_id == user_id, models.Trip.status.in_(_OPEN))
    if exclude_trip_id is not None:
        q = q.filter(models.Trip.id != exclude_trip_id)
    out: dict[int, int] = {}
    for trip in q.all():
        for it in trip.items:
            used = points_used(it)
            if used and it.points_program_id:
                out[it.points_program_id] = out.get(it.points_program_id, 0) + used
            if it.transfer_from_program_id and it.transfer_points:
                out[it.transfer_from_program_id] = out.get(it.transfer_from_program_id, 0) + int(it.transfer_points)
                if used and it.points_program_id:
                    partner = _partner_for(db, user_id, it.transfer_from_program_id, it.points_program_id)
                    if partner:
                        got = partner_points_received(partner, int(it.transfer_points), today)
                        out[it.points_program_id] = out.get(it.points_program_id, 0) - got
    return out


def wallet(db: Session, user_id: int, today: date) -> list[dict]:
    reserved = reserved_by_program(db, user_id, today=today)
    rows = []
    for p in db.query(models.LoyaltyProgram).filter(
            models.LoyaltyProgram.user_id == user_id).order_by(
            models.LoyaltyProgram.sort_order, models.LoyaltyProgram.id).all():
        r = reserved.get(p.id, 0)
        rows.append({
            "id": p.id, "name": p.name, "kind": p.kind.value, "balance": p.balance,
            "reserved": r, "available": p.balance - r,
            "balance_updated_at": p.balance_updated_at,
            "age_days": (today - p.balance_updated_at.date()).days if p.balance_updated_at else None,
            "is_active": p.is_active, "sort_order": p.sort_order,
        })
    return rows


def _partner_for(db: Session, user_id: int, from_id: int, to_id: int) -> models.TransferPartner | None:
    return db.query(models.TransferPartner).filter(
        models.TransferPartner.user_id == user_id,
        models.TransferPartner.from_program_id == from_id,
        models.TransferPartner.to_program_id == to_id).first()


def trip_points_summary(db: Session, trip: models.Trip, today: date) -> dict[int, dict]:
    """Per program this trip touches: points needed (items' own points plus
    transfer source points), what's available after OTHER open trips,
    partner points arriving from attached transfers, and the shortfall."""
    others = reserved_by_program(db, trip.user_id, exclude_trip_id=trip.id, today=today)
    needed: dict[int, int] = {}
    incoming: dict[int, int] = {}
    for it in trip.items:
        used = points_used(it)
        if used and it.points_program_id:
            needed[it.points_program_id] = needed.get(it.points_program_id, 0) + used
        if it.transfer_from_program_id and it.transfer_points:
            src = it.transfer_from_program_id
            needed[src] = needed.get(src, 0) + int(it.transfer_points)
            if used and it.points_program_id:
                partner = _partner_for(db, trip.user_id, src, it.points_program_id)
                if partner:
                    got = partner_points_received(partner, int(it.transfer_points), today)
                    incoming[it.points_program_id] = incoming.get(it.points_program_id, 0) + got
    out: dict[int, dict] = {}
    for pid in needed:
        prog = db.get(models.LoyaltyProgram, pid)
        if prog is None or prog.user_id != trip.user_id:
            continue
        avail = prog.balance - others.get(pid, 0)
        inc = incoming.get(pid, 0)
        out[pid] = {"program_id": pid, "name": prog.name, "needed": needed[pid],
                    "available": avail, "incoming": inc,
                    "shortfall": max(needed[pid] - avail - inc, 0)}
    return out


def suggest_transfer(db: Session, item: models.TripItem, trip: models.Trip, today: date) -> dict | None:
    if points_used(item) <= 0 or not item.points_program_id or item.transfer_from_program_id:
        return None
    summary = trip_points_summary(db, trip, today)
    short = summary.get(item.points_program_id, {}).get("shortfall", 0)
    if short <= 0:
        return None
    best = None
    all_reserved = reserved_by_program(db, trip.user_id, today=today)
    for partner in db.query(models.TransferPartner).filter(
            models.TransferPartner.user_id == trip.user_id,
            models.TransferPartner.to_program_id == item.points_program_id).all():
        src = partner.from_program
        if src is None or not src.is_active:
            continue
        need = source_points_needed(partner, short, today)
        # If src.id is in summary, use that (it has both needed and available computed).
        # Else use balance - all_reserved, which gives the same answer: a source absent
        # from needed has no reservation in this trip.
        src_left = summary[src.id]["available"] - summary[src.id]["needed"] if src.id in summary \
            else src.balance - all_reserved.get(src.id, 0)
        if src_left < need:
            continue
        if best is None or need < best["source_points"]:
            best = {"from_program_id": src.id, "from_program_name": src.name,
                    "source_points": need,
                    "partner_points": partner_points_received(partner, need, today),
                    "bonus_pct": Decimal(partner.bonus_pct).quantize(CENT) if bonus_active(partner, today) else None}
    return best
