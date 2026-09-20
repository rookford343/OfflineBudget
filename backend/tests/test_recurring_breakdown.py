from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import models
from backend.dependencies import get_db, get_current_user
from backend.routers import recurring as recurring_router_module


@pytest.fixture()
def client(db_session):
    user = models.User(username="rec", hashed_password="x", display_name="Rec")
    db_session.add(user)
    db_session.flush()
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("1000.00"),
    )
    db_session.add(account)
    db_session.commit()

    app = FastAPI()
    app.include_router(recurring_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app), user, account


def _item(db, user, account, **kw):
    defaults = dict(
        user_id=user.id, account_id=account.id, name="Thing",
        amount=Decimal("100.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=1,
        start_date=date(2026, 1, 1),
    )
    defaults.update(kw)
    item = models.RecurringItem(**defaults)
    db.add(item)
    db.flush()
    return item


def test_breakdown_route_is_not_shadowed_by_the_item_id_route(client):
    """/recurring/{item_id} is declared in this same router, so /breakdown has
    to be registered BEFORE it -- otherwise FastAPI matches "breakdown" as an
    item_id and the endpoint 422s instead of answering."""
    test_client, _, _ = client

    resp = test_client.get("/recurring/breakdown")

    assert resp.status_code == 200, resp.text


def test_splits_ongoing_from_ending(client, db_session):
    test_client, user, account = client
    _item(db_session, user, account, name="Mortgage")
    _item(db_session, user, account, name="iPhone Duo", end_date=date(2028, 10, 23))
    db_session.commit()

    body = test_client.get("/recurring/breakdown").json()

    assert [i["name"] for i in body["ongoing"]] == ["Mortgage"]
    assert [i["name"] for i in body["ending"]] == ["iPhone Duo"]


def test_monthly_equivalent_normalizes_every_frequency(client, db_session):
    """"What does this cost me per month" is a different question from
    budget_snapshot._monthly_expenses, which deliberately charges a yearly
    bill in full in its own month to match the spreadsheet's Leftover row.
    Here a yearly item is a twelfth, so the ongoing-burn figure means what it
    says."""
    test_client, user, account = client
    _item(db_session, user, account, name="Monthly", amount=Decimal("100.00"),
          frequency=models.RecurringFrequency.monthly)
    _item(db_session, user, account, name="Yearly", amount=Decimal("199.99"),
          frequency=models.RecurringFrequency.yearly, month_of_year=10)
    _item(db_session, user, account, name="Quarterly", amount=Decimal("14.82"),
          frequency=models.RecurringFrequency.quarterly)
    _item(db_session, user, account, name="Weekly", amount=Decimal("10.00"),
          frequency=models.RecurringFrequency.weekly)
    _item(db_session, user, account, name="Biweekly", amount=Decimal("10.00"),
          frequency=models.RecurringFrequency.biweekly)
    db_session.commit()

    by_name = {i["name"]: Decimal(i["monthly_equivalent"])
               for i in test_client.get("/recurring/breakdown").json()["ongoing"]}

    assert by_name["Monthly"] == Decimal("100.00")
    assert by_name["Yearly"] == Decimal("16.67")     # 199.99 / 12
    assert by_name["Quarterly"] == Decimal("4.94")   # 14.82 / 3
    assert by_name["Weekly"] == Decimal("43.33")     # 10 * 52 / 12
    assert by_name["Biweekly"] == Decimal("21.67")   # 10 * 26 / 12


def test_ending_items_carry_months_remaining_and_sort_by_end_date(client, db_session):
    test_client, user, account = client
    today = date.today()
    _item(db_session, user, account, name="Later", end_date=today + timedelta(days=400))
    _item(db_session, user, account, name="Sooner", end_date=today + timedelta(days=70))
    db_session.commit()

    ending = test_client.get("/recurring/breakdown").json()["ending"]

    assert [i["name"] for i in ending] == ["Sooner", "Later"], "soonest roll-off first"
    assert ending[0]["months_remaining"] == 2
    assert ending[1]["months_remaining"] == 13


def test_an_item_whose_end_date_already_passed_reports_zero_months_left(client, db_session):
    """Still listed rather than hidden -- an active item past its end date is
    something to look at, not something to silently drop."""
    test_client, user, account = client
    _item(db_session, user, account, name="Expired", end_date=date.today() - timedelta(days=5))
    db_session.commit()

    ending = test_client.get("/recurring/breakdown").json()["ending"]

    assert ending[0]["name"] == "Expired"
    assert ending[0]["months_remaining"] == 0


def test_burn_totals_split_ongoing_from_temporary_and_ignore_income(client, db_session):
    """The point of the split: "what my life costs" shouldn't be inflated by
    a device payment that rolls off, and a paycheck isn't burn at all."""
    test_client, user, account = client
    _item(db_session, user, account, name="Mortgage", amount=Decimal("4404.65"))
    _item(db_session, user, account, name="iPhone Duo", amount=Decimal("57.87"),
          end_date=date(2028, 10, 23))
    _item(db_session, user, account, name="Paycheck", amount=Decimal("6066.63"),
          type=models.RecurringType.income)
    db_session.commit()

    body = test_client.get("/recurring/breakdown").json()

    assert Decimal(body["ongoing_monthly"]) == Decimal("4404.65")
    assert Decimal(body["ending_monthly"]) == Decimal("57.87")


def test_inactive_items_are_left_out(client, db_session):
    test_client, user, account = client
    _item(db_session, user, account, name="Cancelled", is_active=False)
    db_session.commit()

    body = test_client.get("/recurring/breakdown").json()

    assert body["ongoing"] == [] and body["ending"] == []
