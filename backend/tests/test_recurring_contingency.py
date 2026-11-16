from datetime import date
from decimal import Decimal
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.routers import recurring as recurring_router_module
from backend.dependencies import get_db, get_current_user


@pytest.fixture()
def client(db_session):
    user = models.User(username="cp", hashed_password="x", display_name="CP")
    db_session.add(user)
    db_session.flush()
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
    )
    db_session.add(account)
    db_session.commit()
    app = FastAPI()
    app.include_router(recurring_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app), user, account


def _essential_item(db, user, account, **kw):
    defaults = dict(
        user_id=user.id, account_id=account.id, name="Essential Thing",
        amount=Decimal("100.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=1,
        start_date=date(2026, 1, 1), is_essential=True,
    )
    defaults.update(kw)
    item = models.RecurringItem(**defaults)
    db.add(item)
    db.flush()
    return item


def test_floor_is_three_times_essential_monthly_total(client, db_session):
    test_client, user, account = client
    _essential_item(db_session, user, account, amount=Decimal("1000.00"))
    db_session.commit()

    body = test_client.get("/recurring/contingency").json()

    assert body["floor"] == "3000.00"


def test_non_essential_item_excluded_from_floor_but_in_cut_list(client, db_session):
    test_client, user, account = client
    _essential_item(db_session, user, account, name="Non-essential", amount=Decimal("50.00"), is_essential=False)
    db_session.commit()

    body = test_client.get("/recurring/contingency").json()

    assert body["floor"] == "0.00"
    assert [i["name"] for i in body["cut_list"]] == ["Non-essential"]


def test_essential_item_never_in_cut_list(client, db_session):
    test_client, user, account = client
    _essential_item(db_session, user, account, amount=Decimal("5000.00"))
    db_session.commit()

    body = test_client.get("/recurring/contingency").json()

    assert body["cut_list"] == []


def test_inactive_item_excluded_from_both_floor_and_cut_list(client, db_session):
    test_client, user, account = client
    _essential_item(db_session, user, account, amount=Decimal("1000.00"), is_active=False)
    _essential_item(db_session, user, account, name="Inactive non-essential", amount=Decimal("50.00"), is_essential=False, is_active=False)
    db_session.commit()

    body = test_client.get("/recurring/contingency").json()

    assert body["floor"] == "0.00"
    assert body["cut_list"] == []


def test_missing_groceries_category_resolves_to_zero_not_error(client, db_session):
    """No 'Groceries' category exists at all for this user -- the floor's
    grocery component must be $0, not a crash."""
    test_client, user, account = client

    resp = test_client.get("/recurring/contingency")

    assert resp.status_code == 200
    assert resp.json()["floor"] == "0.00"


def test_groceries_budget_allocation_added_to_floor(client, db_session):
    test_client, user, account = client
    groceries_cat = models.Category(
        user_id=user.id, name="Groceries", type=models.CategoryType.expense, color="#000000",
    )
    db_session.add(groceries_cat)
    db_session.flush()
    db_session.add(models.BudgetAllocation(
        user_id=user.id, category_id=groceries_cat.id, year=date.today().year,
        month=0, budgeted_amount=Decimal("700.00"),
    ))
    db_session.commit()

    body = test_client.get("/recurring/contingency").json()

    assert body["floor"] == "2100.00"  # 700 * 3, no recurring items


def test_contingency_pause_rejected_on_essential_item(client, db_session):
    test_client, user, account = client
    item = _essential_item(db_session, user, account)
    db_session.commit()

    resp = test_client.post(f"/recurring/{item.id}/contingency-pause")

    assert resp.status_code == 400


def test_contingency_pause_and_unpause_on_non_essential_item(client, db_session):
    test_client, user, account = client
    item = _essential_item(db_session, user, account, is_essential=False)
    db_session.commit()

    resp = test_client.post(f"/recurring/{item.id}/contingency-pause")
    assert resp.status_code == 201
    body = test_client.get("/recurring/contingency").json()
    assert body["cut_list"][0]["is_paused"] is True

    resp2 = test_client.delete(f"/recurring/{item.id}/contingency-pause")
    assert resp2.status_code == 204
    body2 = test_client.get("/recurring/contingency").json()
    assert body2["cut_list"][0]["is_paused"] is False


def test_other_users_accounts_and_items_never_leak_into_contingency(client, db_session):
    test_client, user, account = client
    other_user = models.User(username="cp-other", hashed_password="x", display_name="Other")
    db_session.add(other_user)
    db_session.flush()
    other_account = models.Account(
        user_id=other_user.id, name="Other Checking", type=models.AccountType.checking,
        is_emergency_fund=True, current_balance=Decimal("999999.00"),
    )
    db_session.add(other_account)
    db_session.flush()
    _essential_item(db_session, other_user, other_account, name="Other User Item", amount=Decimal("99999.00"))
    db_session.commit()

    body = test_client.get("/recurring/contingency").json()

    assert body["floor"] == "0.00"
    assert body["emergency_fund_balance"] == "0.00"
    assert body["cut_list"] == []
