from datetime import date, datetime
from decimal import Decimal
from backend import models
from backend.services.adventures import (
    reserved_by_program, wallet, trip_points_summary, suggest_transfer, partner_points_received,
)

TODAY = date(2027, 1, 10)
PAY = models.TripPayment


def _user(db, name="w"):
    u = models.User(username=name, hashed_password="x", display_name=name)
    db.add(u); db.flush(); return u


def _prog(db, user, name, balance, kind=models.LoyaltyKind.airline):
    p = models.LoyaltyProgram(user_id=user.id, name=name, kind=kind, balance=balance)
    db.add(p); db.flush(); return p


def _trip(db, user, status=models.TripStatus.planning, name="Trip"):
    t = models.Trip(user_id=user.id, name=name, start_date=date(2027, 3, 1),
                    end_date=date(2027, 3, 5), travelers=1, status=status)
    db.add(t); db.flush(); return t


def _pts_item(db, trip, program, points, **kw):
    it = models.TripItem(trip_id=trip.id, user_id=trip.user_id, name=kw.get("name", "Flight"),
                         category=models.TripCategory.getting_there, unit_cash=Decimal("1000"),
                         payment=PAY.points, points_program_id=program.id, points_price=points,
                         transfer_from_program_id=kw.get("transfer_from"),
                         transfer_points=kw.get("transfer_points"))
    db.add(it); db.flush(); db.refresh(trip); return it


def test_reserved_counts_planning_and_committed_but_not_done(db_session):
    u = _user(db_session)
    air = _prog(db_session, u, "Air", 100000)
    _pts_item(db_session, _trip(db_session, u), air, 30000)
    _pts_item(db_session, _trip(db_session, u, models.TripStatus.committed), air, 20000)
    _pts_item(db_session, _trip(db_session, u, models.TripStatus.done), air, 50000)
    assert reserved_by_program(db_session, u.id) == {air.id: 50000}
    row = next(r for r in wallet(db_session, u.id, TODAY) if r["id"] == air.id)
    assert (row["balance"], row["reserved"], row["available"]) == (100000, 50000, 50000)


def test_transfer_points_reserve_the_source_program(db_session):
    u = _user(db_session)
    bank = _prog(db_session, u, "Bank", 80000, models.LoyaltyKind.bank)
    air = _prog(db_session, u, "Air", 0)
    partner = models.TransferPartner(user_id=u.id, from_program_id=bank.id,
                                     to_program_id=air.id, ratio=Decimal("1"))
    db_session.add(partner); db_session.flush()
    _pts_item(db_session, _trip(db_session, u), air, 70000,
              transfer_from=bank.id, transfer_points=53847)
    credited = partner_points_received(partner, 53847, TODAY)   # ratio 1 -> 53847
    assert reserved_by_program(db_session, u.id, today=TODAY) == {
        air.id: 70000 - credited, bank.id: 53847,
    }


def test_second_trip_shortfall_not_inflated_by_first_trips_credited_transfer(db_session):
    """Chase 100k, Virgin 0; trip1 needs 70k Virgin with a 70k Chase transfer
    attached (the spec's example). Before crediting the partner side back,
    trip1 left Virgin showing -70000 available, so a second trip's Virgin
    shortfall -- and suggest_transfer's suggestion -- were inflated by that
    phantom deficit instead of reflecting trip2's own, much smaller need."""
    u = _user(db_session)
    chase = _prog(db_session, u, "Chase", 100000, models.LoyaltyKind.bank)
    virgin = _prog(db_session, u, "Virgin", 0)
    db_session.add(models.TransferPartner(user_id=u.id, from_program_id=chase.id,
                                          to_program_id=virgin.id, ratio=Decimal("1")))
    db_session.flush()
    trip1 = _trip(db_session, u, name="Trip1")
    _pts_item(db_session, trip1, virgin, 70000, transfer_from=chase.id, transfer_points=70000)

    trip2 = _trip(db_session, u, name="Trip2")
    item2 = _pts_item(db_session, trip2, virgin, 20000)

    summary = trip_points_summary(db_session, trip2, TODAY)[virgin.id]
    assert summary["needed"] == 20000
    assert summary["shortfall"] == 20000   # exactly trip2's own need

    suggestion = suggest_transfer(db_session, item2, trip2, TODAY)
    assert suggestion == {"from_program_id": chase.id, "from_program_name": "Chase",
                          "source_points": 20000, "partner_points": 20000, "bonus_pct": None}


def test_wallet_age_days(db_session):
    u = _user(db_session)
    p = _prog(db_session, u, "Air", 10)
    p.balance_updated_at = datetime(2026, 12, 1, 9, 0)
    row = wallet(db_session, u.id, TODAY)[0]
    assert row["age_days"] == 40


def test_shortfall_is_net_of_other_trips_and_attached_transfers(db_session):
    u = _user(db_session)
    bank = _prog(db_session, u, "Bank", 100000, models.LoyaltyKind.bank)
    air = _prog(db_session, u, "Air", 20000)
    db_session.add(models.TransferPartner(user_id=u.id, from_program_id=bank.id,
                                          to_program_id=air.id, ratio=Decimal("1")))
    other = _trip(db_session, u, name="Other")
    _pts_item(db_session, other, air, 5000)              # reserves 5k Air elsewhere
    trip = _trip(db_session, u)
    _pts_item(db_session, trip, air, 70000)
    s = trip_points_summary(db_session, trip, TODAY)[air.id]
    assert (s["needed"], s["available"], s["incoming"], s["shortfall"]) == (70000, 15000, 0, 55000)
    second = _pts_item(db_session, trip, air, 0, name="Attach",
                       transfer_from=bank.id, transfer_points=55000)
    second.payment = PAY.cash
    db_session.flush(); db_session.refresh(trip)
    s = trip_points_summary(db_session, trip, TODAY)
    assert s[air.id]["incoming"] == 0   # transfer only counts toward the item's own program


def test_suggest_transfer_picks_fewest_source_points_that_can_cover(db_session):
    u = _user(db_session)
    small = _prog(db_session, u, "SmallBank", 10000, models.LoyaltyKind.bank)
    big = _prog(db_session, u, "BigBank", 200000, models.LoyaltyKind.bank)
    rich = _prog(db_session, u, "RichBank", 200000, models.LoyaltyKind.bank)
    air = _prog(db_session, u, "Air", 0)
    for src, ratio, bonus in ((small, "2", None), (big, "1", "30"), (rich, "1", None)):
        db_session.add(models.TransferPartner(user_id=u.id, from_program_id=src.id, to_program_id=air.id,
                                              ratio=Decimal(ratio),
                                              bonus_pct=None if bonus is None else Decimal(bonus)))
    trip = _trip(db_session, u)
    item = _pts_item(db_session, trip, air, 70000)
    s = suggest_transfer(db_session, item, trip, TODAY)
    # small (ratio 2 -> 35000 needed) can't cover with 10000; big with +30% needs 53847
    assert s == {"from_program_id": big.id, "from_program_name": "BigBank",
                 "source_points": 53847, "partner_points": 70001, "bonus_pct": Decimal("30.00")}


def test_no_suggestion_when_covered_or_already_attached(db_session):
    u = _user(db_session)
    air = _prog(db_session, u, "Air", 100000)
    trip = _trip(db_session, u)
    assert suggest_transfer(db_session, _pts_item(db_session, trip, air, 1000), trip, TODAY) is None


def test_wallet_is_user_scoped(db_session):
    a, b = _user(db_session, "a"), _user(db_session, "b")
    _prog(db_session, b, "Theirs", 5)
    assert wallet(db_session, a.id, TODAY) == []


def test_suggest_transfer_with_overlap_program_direct_and_source(db_session):
    """Program X is both used directly (item1) and as a transfer source (item2)."""
    u = _user(db_session)
    x = _prog(db_session, u, "X", 100000, models.LoyaltyKind.bank)
    air = _prog(db_session, u, "Air", 0)
    db_session.add(models.TransferPartner(user_id=u.id, from_program_id=x.id,
                                          to_program_id=air.id, ratio=Decimal("1")))
    trip = _trip(db_session, u)
    # item1: uses X directly for 60000 points (reserves 60000 of X)
    _pts_item(db_session, trip, x, 60000)
    # item2: needs 70000 Air points, only source is X; X has 100000 - 60000 = 40000 left
    item2 = _pts_item(db_session, trip, air, 70000)
    # Not enough X available for the 70000 needed
    assert suggest_transfer(db_session, item2, trip, TODAY) is None
    # Raise X balance to 140000, now 140000 - 60000 = 80000 available, enough for 70000
    x.balance = 140000
    db_session.flush()
    s = suggest_transfer(db_session, item2, trip, TODAY)
    assert s == {"from_program_id": x.id, "from_program_name": "X",
                 "source_points": 70000, "partner_points": 70000, "bonus_pct": None}


def test_suggest_transfer_else_branch_source_reserved_by_other_trip(db_session):
    """Source program X is not used in this trip but is reserved by another open trip."""
    u = _user(db_session)
    x = _prog(db_session, u, "X", 100000, models.LoyaltyKind.bank)
    air = _prog(db_session, u, "Air", 0)
    db_session.add(models.TransferPartner(user_id=u.id, from_program_id=x.id,
                                          to_program_id=air.id, ratio=Decimal("1")))
    # Other trip (planning): uses X directly for 50000 (reserves 50000 of X)
    other = _trip(db_session, u, name="Other")
    _pts_item(db_session, other, x, 50000)
    # This trip (planning): needs 70000 Air, doesn't use X
    trip = _trip(db_session, u, name="This")
    item = _pts_item(db_session, trip, air, 70000)
    # X has 50000 reserved by Other, leaving 50000 available; not enough for 70000 shortfall
    assert suggest_transfer(db_session, item, trip, TODAY) is None
    # Mark Other as done; X is no longer reserved
    other.status = models.TripStatus.done
    db_session.flush()
    s = suggest_transfer(db_session, item, trip, TODAY)
    assert s == {"from_program_id": x.id, "from_program_name": "X",
                 "source_points": 70000, "partner_points": 70000, "bonus_pct": None}
