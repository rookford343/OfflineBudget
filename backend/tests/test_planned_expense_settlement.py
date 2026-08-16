from datetime import date, timedelta
from decimal import Decimal
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.dependencies import get_db, get_current_user
from backend.routers import planned_expenses as planned_expenses_router_module


def _client(db_session, user):
    app = FastAPI()
    app.include_router(planned_expenses_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _mk(db):
    u = models.User(username="s", hashed_password="x", display_name="S")
    db.add(u); db.flush()
    a = models.Account(user_id=u.id, name="Chk", type=models.AccountType.checking)
    db.add(a); db.flush()
    return u, a


def test_settled_one_off_drops_out_of_the_default_list(db_session):
    u, a = _mk(db_session)
    pe = models.PlannedExpense(user_id=u.id, account_id=a.id, name="Bonus",
                               amount=Decimal("100.00"),
                               expected_date=date.today() - timedelta(days=5))
    db_session.add(pe); db_session.commit()
    c = _client(db_session, u)

    assert len(c.get("/planned-expenses").json()) == 1
    r = c.post(f"/planned-expenses/{pe.id}/settle", json={"actual_amount": "97.50"})
    assert r.status_code == 200, r.text

    assert c.get("/planned-expenses").json() == []
    archived = c.get("/planned-expenses", params={"include_settled": True}).json()
    assert len(archived) == 1
    # The estimate survives beside the actual -- that comparison is the point.
    assert Decimal(archived[0]["amount"]) == Decimal("100.00")
    assert Decimal(archived[0]["actual_amount"]) == Decimal("97.50")
    assert archived[0]["is_settled"] is True


def test_settling_with_no_amount_records_it_never_happened(db_session):
    u, a = _mk(db_session)
    pe = models.PlannedExpense(user_id=u.id, account_id=a.id, name="Trip",
                               amount=Decimal("500.00"),
                               expected_date=date.today() - timedelta(days=1))
    db_session.add(pe); db_session.commit()
    c = _client(db_session, u)

    c.post(f"/planned-expenses/{pe.id}/settle", json={"actual_amount": None})
    archived = c.get("/planned-expenses", params={"include_settled": True}).json()
    assert archived[0]["actual_amount"] is None
    assert archived[0]["is_settled"] is True


def test_unsettle_restores_it_to_the_active_list(db_session):
    u, a = _mk(db_session)
    pe = models.PlannedExpense(user_id=u.id, account_id=a.id, name="X",
                               amount=Decimal("10.00"),
                               expected_date=date.today() - timedelta(days=2))
    db_session.add(pe); db_session.commit()
    c = _client(db_session, u)
    c.post(f"/planned-expenses/{pe.id}/settle", json={"actual_amount": "10.00"})
    c.post(f"/planned-expenses/{pe.id}/unsettle")
    assert len(c.get("/planned-expenses").json()) == 1


def test_forecast_ignores_a_settled_one_off(db_session):
    """The real transaction is already in the ledger once it's settled, so
    projecting the estimate as well would double-count it."""
    from backend.services.forecast_engine import build_forecast
    u, a = _mk(db_session)
    a.current_balance = Decimal("1000.00")
    future = date.today() + timedelta(days=10)
    pe = models.PlannedExpense(user_id=u.id, account_id=a.id, name="Big",
                               amount=Decimal("400.00"), expected_date=future)
    db_session.add(pe); db_session.commit()

    start, end = date.today(), date.today() + timedelta(days=30)
    with_pe = min(r.projected_balance for r in build_forecast(db_session, u.id, a.id, start, end))
    pe.settled_on = date.today(); pe.actual_amount = Decimal("400.00")
    db_session.commit()
    without = min(r.projected_balance for r in build_forecast(db_session, u.id, a.id, start, end))

    assert without > with_pe
