from datetime import date, timedelta
from decimal import Decimal
import pytest
from backend import models
from backend.services.adventures import ensure_adventures_seeded, STARTER_TEMPLATE
from backend.services.adventures_lifecycle import (
    LifecycleError, create_trip_from_template, sync_trip_planned_expenses, commit_trip,
    uncommit_trip, set_item_paid, delete_item, delete_trip, finish_plan, finish_trip,
    create_trip_fund, update_trip_fund_target, remove_trip_fund,
)
from backend.services.forecast_engine import build_forecast

TODAY = date(2027, 1, 10)
PAY = models.TripPayment


def _setup(db):
    u = models.User(username="life", hashed_password="x", display_name="L")
    db.add(u); db.flush()
    acct = models.Account(user_id=u.id, name="Checking", type=models.AccountType.checking,
                          current_balance=Decimal("10000.00"))
    card = models.CreditCard(user_id=u.id, name="Card A", credit_limit=Decimal("5000.00"),
                             statement_day=28, due_day=25, current_balance=Decimal("0.00"))
    db.add_all([acct, card]); db.flush()
    ensure_adventures_seeded(db, u.id)
    trip = create_trip_from_template(db, u.id, name="Beach", destination="Coast",
                                     start_date=date(2027, 3, 1), end_date=date(2027, 3, 5),
                                     travelers=2, default_card_id=card.id)
    return u, acct, card, trip


def _by_name(trip, name):
    return next(i for i in trip.items if i.name == name)


def _pes(db, user):
    return db.query(models.PlannedExpense).filter_by(user_id=user.id).order_by(models.PlannedExpense.id).all()


def test_create_from_template_copies_every_item(db_session):
    u, _, _, trip = _setup(db_session)
    assert [i.name for i in trip.items] == [n for _, n, _ in STARTER_TEMPLATE]
    assert trip.status == models.TripStatus.planning


def test_planning_trip_creates_no_planned_expenses(db_session):
    u, _, _, trip = _setup(db_session)
    _by_name(trip, "Lodging").unit_cash = Decimal("200.00")
    sync_trip_planned_expenses(db_session, trip)
    assert _pes(db_session, u) == []


def test_commit_creates_one_offs_with_amount_date_and_card(db_session):
    u, _, card, trip = _setup(db_session)
    lodging = _by_name(trip, "Lodging"); lodging.unit_cash = Decimal("200.00")       # 4 nights = 800
    flights = _by_name(trip, "Flights"); flights.unit_cash = Decimal("500.00")       # 2 people
    flights.payment = PAY.points; flights.points_price = 60000; flights.cash_copay = Decimal("11.20")
    flights.charge_date = date(2027, 1, 20)
    commit_trip(db_session, trip)
    pes = {pe.name: pe for pe in _pes(db_session, u)}
    # Buffer is 10% of other cash owed: (800 + 11.20) * 0.10 = 81.12
    assert set(pes) == {"Beach: Lodging", "Beach: Flights", "Beach: Buffer"}
    assert pes["Beach: Lodging"].amount == Decimal("800.00")
    assert pes["Beach: Lodging"].expected_date == date(2027, 3, 1)
    assert pes["Beach: Flights"].amount == Decimal("11.20")
    assert pes["Beach: Flights"].expected_date == date(2027, 1, 20)
    assert all(pe.card_id == card.id and pe.direction == models.PlannedDirection.outflow for pe in pes.values())
    assert pes["Beach: Buffer"].amount == Decimal("81.12")
    assert trip.status == models.TripStatus.committed


def test_sync_after_edit_is_idempotent_and_removes_zeroed_items(db_session):
    u, _, _, trip = _setup(db_session)
    lodging = _by_name(trip, "Lodging"); lodging.unit_cash = Decimal("200.00")
    commit_trip(db_session, trip)
    lodging.unit_cash = Decimal("250.00")
    sync_trip_planned_expenses(db_session, trip)
    sync_trip_planned_expenses(db_session, trip)
    pes = {pe.name: pe for pe in _pes(db_session, u)}
    assert pes["Beach: Lodging"].amount == Decimal("1000.00") and len(pes) == 2   # + Buffer
    lodging.unit_cash = None
    sync_trip_planned_expenses(db_session, trip)
    assert _pes(db_session, u) == [] and lodging.planned_expense_id is None


def test_sync_leaves_a_settled_planned_expense_untouched(db_session):
    """Settling from the Planned page can happen while item.is_paid is still
    False -- sync must not rewrite or delete that row."""
    u, _, card, trip = _setup(db_session)
    lodging = _by_name(trip, "Lodging"); lodging.unit_cash = Decimal("200.00")
    commit_trip(db_session, trip)
    pe = db_session.get(models.PlannedExpense, lodging.planned_expense_id)
    pe.settled_on = TODAY
    pe.actual_amount = Decimal("800.00")
    db_session.flush()
    orig_amount, orig_date, orig_card = pe.amount, pe.expected_date, pe.card_id

    lodging.unit_cash = Decimal("500.00")   # would bump the amount if sync touched it
    sync_trip_planned_expenses(db_session, trip)

    assert pe.amount == orig_amount
    assert pe.expected_date == orig_date
    assert pe.card_id == orig_card
    assert pe.settled_on == TODAY and pe.actual_amount == Decimal("800.00")
    assert lodging.planned_expense_id == pe.id


def test_mark_paid_settles_and_forecast_drops_it(db_session):
    u, acct, _, trip = _setup(db_session)
    trip.default_card_id = None   # straight to checking so the forecast effect is direct
    lodging = _by_name(trip, "Lodging"); lodging.unit_cash = Decimal("200.00")
    _by_name(trip, "Buffer").unit_cash = Decimal("0")
    commit_trip(db_session, trip)
    db_session.commit()

    def lodging_lines():
        days = build_forecast(db_session, u.id, acct.id, date(2027, 2, 25), date(2027, 3, 5))
        return [t for d in days for t in d.transactions if "Lodging" in t.name]

    assert len(lodging_lines()) == 1
    set_item_paid(db_session, trip, lodging, True, TODAY)
    set_item_paid(db_session, trip, lodging, True, TODAY)   # no-op
    db_session.commit()
    pe = db_session.get(models.PlannedExpense, lodging.planned_expense_id)
    assert pe.settled_on == TODAY and pe.actual_amount == Decimal("800.00")
    assert lodging_lines() == []
    set_item_paid(db_session, trip, lodging, False, TODAY)
    assert pe.settled_on is None and pe.actual_amount is None


def test_uncommit_removes_unsettled_only(db_session):
    u, _, _, trip = _setup(db_session)
    lodging = _by_name(trip, "Lodging"); lodging.unit_cash = Decimal("200.00")
    food = _by_name(trip, "Food"); food.unit_cash = Decimal("10.00")
    commit_trip(db_session, trip)
    set_item_paid(db_session, trip, lodging, True, TODAY)
    uncommit_trip(db_session, trip)
    pes = _pes(db_session, u)
    assert [pe.name for pe in pes] == ["Beach: Lodging"] and pes[0].settled_on == TODAY
    assert food.planned_expense_id is None and lodging.planned_expense_id is None
    assert trip.status == models.TripStatus.planning


def test_delete_item_and_trip_clean_up_one_offs(db_session):
    u, _, _, trip = _setup(db_session)
    lodging = _by_name(trip, "Lodging"); lodging.unit_cash = Decimal("200.00")
    commit_trip(db_session, trip)
    delete_item(db_session, trip, lodging)
    assert [pe.name for pe in _pes(db_session, u)] == []   # buffer fell to 0 too
    _by_name(trip, "Food").unit_cash = Decimal("10.00")
    sync_trip_planned_expenses(db_session, trip)
    delete_trip(db_session, trip)
    db_session.flush()
    assert _pes(db_session, u) == [] and db_session.query(models.Trip).count() == 0


def test_status_guards(db_session):
    u, _, _, trip = _setup(db_session)
    with pytest.raises(LifecycleError):
        uncommit_trip(db_session, trip)
    with pytest.raises(LifecycleError):
        finish_trip(db_session, trip, None, False, TODAY)
    commit_trip(db_session, trip)
    with pytest.raises(LifecycleError):
        commit_trip(db_session, trip)


def _program(db, user, name):
    return db.query(models.LoyaltyProgram).filter_by(user_id=user.id, name=name).one()


def test_finish_deducts_points_with_transfer_and_refuses_negative(db_session):
    u, _, _, trip = _setup(db_session)
    chase = _program(db_session, u, "Chase Ultimate Rewards"); chase.balance = 60000
    virgin = _program(db_session, u, "Virgin Atlantic Flying Club"); virgin.balance = 1000
    partner = db_session.query(models.TransferPartner).filter_by(
        user_id=u.id, from_program_id=chase.id, to_program_id=virgin.id).one()
    partner.bonus_pct = Decimal("30")
    flights = _by_name(trip, "Flights"); flights.unit_cash = Decimal("900.00")
    flights.payment = PAY.points; flights.points_program_id = virgin.id; flights.points_price = 70000
    flights.transfer_from_program_id = chase.id; flights.transfer_points = 53847
    commit_trip(db_session, trip)
    assert finish_plan(db_session, trip, TODAY) == {chase.id: -53847, virgin.id: 70001 - 70000}
    finish_trip(db_session, trip, None, False, TODAY)
    assert (chase.balance, virgin.balance) == (60000 - 53847, 1000 + 1)
    assert trip.status == models.TripStatus.done and chase.balance_updated_at is not None


def test_finish_refuses_negative_unless_forced(db_session):
    u, _, _, trip = _setup(db_session)
    hyatt = _program(db_session, u, "World of Hyatt"); hyatt.balance = 1000
    lodging = _by_name(trip, "Lodging"); lodging.unit_cash = Decimal("200.00")
    lodging.payment = PAY.points; lodging.points_program_id = hyatt.id; lodging.points_price = 5000
    commit_trip(db_session, trip)
    with pytest.raises(LifecycleError):
        finish_trip(db_session, trip, None, False, TODAY)
    assert hyatt.balance == 1000 and trip.status == models.TripStatus.committed
    finish_trip(db_session, trip, {hyatt.id: 900}, False, TODAY)   # confirmed lower usage
    assert hyatt.balance == 100


def test_trip_fund_create_update_remove(db_session):
    u, _, _, trip = _setup(db_session)
    _by_name(trip, "Lodging").unit_cash = Decimal("200.00")
    goal = create_trip_fund(db_session, trip)
    assert goal.name == "Beach fund" and goal.target_amount == Decimal("880.00")   # 800 + 10% buffer
    assert goal.target_date == date(2027, 3, 1) - timedelta(days=7)
    with pytest.raises(LifecycleError):
        create_trip_fund(db_session, trip)
    _by_name(trip, "Lodging").unit_cash = Decimal("300.00")
    assert goal.target_amount == Decimal("880.00")            # never silently changes
    assert update_trip_fund_target(db_session, trip).target_amount == Decimal("1320.00")
    remove_trip_fund(db_session, trip, delete_goal=True)
    db_session.flush()
    assert trip.fund_goal_id is None and db_session.query(models.SavingsGoal).count() == 0
