"""/bonus-plans CRUD. Made-up figures."""
from datetime import date
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import models
from backend.dependencies import get_current_user
from backend.routers import bonus_plans as bonus_router


def _client(db, user):
    app = FastAPI()
    app.include_router(bonus_router.router)
    app.dependency_overrides[bonus_router.get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _seed(db, username="api"):
    user = models.User(username=username, hashed_password="x", display_name="A",
                       annual_salary=Decimal("100000"), annual_salary_year=2026, annual_raise_pct=Decimal("0"))
    db.add(user)
    db.flush()
    acct = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking,
                          current_balance=Decimal("1"))
    db.add(acct)
    db.flush()
    item = models.RecurringItem(user_id=user.id, account_id=acct.id, name="Annual Bonus", amount=Decimal("1"),
                                type=models.RecurringType.income, frequency=models.RecurringFrequency.yearly,
                                month_of_year=4, day_of_month=15, start_date=date(2026, 1, 1))
    db.add(item)
    db.commit()
    return user, item


BODY = {"target_pct": "20", "salary_lag_years": 1, "withholding_pct": "30",
        "years": [{"year": 2027, "gross_amount": "12000"}]}


def test_create_list_update_delete(db_session):
    user, item = _seed(db_session)
    c = _client(db_session, user)
    r = c.post("/bonus-plans", json={**BODY, "recurring_item_id": item.id})
    assert r.status_code == 201, r.text
    plan = r.json()
    assert plan["item_name"] == "Annual Bonus"
    assert len(plan["upcoming"]) == 3
    db_session.refresh(item)
    assert item.amount == Decimal(plan["upcoming"][0]["net"])
    r = c.put(f"/bonus-plans/{plan['id']}", json={**BODY, "recurring_item_id": item.id, "years": []})
    assert r.status_code == 200 and r.json()["years"] == []
    assert len(c.get("/bonus-plans").json()) == 1
    assert c.delete(f"/bonus-plans/{plan['id']}").status_code == 204
    assert c.get("/bonus-plans").json() == []


def test_one_plan_per_item(db_session):
    user, item = _seed(db_session)
    c = _client(db_session, user)
    assert c.post("/bonus-plans", json={**BODY, "recurring_item_id": item.id}).status_code == 201
    assert c.post("/bonus-plans", json={**BODY, "recurring_item_id": item.id}).status_code == 409


def test_item_must_be_a_yearly_income_item(db_session):
    user, item = _seed(db_session)
    item.frequency = models.RecurringFrequency.monthly
    db_session.commit()
    assert _client(db_session, user).post("/bonus-plans", json={**BODY, "recurring_item_id": item.id}).status_code == 422


def test_duplicate_years_are_refused(db_session):
    user, item = _seed(db_session)
    body = {**BODY, "recurring_item_id": item.id,
            "years": [{"year": 2027, "gross_amount": "1"}, {"year": 2027, "gross_amount": "2"}]}
    assert _client(db_session, user).post("/bonus-plans", json=body).status_code == 422


def test_resending_the_same_year_on_update_succeeds(db_session):
    """PUT re-sending a year that's already on the plan (e.g. the form just
    submitting its own current state, with a tweaked amount) used to 500 --
    plan.years was reassigned wholesale, and SQLAlchemy flushed the new
    rows' INSERTs before the orphaned rows' DELETEs, colliding with
    UniqueConstraint(plan_id, year)."""
    user, item = _seed(db_session)
    c = _client(db_session, user)
    r = c.post("/bonus-plans", json={**BODY, "recurring_item_id": item.id})
    assert r.status_code == 201, r.text
    plan_id = r.json()["id"]
    body = {**BODY, "recurring_item_id": item.id, "years": [{"year": 2027, "gross_amount": "15000"}]}
    r = c.put(f"/bonus-plans/{plan_id}", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["years"] == [{"year": 2027, "gross_amount": "15000.00"}]


def test_get_does_not_write_the_refreshed_item_amount(db_session):
    """GET must stay read-only -- backend/dependencies.py's get_current_user
    only blocks writes on non-GET methods, so a write here would let a View
    Only account trigger one. refresh_item_amounts runs after POST/PUT and
    on the scheduler sweep instead."""
    user, item = _seed(db_session)
    c = _client(db_session, user)
    r = c.post("/bonus-plans", json={**BODY, "recurring_item_id": item.id})
    assert r.status_code == 201, r.text
    item.amount = Decimal("999.99")
    db_session.commit()
    assert c.get("/bonus-plans").status_code == 200
    db_session.refresh(item)
    assert item.amount == Decimal("999.99")
