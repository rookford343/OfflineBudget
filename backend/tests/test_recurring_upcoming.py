"""GET /recurring/upcoming -- the Dashboard's "Upcoming Bills" card.

Replaces the old client-side computation in Dashboard.tsx, which read
r.amount directly (ignoring any confirmed BillAmountOverride actual) and
matched on day_of_month alone (so a yearly or quarterly item showed up as
"due" in every month). This endpoint reuses summary_generator._next_fire_date
-- the single source of truth the daily email's own Upcoming list already
uses -- for the real next fire date, and applies the same
(recurring_item_id, due_date)-keyed override lookup forecast_engine.py uses
for its bill_actuals dict.
"""
from datetime import date
from decimal import Decimal
from unittest.mock import patch
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.dependencies import get_db, get_current_user
from backend.routers import recurring as recurring_router_module

TODAY = "backend.routers.recurring._today"


def _client(db, user):
    app = FastAPI()
    app.include_router(recurring_router_module.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _user(db, username="u"):
    user = models.User(username=username, hashed_password="x", display_name="U")
    db.add(user); db.flush()
    return user


def _account(db, user):
    acct = models.Account(
        user_id=user.id, name="Chk", type=models.AccountType.checking,
        current_balance=Decimal("1000.00"),
    )
    db.add(acct); db.flush()
    return acct


def _item(
    db, user, acct, *, name="Item", amount="100.00", day_of_month=10,
    frequency=models.RecurringFrequency.monthly, month_of_year=None,
    type=models.RecurringType.expense, is_active=True, card_id=None,
    start_date=date(2020, 1, 1), end_date=None,
):
    item = models.RecurringItem(
        user_id=user.id, account_id=acct.id, name=name, amount=Decimal(amount),
        type=type, frequency=frequency, day_of_month=day_of_month,
        month_of_year=month_of_year, is_active=is_active, card_id=card_id,
        start_date=start_date, end_date=end_date,
    )
    db.add(item); db.commit()
    return item


def _override(db, user, item, due_date, actual_amount):
    o = models.BillAmountOverride(
        user_id=user.id, recurring_item_id=item.id, due_date=due_date,
        actual_amount=Decimal(actual_amount),
    )
    db.add(o); db.commit()
    return o


def test_override_replaces_amount_on_its_date_only(db_session):
    user = _user(db_session); acct = _account(db_session, user)
    item = _item(db_session, user, acct, name="Utility", amount="100.00", day_of_month=10)
    # An override on a date OTHER than the upcoming occurrence must not leak
    # into it -- it's keyed to that one due date, nothing else.
    _override(db_session, user, item, date(2026, 9, 10), "999.00")

    client = _client(db_session, user)
    with patch(TODAY, return_value=date(2026, 10, 1)):
        resp = client.get("/recurring/upcoming", params={"days": 30})
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["due_date"] == "2026-10-10"
    assert Decimal(rows[0]["amount"]) == Decimal("100.00")
    assert rows[0]["estimated_amount"] == "100.00" or Decimal(rows[0]["estimated_amount"]) == Decimal("100.00")
    assert rows[0]["is_actual"] is False

    # Now add the override on the ACTUAL upcoming due date -- it should apply.
    _override(db_session, user, item, date(2026, 10, 10), "150.00")
    with patch(TODAY, return_value=date(2026, 10, 1)):
        resp = client.get("/recurring/upcoming", params={"days": 30})
    rows = resp.json()
    assert len(rows) == 1
    assert Decimal(rows[0]["amount"]) == Decimal("150.00")
    assert Decimal(rows[0]["estimated_amount"]) == Decimal("100.00")
    assert rows[0]["is_actual"] is True


def test_yearly_item_appears_only_in_its_month(db_session):
    user = _user(db_session); acct = _account(db_session, user)
    _item(
        db_session, user, acct, name="Annual Renewal", amount="300.00",
        frequency=models.RecurringFrequency.yearly, month_of_year=5, day_of_month=15,
    )

    client = _client(db_session, user)
    with patch(TODAY, return_value=date(2026, 10, 1)):
        resp = client.get("/recurring/upcoming", params={"days": 30})
    assert resp.json() == []

    with patch(TODAY, return_value=date(2026, 4, 20)):
        resp = client.get("/recurring/upcoming", params={"days": 30})
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["name"] == "Annual Renewal"
    assert rows[0]["due_date"] == "2026-05-15"


def test_inactive_item_excluded(db_session):
    user = _user(db_session); acct = _account(db_session, user)
    _item(db_session, user, acct, name="Cancelled", day_of_month=10, is_active=False)

    client = _client(db_session, user)
    with patch(TODAY, return_value=date(2026, 10, 1)):
        resp = client.get("/recurring/upcoming", params={"days": 30})
    assert resp.json() == []


def test_income_item_excluded(db_session):
    user = _user(db_session); acct = _account(db_session, user)
    _item(db_session, user, acct, name="Paycheck", day_of_month=10, type=models.RecurringType.income)

    client = _client(db_session, user)
    with patch(TODAY, return_value=date(2026, 10, 1)):
        resp = client.get("/recurring/upcoming", params={"days": 30})
    assert resp.json() == []


def test_window_respected(db_session):
    user = _user(db_session); acct = _account(db_session, user)
    # Today is Oct 20 and day_of_month=10 has already passed this month, so
    # the next occurrence is Nov 10 -- 21 days out.
    _item(db_session, user, acct, name="Just Outside", day_of_month=10)

    client = _client(db_session, user)
    with patch(TODAY, return_value=date(2026, 10, 20)):
        resp = client.get("/recurring/upcoming", params={"days": 15})
    assert resp.json() == []

    with patch(TODAY, return_value=date(2026, 10, 20)):
        resp = client.get("/recurring/upcoming", params={"days": 25})
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["due_date"] == "2026-11-10"


def test_scoped_to_current_user(db_session):
    user_a = _user(db_session, "a")
    user_b = _user(db_session, "b")
    acct_a = _account(db_session, user_a)
    acct_b = _account(db_session, user_b)
    _item(db_session, user_a, acct_a, name="Mine", day_of_month=10)
    _item(db_session, user_b, acct_b, name="Theirs", day_of_month=10)

    client = _client(db_session, user_a)
    with patch(TODAY, return_value=date(2026, 10, 1)):
        resp = client.get("/recurring/upcoming", params={"days": 30})
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["name"] == "Mine"


def test_sorted_by_due_date_then_name(db_session):
    user = _user(db_session); acct = _account(db_session, user)
    _item(db_session, user, acct, name="Zeta", day_of_month=10)
    _item(db_session, user, acct, name="Alpha", day_of_month=10)
    _item(db_session, user, acct, name="Earliest", day_of_month=5)

    client = _client(db_session, user)
    with patch(TODAY, return_value=date(2026, 10, 1)):
        resp = client.get("/recurring/upcoming", params={"days": 30})
    rows = resp.json()
    assert [r["name"] for r in rows] == ["Earliest", "Alpha", "Zeta"]


def test_card_paid_bill_still_listed_with_card_id(db_session):
    user = _user(db_session); acct = _account(db_session, user)
    card = models.CreditCard(
        user_id=user.id, name="Card", credit_limit=Decimal("1000.00"),
        statement_day=1, due_day=15,
    )
    db_session.add(card); db_session.commit()
    _item(db_session, user, acct, name="Card Bill", day_of_month=10, card_id=card.id)

    client = _client(db_session, user)
    with patch(TODAY, return_value=date(2026, 10, 1)):
        resp = client.get("/recurring/upcoming", params={"days": 30})
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["card_id"] == card.id


def test_days_window_is_bounded(db_session):
    user = _user(db_session)
    c = _client(db_session, user)
    assert c.get("/recurring/upcoming", params={"days": 367}).status_code == 422
    assert c.get("/recurring/upcoming", params={"days": -1}).status_code == 422
