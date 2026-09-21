"""Proposal CRUD, and the forecast endpoint resolving a scenario server-side.

The endpoint gains scenario_id rather than making the client assemble
proposals into a request body: the client cannot express a transient
RecurringItem, and duplicating the resolution rules (a committed scenario
resolves to nothing) in TypeScript would be a second place for them to drift.
"""
from datetime import date
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import models
from backend.dependencies import get_db, get_current_user
from backend.routers import scenarios as scenarios_router
from backend.routers import forecast as forecast_router


@pytest.fixture()
def client(db_session):
    user = models.User(username="api", hashed_password="x", display_name="Api")
    db_session.add(user)
    db_session.flush()
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("5000.00"),
    )
    db_session.add(account)
    db_session.flush()
    scenario = models.ForecastScenario(user_id=user.id, name="Test")
    db_session.add(scenario)
    db_session.commit()

    app = FastAPI()
    app.include_router(scenarios_router.router)
    app.include_router(forecast_router.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app), user, account, scenario


def test_post_an_item_then_read_it_back_on_the_scenario(client):
    c, _user, account, scenario = client
    r = c.post(f"/scenarios/{scenario.id}/items", json={
        "name": "iPhone Trade-In", "amount": "57.87", "type": "expense",
        "frequency": "monthly", "day_of_month": 23,
        "start_date": "2026-10-23", "end_date": "2028-10-23",
        "account_id": account.id,
    })
    assert r.status_code == 201, r.text
    assert r.json()["committed_recurring_item_id"] is None

    listed = c.get("/scenarios").json()
    assert [i["name"] for i in listed[0]["proposed_items"]] == ["iPhone Trade-In"]
    assert listed[0]["status"] == "draft"


def test_post_an_expense_then_delete_it(client):
    c, _user, account, scenario = client
    created = c.post(f"/scenarios/{scenario.id}/expenses", json={
        "name": "New laptop", "amount": "2400.00",
        "expected_date": "2026-12-01", "account_id": account.id,
    }).json()

    assert c.delete(f"/scenarios/{scenario.id}/expenses/{created['id']}").status_code == 204
    assert c.get("/scenarios").json()[0]["proposed_expenses"] == []


def test_an_item_on_a_missing_scenario_is_404(client):
    c, _user, account, _scenario = client
    r = c.post("/scenarios/9999/items", json={
        "name": "Nope", "amount": "1.00", "type": "expense", "frequency": "monthly",
        "day_of_month": 1, "start_date": "2026-10-01", "account_id": account.id,
    })
    assert r.status_code == 404


def test_deleting_an_item_belonging_to_another_scenario_is_404(client):
    c, _user, account, scenario = client
    created = c.post(f"/scenarios/{scenario.id}/items", json={
        "name": "Mine", "amount": "1.00", "type": "expense", "frequency": "monthly",
        "day_of_month": 1, "start_date": "2026-10-01", "account_id": account.id,
    }).json()
    other_scenario = c.post("/scenarios", json={"name": "Other"}).json()

    r = c.delete(f"/scenarios/{other_scenario['id']}/items/{created['id']}")
    assert r.status_code == 404


def test_quarters_scenario_resolves_a_scenario_id_server_side(client):
    c, _user, account, scenario = client
    c.post(f"/scenarios/{scenario.id}/items", json={
        "name": "Gym", "amount": "45.00", "type": "expense", "frequency": "monthly",
        "day_of_month": 10, "start_date": "2026-01-10", "account_id": account.id,
    })

    baseline = c.post("/forecast/quarters-scenario", json={
        "account_id": account.id, "year": 2026,
    }).json()
    with_scenario = c.post("/forecast/quarters-scenario", json={
        "account_id": account.id, "year": 2026, "scenario_id": scenario.id,
    }).json()

    assert baseline[3]["close_balance"] != with_scenario[3]["close_balance"]


def test_quarters_scenario_with_an_unknown_scenario_id_is_404(client):
    c, _user, account, _scenario = client
    r = c.post("/forecast/quarters-scenario", json={
        "account_id": account.id, "year": 2026, "scenario_id": 9999,
    })
    assert r.status_code == 404


# ── Proposal validation ───────────────────────────────────────────────────────
# Committing a scenario copies these fields VERBATIM onto real RecurringItem
# and PlannedExpense rows, so this schema is the last gate before a typo
# becomes a real bill. It used to type `type`, `frequency` and `direction` as
# bare strings with no day_of_month bounds at all, while RecurringCreate --
# the schema for the identical row created any other way -- used enums and a
# 0-31 check. The two consequences were not symmetrical: an out-of-range day
# was ACCEPTED (45 silently reads as "last day of month", a negative day never
# fires at all, so committing one creates a permanently invisible real bill),
# while an unknown enum value 500'd. Both are 422 now.

def test_a_day_of_month_past_the_end_of_any_month_is_rejected(client):
    c, _user, account, scenario = client
    r = c.post(f"/scenarios/{scenario.id}/items", json={
        "name": "Typo", "amount": "10.00", "type": "expense", "frequency": "monthly",
        "day_of_month": 45, "start_date": "2026-10-01", "account_id": account.id,
    })
    assert r.status_code == 422, r.text


def test_a_negative_day_of_month_is_rejected(client):
    """The worse half of the pair: a negative day matches no day of any month,
    so the committed item is real, active, counted in the commitments total --
    and never appears on the forecast."""
    c, _user, account, scenario = client
    r = c.post(f"/scenarios/{scenario.id}/items", json={
        "name": "Typo", "amount": "10.00", "type": "expense", "frequency": "monthly",
        "day_of_month": -3, "start_date": "2026-10-01", "account_id": account.id,
    })
    assert r.status_code == 422, r.text
    assert c.get("/scenarios").json()[0]["proposed_items"] == []


def test_day_of_month_zero_is_still_accepted_as_last_day(client):
    """0 is the encoding for 'last day of month', not an out-of-range value --
    the same convention RecurringCreate uses. Bounding the field must not
    outlaw it."""
    c, _user, account, scenario = client
    r = c.post(f"/scenarios/{scenario.id}/items", json={
        "name": "Last day", "amount": "10.00", "type": "expense",
        "frequency": "monthly", "day_of_month": 0,
        "start_date": "2026-10-01", "account_id": account.id,
    })
    assert r.status_code == 201, r.text


def test_an_unknown_recurring_type_is_a_422_not_a_500(client):
    c, _user, account, scenario = client
    r = c.post(f"/scenarios/{scenario.id}/items", json={
        "name": "Nonsense", "amount": "10.00", "type": "banana",
        "frequency": "monthly", "day_of_month": 1,
        "start_date": "2026-10-01", "account_id": account.id,
    })
    assert r.status_code == 422, r.text


def test_an_unknown_frequency_is_a_422_not_a_500(client):
    c, _user, account, scenario = client
    r = c.post(f"/scenarios/{scenario.id}/items", json={
        "name": "Nonsense", "amount": "10.00", "type": "expense",
        "frequency": "fortnightly", "day_of_month": 1,
        "start_date": "2026-10-01", "account_id": account.id,
    })
    assert r.status_code == 422, r.text


def test_an_unknown_expense_direction_is_rejected(client):
    """Direction decides the SIGN of real money once committed."""
    c, _user, account, scenario = client
    r = c.post(f"/scenarios/{scenario.id}/expenses", json={
        "name": "Nonsense", "amount": "10.00", "expected_date": "2026-12-01",
        "direction": "sideways", "account_id": account.id,
    })
    assert r.status_code == 422, r.text
