"""'Amounts changed?' prompts: a recurring item whose latest linked payment
differs from its planned amount asks the user whether to update it going
forward. Nothing changes until the user answers.

A price change is a step (e.g. a loan payment dropping after an escrow
review), so the suggestion is the LATEST payment, not an average. A bill that
swings month to month gets offered "stop asking" instead of a number.
"""
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import models
from backend.dependencies import get_current_user, get_db
from backend.routers import recurring as recurring_router_module
from backend.services.amount_drift import answer_drift, items_with_drift

TODAY = date(2026, 10, 16)


def _setup(db, planned="1000.00", **item_kw):
    user = models.User(username="drift", hashed_password="x", display_name="D")
    db.add(user)
    db.flush()
    acct = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking,
                          current_balance=Decimal("5000"))
    db.add(acct)
    db.flush()
    item = models.RecurringItem(user_id=user.id, account_id=acct.id, name="Home Loan",
                                amount=Decimal(planned), type=models.RecurringType.expense,
                                frequency=models.RecurringFrequency.monthly, day_of_month=1,
                                start_date=date(2026, 1, 1), **item_kw)
    db.add(item)
    db.commit()
    return user, acct, item


def _paid(db, user, acct, item, amount, on, linked=True):
    db.add(models.Transaction(user_id=user.id, account_id=acct.id, date=on, amount=-Decimal(amount),
                              description="LOAN SERVICER PMT", is_actual=True,
                              recurring_item_id=item.id if linked else None))
    db.commit()


def test_a_step_change_suggests_the_latest_payment_not_an_average(db_session):
    user, acct, item = _setup(db_session)
    _paid(db_session, user, acct, item, "1000.00", date(2026, 8, 1))
    _paid(db_session, user, acct, item, "960.00", date(2026, 9, 1))
    _paid(db_session, user, acct, item, "960.00", date(2026, 10, 1))
    [d] = items_with_drift(db_session, user.id, TODAY)
    assert d.latest_amount == Decimal("960.00")
    assert d.planned_amount == Decimal("1000.00")
    assert d.latest_date == date(2026, 10, 1)
    assert d.varies is False


def test_flags_after_the_first_changed_payment(db_session):
    user, acct, item = _setup(db_session)
    _paid(db_session, user, acct, item, "960.00", date(2026, 10, 1))
    assert [d.recurring_item_id for d in items_with_drift(db_session, user.id, TODAY)] == [item.id]


@pytest.mark.parametrize("planned,paid", [
    pytest.param("1000.00", "1000.00", id="exact"),
    pytest.param("1000.00", "1008.00", id="over_5_dollars_but_under_1_percent"),
    pytest.param("60.00", "64.00", id="over_1_percent_but_under_5_dollars"),
])
def test_small_or_no_difference_is_not_flagged(db_session, planned, paid):
    user, acct, item = _setup(db_session, planned=planned)
    _paid(db_session, user, acct, item, paid, date(2026, 10, 1))
    assert items_with_drift(db_session, user.id, TODAY) == []


def test_unlinked_and_old_payments_are_ignored(db_session):
    user, acct, item = _setup(db_session)
    _paid(db_session, user, acct, item, "500.00", date(2026, 10, 1), linked=False)
    _paid(db_session, user, acct, item, "500.00", TODAY - timedelta(days=200))
    assert items_with_drift(db_session, user.id, TODAY) == []


def test_a_bill_that_swings_is_offered_stop_asking(db_session):
    user, acct, item = _setup(db_session, planned="200.00")
    for amt, on in [("150.00", date(2026, 7, 20)), ("240.00", date(2026, 8, 20)), ("180.00", date(2026, 9, 20))]:
        _paid(db_session, user, acct, item, amt, on)
    [d] = items_with_drift(db_session, user.id, TODAY)
    assert d.varies is True


def test_one_odd_charge_among_steady_ones_still_suggests_the_new_amount(db_session):
    """A one-time device charge on a phone bill must not make a steady price
    change look like a bill that swings."""
    user, acct, item = _setup(db_session, planned="100.00")
    for amt, on in [("250.00", date(2026, 7, 20)), ("90.00", date(2026, 8, 20)), ("90.00", date(2026, 9, 20))]:
        _paid(db_session, user, acct, item, amt, on)
    [d] = items_with_drift(db_session, user.id, TODAY)
    assert (d.varies, d.latest_amount) == (False, Decimal("90.00"))


@pytest.mark.parametrize("kw", [
    pytest.param({"amount_varies": True}, id="marked_varies"),
    pytest.param({"is_active": False}, id="inactive"),
    pytest.param({"statement_day": 17}, id="confirmed_each_month_already"),
])
def test_excluded_items_never_prompt(db_session, kw):
    user, acct, item = _setup(db_session, **kw)
    _paid(db_session, user, acct, item, "960.00", date(2026, 10, 1))
    assert items_with_drift(db_session, user.id, TODAY) == []


def test_update_sets_the_latest_payment_as_the_amount(db_session):
    user, acct, item = _setup(db_session)
    _paid(db_session, user, acct, item, "960.00", date(2026, 10, 1))
    answer_drift(db_session, user.id, item.id, "update", TODAY)
    db_session.refresh(item)
    assert item.amount == Decimal("960.00")
    assert items_with_drift(db_session, user.id, TODAY) == []


def test_keep_stays_quiet_until_a_newer_payment_posts(db_session):
    user, acct, item = _setup(db_session)
    _paid(db_session, user, acct, item, "960.00", date(2026, 9, 1))
    answer_drift(db_session, user.id, item.id, "keep", TODAY)
    db_session.refresh(item)
    assert item.amount == Decimal("1000.00")
    assert items_with_drift(db_session, user.id, TODAY) == []
    _paid(db_session, user, acct, item, "960.00", date(2026, 10, 1))
    assert len(items_with_drift(db_session, user.id, TODAY)) == 1


def test_varies_stops_all_future_prompts(db_session):
    user, acct, item = _setup(db_session)
    _paid(db_session, user, acct, item, "960.00", date(2026, 9, 1))
    answer_drift(db_session, user.id, item.id, "varies", TODAY)
    _paid(db_session, user, acct, item, "900.00", date(2026, 10, 1))
    db_session.refresh(item)
    assert item.amount_varies is True
    assert items_with_drift(db_session, user.id, TODAY) == []


def test_answering_with_nothing_to_answer_is_refused(db_session):
    user, acct, item = _setup(db_session)
    with pytest.raises(LookupError):
        answer_drift(db_session, user.id, item.id, "update", TODAY)


def _client(db, user):
    app = FastAPI()
    app.include_router(recurring_router_module.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_endpoints_list_then_update(db_session):
    user, acct, item = _setup(db_session)
    _paid(db_session, user, acct, item, "960.00", date(2026, 10, 1))
    with patch("backend.routers.recurring._today", return_value=TODAY):
        c = _client(db_session, user)
        r = c.get("/recurring/amount-drift")
        assert r.status_code == 200, r.text
        assert [(d["recurring_item_id"], Decimal(d["latest_amount"])) for d in r.json()] \
            == [(item.id, Decimal("960.00"))]
        r = c.post(f"/recurring/{item.id}/amount-drift", json={"action": "update"})
        assert r.status_code == 200, r.text
        assert Decimal(r.json()["amount"]) == Decimal("960.00")
        assert c.get("/recurring/amount-drift").json() == []


def test_endpoint_refuses_another_users_item_and_bad_actions(db_session):
    user, acct, item = _setup(db_session)
    _paid(db_session, user, acct, item, "960.00", date(2026, 10, 1))
    other = models.User(username="other", hashed_password="x", display_name="O")
    db_session.add(other)
    db_session.commit()
    with patch("backend.routers.recurring._today", return_value=TODAY):
        assert _client(db_session, other).post(f"/recurring/{item.id}/amount-drift",
                                               json={"action": "update"}).status_code == 404
        assert _client(db_session, user).post(f"/recurring/{item.id}/amount-drift",
                                              json={"action": "delete"}).status_code == 422
    db_session.refresh(item)
    assert item.amount == Decimal("1000.00")
