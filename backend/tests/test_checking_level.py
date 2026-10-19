""""Keep checking at the right level": top-up rules plus the optional sweep.

The sweep runs only under savings_strategy == "save_monthly" with a ceiling
and destination set, evaluated on the rule's check_day. Made-up figures.
"""
from datetime import date
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import models
from backend.dependencies import get_current_user, get_db
from backend.routers import forecast as forecast_router
from backend.services.forecast_engine import (
    _compute_transfer_schedule,
    _compute_transfer_schedules,
    build_forecast,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _seed(db, username="cl", strategy="save_monthly", checking_balance="6500.00"):
    user = models.User(username=username, hashed_password="x", display_name="C", savings_strategy=strategy)
    db.add(user)
    db.flush()
    savings = models.Account(user_id=user.id, name="Savings", type=models.AccountType.savings,
                             current_balance=Decimal("10000.00"))
    checking = models.Account(user_id=user.id, name="Main Checking", type=models.AccountType.checking,
                              current_balance=Decimal(checking_balance))
    brokerage = models.Account(user_id=user.id, name="Brokerage", type=models.AccountType.money_market,
                               current_balance=Decimal("20000.00"))
    db.add_all([savings, checking, brokerage])
    db.flush()
    return user, savings, checking, brokerage


def _monthly(db, user, account, name, amount, day, kind):
    db.add(models.RecurringItem(
        user_id=user.id, account_id=account.id, name=name, amount=Decimal(amount),
        type=kind, frequency=models.RecurringFrequency.monthly,
        day_of_month=day, start_date=date(2026, 1, 1),
    ))


def _bill_and_paycheck(db, user, checking):
    # A stationary month: -$1,000 on the 15th, +$1,000 on the 20th. With
    # $6,500 open, every month's raw low is $5,500 (the 15th-19th).
    _monthly(db, user, checking, "Bill", "1000.00", 15, models.RecurringType.expense)
    _monthly(db, user, checking, "Paycheck", "1000.00", 20, models.RecurringType.income)


def _rule(db, user, savings, checking, sweep_ceiling=None, sweep_to=None, check_day=1):
    rule = models.BufferTransferRule(
        user_id=user.id, from_account_id=savings.id, to_account_id=checking.id,
        action_threshold=Decimal("500"), target_floor=Decimal("1000"),
        increment=Decimal("1000"), check_day=check_day,
        sweep_ceiling=Decimal(sweep_ceiling) if sweep_ceiling is not None else None,
        sweep_to_account_id=sweep_to.id if sweep_to is not None else None,
    )
    db.add(rule)
    db.flush()
    return rule


# ── schedule ──────────────────────────────────────────────────────────────────

def test_topup_schedule_unchanged_when_no_sweep_is_set(db_session):
    user, savings, checking, _ = _seed(db_session, checking_balance="500.00")
    _monthly(db_session, user, checking, "Big Bill", "3000.00", 15, models.RecurringType.expense)
    _monthly(db_session, user, checking, "Paycheck", "2000.00", 20, models.RecurringType.income)
    rule = _rule(db_session, user, savings, checking)
    db_session.commit()

    topups, sweeps = _compute_transfer_schedules(db_session, user.id, rule, date(2026, 1, 1), date(2026, 4, 30))

    assert sweeps == {}
    assert topups == _compute_transfer_schedule(db_session, user.id, rule, date(2026, 1, 1), date(2026, 4, 30))
    # Captured from the engine BEFORE the sweep change. Jan: 500 - 3,000 =
    # -2,500 low -> 3,500 short of the 1,000 floor -> 4,000. Feb's low with
    # that credit is exactly 500 (not below the threshold). Mar: -500 -> 2,000.
    assert topups == {date(2026, 1, 1): Decimal("4000"), date(2026, 3, 1): Decimal("2000")}


def test_sweep_moves_whole_increments_of_the_excess_under_save_monthly(db_session):
    user, savings, checking, _ = _seed(db_session)
    _bill_and_paycheck(db_session, user, checking)
    rule = _rule(db_session, user, savings, checking, sweep_ceiling="2000", sweep_to=savings)
    db_session.commit()

    topups, sweeps = _compute_transfer_schedules(db_session, user.id, rule, date(2026, 1, 1), date(2026, 3, 31))

    assert topups == {}
    # Jan: low 5,500 - ceiling 2,000 = 3,500 excess -> floor to 3,000.
    # Feb: low 5,500 - 3,000 already swept = 2,500 -> 500 excess, under one
    # increment, so nothing moves. Same for March.
    assert sweeps == {date(2026, 1, 1): Decimal("3000")}


def test_no_sweep_under_pull_from_savings(db_session):
    """The strategy gate: identical rule and balances as above, but the
    user isn't saving monthly, so the sweep never runs."""
    user, savings, checking, _ = _seed(db_session, strategy="pull_from_savings")
    _bill_and_paycheck(db_session, user, checking)
    rule = _rule(db_session, user, savings, checking, sweep_ceiling="2000", sweep_to=savings)
    db_session.commit()

    topups, sweeps = _compute_transfer_schedules(db_session, user.id, rule, date(2026, 1, 1), date(2026, 3, 31))

    assert sweeps == {}
    assert topups == {}
    entries = build_forecast(db_session, user.id, checking.id, date(2026, 1, 1), date(2026, 3, 31))
    assert not any(t.name.startswith("Sweep") for e in entries for t in e.transactions)


def test_no_sweep_when_ceiling_or_destination_missing(db_session):
    user, savings, checking, _ = _seed(db_session)
    _bill_and_paycheck(db_session, user, checking)
    rule = _rule(db_session, user, savings, checking, sweep_ceiling="2000", sweep_to=None)
    db_session.commit()

    _, sweeps = _compute_transfer_schedules(db_session, user.id, rule, date(2026, 1, 1), date(2026, 3, 31))
    assert sweeps == {}


def test_sweep_never_takes_checking_below_the_ceiling_within_the_window(db_session):
    """Check day the 5th, low point late in the month (rent on the 25th,
    paycheck on the 28th, net zero per month): the sweep sized on the 5th
    must still leave the 25th at or above the ceiling. Sizing it on the
    check-day balance instead (9,000 - 2,000 = 7,000) would put the 25th at
    -1,000."""
    user, savings, checking, _ = _seed(db_session, checking_balance="9000.00")
    _monthly(db_session, user, checking, "Rent", "3000.00", 25, models.RecurringType.expense)
    _monthly(db_session, user, checking, "Paycheck", "3000.00", 28, models.RecurringType.income)
    _rule(db_session, user, savings, checking, sweep_ceiling="2000", sweep_to=savings, check_day=5)
    db_session.commit()

    entries = build_forecast(db_session, user.id, checking.id, date(2026, 1, 1), date(2026, 6, 30))

    swept = [(e.date, t.amount) for e in entries for t in e.transactions if t.name.startswith("Sweep to")]
    assert swept == [(date(2026, 1, 5), Decimal("-4000"))]
    in_windows = [e for e in entries if e.date >= date(2026, 1, 5)]
    assert min(e.projected_balance for e in in_windows) == Decimal("2000.00")


def test_sweep_is_the_same_whatever_window_end_the_caller_asks_for(db_session):
    """A caller whose window ends before the month's low point (e.g. a short
    risk query) must not see a bigger sweep than a full-year caller does."""
    user, savings, checking, _ = _seed(db_session)
    _bill_and_paycheck(db_session, user, checking)
    rule = _rule(db_session, user, savings, checking, sweep_ceiling="2000", sweep_to=savings)
    db_session.commit()

    _, short = _compute_transfer_schedules(db_session, user.id, rule, date(2026, 1, 1), date(2026, 1, 10))
    _, full = _compute_transfer_schedules(db_session, user.id, rule, date(2026, 1, 1), date(2026, 12, 31))

    assert short[date(2026, 1, 1)] == full[date(2026, 1, 1)] == Decimal("3000")


# ── engine injection ──────────────────────────────────────────────────────────

def test_sweep_shows_as_an_outflow_on_checking(db_session):
    user, savings, checking, _ = _seed(db_session)
    _bill_and_paycheck(db_session, user, checking)
    _rule(db_session, user, savings, checking, sweep_ceiling="2000", sweep_to=savings)
    db_session.commit()

    entries = build_forecast(db_session, user.id, checking.id, date(2026, 1, 1), date(2026, 1, 31))

    jan1 = next(e for e in entries if e.date == date(2026, 1, 1))
    sweep = [t for t in jan1.transactions if t.name == "Sweep to Savings"]
    assert len(sweep) == 1
    assert sweep[0].amount == Decimal("-3000")
    assert sweep[0].is_transfer and sweep[0].is_planned_transfer
    assert jan1.projected_balance == Decimal("3500.00")  # 6,500 - 3,000
    assert min(e.projected_balance for e in entries) == Decimal("2500.00")


def test_sweep_destination_forecast_shows_the_inflow(db_session):
    """The destination here is a third account (not the top-up source), so
    the engine has to find the rule by sweep_to_account_id too."""
    user, savings, checking, brokerage = _seed(db_session)
    _bill_and_paycheck(db_session, user, checking)
    _rule(db_session, user, savings, checking, sweep_ceiling="2000", sweep_to=brokerage)
    db_session.commit()

    dest = build_forecast(db_session, user.id, brokerage.id, date(2026, 1, 1), date(2026, 1, 31))
    jan1 = next(e for e in dest if e.date == date(2026, 1, 1))
    inflow = [t for t in jan1.transactions if t.name == "Sweep from Main Checking"]
    assert len(inflow) == 1
    assert inflow[0].amount == Decimal("3000")
    assert inflow[0].is_transfer and inflow[0].is_planned_transfer
    assert jan1.projected_balance == Decimal("23000.00")

    # The top-up source isn't the sweep destination, so it sees no sweep.
    src = build_forecast(db_session, user.id, savings.id, date(2026, 1, 1), date(2026, 1, 31))
    assert not any(t.name.startswith("Sweep") for e in src for t in e.transactions)


# ── API ───────────────────────────────────────────────────────────────────────

def _client(db, user):
    app = FastAPI()
    app.include_router(forecast_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _body(savings, checking, **over):
    body = {
        "from_account_id": savings.id, "to_account_id": checking.id,
        "action_threshold": "500", "target_floor": "1000", "increment": "1000",
        "check_day": 1, "is_active": True, "sweep_ceiling": None, "sweep_to_account_id": None,
    }
    body.update(over)
    return body


def test_checking_level_get_is_null_before_any_rule(db_session):
    user, savings, checking, _ = _seed(db_session)
    db_session.commit()
    r = _client(db_session, user).get(f"/forecast/checking-level?account_id={checking.id}")
    assert r.status_code == 200
    assert r.json() is None


def test_checking_level_put_then_get_round_trip_and_update_in_place(db_session):
    user, savings, checking, brokerage = _seed(db_session)
    db_session.commit()
    c = _client(db_session, user)

    r = c.put("/forecast/checking-level", json=_body(savings, checking, sweep_ceiling="3000",
                                                    sweep_to_account_id=brokerage.id))
    assert r.status_code == 200, r.text
    first = r.json()
    assert Decimal(first["sweep_ceiling"]) == Decimal("3000")
    assert first["sweep_to_account_id"] == brokerage.id

    got = c.get(f"/forecast/checking-level?account_id={checking.id}").json()
    assert got == first

    r = c.put("/forecast/checking-level", json=_body(savings, checking, target_floor="1500", check_day=15))
    assert r.status_code == 200
    assert r.json()["id"] == first["id"]
    assert r.json()["sweep_ceiling"] is None
    assert db_session.query(models.BufferTransferRule).filter_by(user_id=user.id).count() == 1


@pytest.mark.parametrize("over", [
    {"increment": "0"},
    {"target_floor": "400"},                       # below action_threshold
    {"check_day": 29},
    {"check_day": 0},
    {"sweep_ceiling": "1000"},                     # not above target_floor
    {"sweep_ceiling": "3000"},                     # no destination
])
def test_checking_level_rejects_invalid_settings(db_session, over):
    user, savings, checking, _ = _seed(db_session)
    db_session.commit()
    body = _body(savings, checking, **over)
    if over.get("sweep_ceiling") == "1000":
        body["sweep_to_account_id"] = savings.id
    r = _client(db_session, user).put("/forecast/checking-level", json=body)
    assert r.status_code == 422, r.text
    assert db_session.query(models.BufferTransferRule).count() == 0


def test_checking_level_rejects_same_from_and_to(db_session):
    user, savings, checking, _ = _seed(db_session)
    db_session.commit()
    r = _client(db_session, user).put("/forecast/checking-level", json=_body(checking, checking))
    assert r.status_code == 422


def test_checking_level_rejects_sweep_back_into_checking(db_session):
    user, savings, checking, _ = _seed(db_session)
    db_session.commit()
    r = _client(db_session, user).put("/forecast/checking-level",
                                      json=_body(savings, checking, sweep_ceiling="3000",
                                                 sweep_to_account_id=checking.id))
    assert r.status_code == 422


def test_checking_level_rejects_an_inactive_account(db_session):
    user, savings, checking, brokerage = _seed(db_session)
    brokerage.is_active = False
    db_session.commit()
    c = _client(db_session, user)
    assert c.put("/forecast/checking-level", json=_body(brokerage, checking)).status_code == 422
    assert c.put("/forecast/checking-level", json=_body(savings, checking, sweep_ceiling="3000",
                                                        sweep_to_account_id=brokerage.id)).status_code == 422


def test_checking_level_foreign_account_is_404(db_session):
    user, savings, checking, _ = _seed(db_session)
    _, other_savings, other_checking, _ = _seed(db_session, username="other")
    db_session.commit()
    c = _client(db_session, user)
    assert c.get(f"/forecast/checking-level?account_id={other_checking.id}").status_code == 404
    assert c.put("/forecast/checking-level", json=_body(other_savings, checking)).status_code == 404
    assert c.put("/forecast/checking-level", json=_body(savings, other_checking)).status_code == 404
    assert c.put("/forecast/checking-level", json=_body(savings, checking, sweep_ceiling="3000",
                                                        sweep_to_account_id=other_savings.id)).status_code == 404
    assert db_session.query(models.BufferTransferRule).count() == 0


def test_checking_level_get_does_not_write(db_session):
    user, savings, checking, _ = _seed(db_session)
    db_session.commit()
    _client(db_session, user).get(f"/forecast/checking-level?account_id={checking.id}")
    assert db_session.query(models.BufferTransferRule).count() == 0


# ── user deletion with a sweep destination set ───────────────────────────────

@pytest.mark.parametrize("strip_on_delete", [False, True])
def test_a_user_with_a_sweep_destination_can_be_deleted(strip_on_delete):
    """buffer_transfer_rules.sweep_to_account_id is a third fk from a
    user-owned table into accounts. Deleting the user cascades into both the
    rules and the accounts; the rule rows must go first (or the fk clear
    itself). Run with and without ON DELETE SET NULL in the DDL, so the
    delete is proven not to depend on the clause."""
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from backend.auth import hash_password
    from backend.database import Base
    from backend.routers.auth import delete_account
    from backend.schemas import DeleteAccountRequest

    constraint = next(iter(models.BufferTransferRule.__table__.c.sweep_to_account_id.foreign_keys)).constraint
    original = constraint.ondelete
    assert original == "SET NULL"

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _fk_pragma(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    try:
        if strip_on_delete:
            constraint.ondelete = None
        Base.metadata.create_all(bind=engine)
    finally:
        constraint.ondelete = original

    db = sessionmaker(bind=engine)()
    try:
        user, savings, checking, brokerage = _seed(db)
        user.hashed_password = hash_password("correct-password")
        _rule(db, user, savings, checking, sweep_ceiling="3000", sweep_to=brokerage)
        db.commit()

        delete_account(DeleteAccountRequest(password="correct-password"), db, user)  # must not raise

        assert db.query(models.User).count() == 0
        assert db.query(models.BufferTransferRule).count() == 0
    finally:
        db.close()
        engine.dispose()
