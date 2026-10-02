from datetime import date
from decimal import Decimal
from backend import models
from backend.services.adventures import (
    ensure_adventures_seeded, CHASE_UR, STARTER_AIRLINES, STARTER_HOTELS, STARTER_TEMPLATE,
    nights, days, multiplier, cash_price, cash_owed, points_used, value_cpp,
    buffer_amount, trip_cash_total, effective_ratio, source_points_needed,
    partner_points_received, bonus_active,
)


def _user(db, username="traveler"):
    u = models.User(username=username, hashed_password="x", display_name="T")
    db.add(u)
    db.flush()
    return u


def test_seeding_creates_programs_partners_and_template_once(db_session):
    user = _user(db_session)
    ensure_adventures_seeded(db_session, user.id)
    ensure_adventures_seeded(db_session, user.id)  # idempotent
    programs = db_session.query(models.LoyaltyProgram).filter_by(user_id=user.id).all()
    names = {p.name for p in programs}
    assert CHASE_UR in names
    assert set(STARTER_AIRLINES) <= names and set(STARTER_HOTELS) <= names
    assert len(programs) == 1 + len(STARTER_AIRLINES) + len(STARTER_HOTELS)
    assert all(p.balance == 0 for p in programs)
    partners = db_session.query(models.TransferPartner).filter_by(user_id=user.id).all()
    assert len(partners) == len(STARTER_AIRLINES) + len(STARTER_HOTELS)
    assert all(p.ratio == Decimal("1") and p.bonus_pct is None for p in partners)
    template = db_session.query(models.ChecklistTemplateItem).filter_by(user_id=user.id).all()
    assert len(template) == len(STARTER_TEMPLATE)


def test_seeding_is_per_kind_and_per_user(db_session):
    a, b = _user(db_session, "a"), _user(db_session, "b")
    ensure_adventures_seeded(db_session, a.id)
    # a deletes the whole template; programs remain, so re-seeding restores only the template
    db_session.query(models.ChecklistTemplateItem).filter_by(user_id=a.id).delete()
    ensure_adventures_seeded(db_session, a.id)
    assert db_session.query(models.ChecklistTemplateItem).filter_by(user_id=a.id).count() == len(STARTER_TEMPLATE)
    assert db_session.query(models.LoyaltyProgram).filter_by(user_id=a.id).count() == 1 + len(STARTER_AIRLINES) + len(STARTER_HOTELS)
    assert db_session.query(models.LoyaltyProgram).filter_by(user_id=b.id).count() == 0


TP = models.TripPricing
PAY = models.TripPayment


def _trip(**kw):
    return models.Trip(name="Trip", start_date=kw.get("start", date(2027, 3, 1)),
                       end_date=kw.get("end", date(2027, 3, 5)), travelers=kw.get("travelers", 2),
                       status=models.TripStatus.planning, items=[])


def _item(trip, name="Thing", pricing=TP.flat, unit="100.00", payment=PAY.cash, **kw):
    it = models.TripItem(name=name, category=models.TripCategory.while_there, pricing=pricing,
                         unit_cash=None if unit is None else Decimal(unit), payment=payment,
                         points_price=kw.get("points"), cash_copay=Decimal(kw.get("copay", "0")),
                         mix_cash=None if kw.get("mix") is None else Decimal(kw["mix"]),
                         is_paid=False, sort_order=0)
    trip.items.append(it)
    return it


def test_nights_days_and_multipliers():
    t = _trip()  # 4 nights, 5 days, 2 travelers
    assert (nights(t), days(t)) == (4, 5)
    expected = {TP.flat: 1, TP.per_day: 5, TP.per_night: 4, TP.per_person: 2, TP.per_person_day: 10}
    for pricing, m in expected.items():
        assert multiplier(_item(t, pricing=pricing), t) == m


def test_cash_price_and_cash_owed_per_payment_mode():
    t = _trip()
    cash = _item(t, pricing=TP.per_person, unit="300.00")
    pts = _item(t, unit="1000.00", payment=PAY.points, points=50000, copay="85.20")
    mix = _item(t, unit="400.00", payment=PAY.mix, points=10000, mix="150.00", copay="10.00")
    assert cash_price(cash, t) == Decimal("600.00") and cash_owed(cash, t) == Decimal("600.00")
    assert cash_owed(pts, t) == Decimal("85.20")
    assert cash_owed(mix, t) == Decimal("160.00")
    assert points_used(cash) == 0 and points_used(pts) == 50000 and points_used(mix) == 10000


def test_value_cpp_and_its_none_cases():
    t = _trip()
    pts = _item(t, unit="1000.00", payment=PAY.points, points=50000, copay="85.20")
    assert value_cpp(pts, t) == Decimal("1.83")          # (1000-85.20)/50000*100
    mix = _item(t, unit="400.00", payment=PAY.mix, points=10000, mix="150.00", copay="10.00")
    assert value_cpp(mix, t) == Decimal("2.40")          # (400-150-10)/10000*100
    assert value_cpp(_item(t), t) is None                 # cash item
    assert value_cpp(_item(t, unit="50.00", payment=PAY.points, points=1000, copay="60.00"), t) is None
    assert value_cpp(_item(t, unit="50.00", payment=PAY.points, points=0), t) is None


def test_auto_buffer_is_ten_percent_of_other_cash_and_user_value_wins():
    t = _trip()
    _item(t, unit="1000.00")
    _item(t, unit="234.50")
    buf = _item(t, name="Buffer", unit=None)
    assert buffer_amount(t) == Decimal("123.45")
    assert cash_owed(buf, t) == Decimal("123.45")
    assert trip_cash_total(t) == Decimal("1357.95")
    buf.unit_cash = Decimal("50.00")
    assert cash_owed(buf, t) == Decimal("50.00")


def _partner(ratio="1", bonus=None, ends=None):
    return models.TransferPartner(ratio=Decimal(ratio),
                                  bonus_pct=None if bonus is None else Decimal(bonus),
                                  bonus_ends_on=ends)


def test_effective_ratio_bonus_window_including_end_date():
    today = date(2027, 1, 10)
    assert effective_ratio(_partner(), today) == Decimal("1")
    assert effective_ratio(_partner(bonus="30", ends=date(2027, 1, 10)), today) == Decimal("1.30")
    assert effective_ratio(_partner(bonus="30", ends=date(2027, 1, 9)), today) == Decimal("1")
    assert effective_ratio(_partner(bonus="30"), today) == Decimal("1.30")   # no end date
    assert bonus_active(_partner(bonus="30", ends=date(2027, 1, 9)), today) is False


def test_transfer_rounding_ceil_for_source_floor_for_received():
    today = date(2027, 1, 10)
    p = _partner(bonus="30")
    assert source_points_needed(p, 70000, today) == 53847      # 70000/1.3 = 53846.15 -> up
    assert partner_points_received(p, 53847, today) == 70001   # 53847*1.3 = 70001.1 -> down
    assert source_points_needed(_partner(), 70000, today) == 70000
