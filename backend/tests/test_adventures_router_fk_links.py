"""I1 fix-round tests: deleting a trip-linked PlannedExpense or SavingsGoal
through its own router must null the Adventures link first (no FK ondelete,
by ruling), not raise an IntegrityError."""
from datetime import date
from decimal import Decimal
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.dependencies import get_db, get_current_user
from backend.routers import planned_expenses as planned_expenses_router_module
from backend.routers import goals as goals_router_module
from backend.services.adventures import ensure_adventures_seeded
from backend.services.adventures_lifecycle import create_trip_from_template, commit_trip, create_trip_fund


def _client(db_session, user, router_module):
    app = FastAPI()
    app.include_router(router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _by_name(trip, name):
    return next(i for i in trip.items if i.name == name)


def _setup(db):
    u = models.User(username="fk", hashed_password="x", display_name="FK")
    db.add(u); db.flush()
    ensure_adventures_seeded(db, u.id)
    trip = create_trip_from_template(db, u.id, name="Beach", destination="Coast",
                                     start_date=date(2027, 3, 1), end_date=date(2027, 3, 5),
                                     travelers=2, default_card_id=None)
    return u, trip


def test_delete_trip_linked_planned_expense_nulls_the_item_link(db_session):
    u, trip = _setup(db_session)
    lodging = _by_name(trip, "Lodging")
    lodging.unit_cash = Decimal("200.00")
    commit_trip(db_session, trip)
    db_session.commit()

    pe_id = lodging.planned_expense_id
    assert pe_id is not None

    c = _client(db_session, u, planned_expenses_router_module)
    r = c.delete(f"/planned-expenses/{pe_id}")
    assert r.status_code == 204, r.text

    db_session.refresh(lodging)
    assert lodging.planned_expense_id is None
    assert db_session.get(models.PlannedExpense, pe_id) is None


def test_delete_trip_fund_goal_nulls_the_trip_link(db_session):
    u, trip = _setup(db_session)
    _by_name(trip, "Lodging").unit_cash = Decimal("200.00")
    goal = create_trip_fund(db_session, trip)
    db_session.commit()

    goal_id = goal.id
    assert trip.fund_goal_id == goal_id

    c = _client(db_session, u, goals_router_module)
    r = c.delete(f"/goals/{goal_id}")
    assert r.status_code == 200, r.text

    db_session.refresh(trip)
    assert trip.fund_goal_id is None
    assert db_session.get(models.SavingsGoal, goal_id) is None
