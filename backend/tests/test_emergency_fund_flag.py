from datetime import date
from decimal import Decimal
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.dependencies import get_db, get_current_user
from backend.routers import accounts as accounts_router_module
from backend.services.budget_snapshot import compute_budget_snapshot


def _client(db_session, user):
    app = FastAPI()
    app.include_router(accounts_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_emergency_fund_flag_round_trips_including_unsetting(db_session):
    """`exclude_none` on the PATCH keeps False, so unchecking must persist --
    a flag you can set but not clear is worse than no flag."""
    user = models.User(username="e", hashed_password="x", display_name="E")
    db_session.add(user); db_session.flush()
    acct = models.Account(user_id=user.id, name="MM", type=models.AccountType.money_market,
                          current_balance=Decimal("26232.94"))
    db_session.add(acct); db_session.commit()
    c = _client(db_session, user)

    assert c.get("/accounts").json()[0]["is_emergency_fund"] is False
    c.patch(f"/accounts/{acct.id}", json={"is_emergency_fund": True})
    assert c.get("/accounts").json()[0]["is_emergency_fund"] is True
    c.patch(f"/accounts/{acct.id}", json={"is_emergency_fund": False})
    assert c.get("/accounts").json()[0]["is_emergency_fund"] is False


def test_emergency_fund_is_held_out_of_available_savings(db_session):
    """Dan's Money Market is an emergency fund. Counting it made available
    savings read $56,240.03 when only $30,007.09 was really available."""
    user = models.User(username="e2", hashed_password="x", display_name="E")
    db_session.add(user); db_session.flush()
    checking = models.Account(user_id=user.id, name="Chk", type=models.AccountType.checking,
                              current_balance=Decimal("1000.00"))
    savings = models.Account(user_id=user.id, name="Sav", type=models.AccountType.savings,
                             current_balance=Decimal("30007.09"))
    mm = models.Account(user_id=user.id, name="MM", type=models.AccountType.money_market,
                        current_balance=Decimal("26232.94"), is_emergency_fund=True)
    db_session.add_all([checking, savings, mm]); db_session.commit()

    entry = type("E", (), {"date": date(2026, 8, 7), "projected_balance": Decimal("5120.66"), "transactions": []})()
    with patch("backend.services.budget_snapshot.build_forecast", return_value=[entry]):
        snap = compute_budget_snapshot(db_session, user, checking.id, as_of=date(2026, 8, 7))

    assert snap.savings_balance == Decimal("30007.09")
