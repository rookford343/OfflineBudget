"""Adventures: pure trip money/points rules, wallet math, and seeding.

Spec: docs/superpowers/specs/2026-10-01-adventures-design.md. The rules here
are pure functions of ORM rows (no writes) except `ensure_adventures_seeded`.
Lifecycle writes (commit, sync, finish, fund) live in adventures_lifecycle.py.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

from sqlalchemy.orm import Session

from backend import models
from backend.models import TripCategory as C, TripPricing as P

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
