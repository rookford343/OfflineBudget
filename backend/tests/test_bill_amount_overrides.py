import sys
from datetime import date, timedelta
from decimal import Decimal
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.dependencies import get_db, get_current_user
from backend.routers import bill_overrides as bill_overrides_router_module
from backend.services.forecast_engine import build_forecast, _next_occurrence_on_or_after, _adjust_for_weekend

FIXED_TODAY = date(2026, 11, 2)  # a Monday; Duke's day-8 bill posts Fri Nov 6, ahead of it


@pytest.fixture(autouse=True)
def _pin_today(monkeypatch):
    """Pin date.today() for this module, the forecast engine and the override
    router. Without it the 'next due date' helpers race the real calendar: a
    weekend due date posts on the Friday before, which can already be past."""
    class _FixedDate(date):
        @classmethod
        def today(cls):
            return FIXED_TODAY
    monkeypatch.setattr(sys.modules[__name__], "date", _FixedDate)
    monkeypatch.setattr("backend.services.forecast_engine.date", _FixedDate)
    monkeypatch.setattr("backend.routers.bill_overrides.date", _FixedDate)


def _client(db_session, user):
    app = FastAPI()
    app.include_router(bill_overrides_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _seed(db, day=8, amount="180.00"):
    user = models.User(username="d", hashed_password="x", display_name="D")
    db.add(user); db.flush()
    acct = models.Account(user_id=user.id, name="Chk", type=models.AccountType.checking,
                          current_balance=Decimal("10000.00"))
    db.add(acct); db.flush()
    item = models.RecurringItem(
        user_id=user.id, account_id=acct.id, name="Duke Electric",
        amount=Decimal(amount), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=day,
        start_date=date(2026, 1, 1), is_active=True, include_in_forecast=True,
    )
    db.add(item); db.commit()
    return user, acct, item


def _next_due(day: int = 8) -> date:
    """The next occurrence of day-of-month `day` strictly after today, so an
    override due date is always in the future regardless of which real day
    this test happens to run on -- same technique as _RelativeCardCycles in
    test_forecast_spreadsheet_gaps_20260814.py. A hardcoded 2026-09-08 rotted
    here once wall-clock time passed it: build_forecast(..., date.today(),
    ...) starts its window at today, so a due date already in the past never
    appears in it, and GET /bill-overrides's default upcoming_only filter
    drops it too.

    The NATURAL due date, the one an override is keyed by (the weekend
    rule): the Recurring page and the bill prompts store it, and the
    forecast moves only the day it posts. See _posts_on."""
    return _next_occurrence_on_or_after(day, date.today() + timedelta(days=1))


def _posts_on(due: date) -> date:
    """The day the forecast posts a bill due on `due`: a Saturday or Sunday
    due date moves to the Friday before it."""
    return _adjust_for_weekend(due)


def _amount_on(db, user, acct, target: date, name: str):
    rows = build_forecast(db, user.id, acct.id, date.today(), target + timedelta(days=1))
    for r in rows:
        if r.date != target:
            continue
        for tx in r.transactions:
            if getattr(tx, "name", "") == name:
                return tx.amount
    return None


def test_override_replaces_the_projected_amount_on_its_own_date(db_session):
    """the user's real case: Duke Electric modelled at $180.00/month, a statement
    due one month came in at $214.07."""
    user, acct, item = _seed(db_session)
    due = _next_due()
    db_session.add(models.BillAmountOverride(
        user_id=user.id, recurring_item_id=item.id,
        due_date=due, actual_amount=Decimal("214.07")))
    db_session.commit()

    assert _amount_on(db_session, user, acct, _posts_on(due), "Duke Electric") == Decimal("-214.07")


def test_other_months_keep_the_modelled_amount(db_session):
    """The override must not become the new normal -- overwriting the item
    itself would rewrite every future month to a single-occurrence figure."""
    user, acct, item = _seed(db_session)
    # Chained off the RAW (pre-weekend-adjustment) date, not `due` itself --
    # if the first occurrence had been pulled back a day or two, resuming
    # the search from its adjusted date could still land inside the same
    # month instead of rolling over to the next one.
    raw_due = _next_occurrence_on_or_after(8, date.today() + timedelta(days=1))
    due = raw_due
    next_month = _adjust_for_weekend(_next_occurrence_on_or_after(8, raw_due + timedelta(days=1)))
    db_session.add(models.BillAmountOverride(
        user_id=user.id, recurring_item_id=item.id,
        due_date=due, actual_amount=Decimal("214.07")))
    db_session.commit()

    assert _amount_on(db_session, user, acct, next_month, "Duke Electric") == Decimal("-180.00")
    assert item.amount == Decimal("180.00")


def test_upsert_restates_rather_than_conflicting(db_session):
    """A bill can be restated before it's paid, and correcting a typo should
    not require delete-then-recreate."""
    user, acct, item = _seed(db_session)
    c = _client(db_session, user)
    payload = {"recurring_item_id": item.id, "due_date": _next_due().isoformat(), "actual_amount": "214.07"}

    first = c.post("/bill-overrides", json=payload)
    assert first.status_code == 201
    payload["actual_amount"] = "231.05"
    second = c.post("/bill-overrides", json=payload)
    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]
    assert Decimal(second.json()["actual_amount"]) == Decimal("231.05")
    assert len(c.get("/bill-overrides").json()) == 1


def test_response_carries_the_projection_for_comparison(db_session):
    """Comparing actual against projected is the whole point, so the variance
    must be computable without a second round trip."""
    user, acct, item = _seed(db_session)
    c = _client(db_session, user)
    r = c.post("/bill-overrides", json={
        "recurring_item_id": item.id, "due_date": _next_due().isoformat(), "actual_amount": "214.07"}).json()

    assert Decimal(r["projected_amount"]) == Decimal("180.00")
    assert Decimal(r["actual_amount"]) == Decimal("214.07")
    assert r["recurring_item_name"] == "Duke Electric"


def test_deleting_an_override_restores_the_projection(db_session):
    user, acct, item = _seed(db_session)
    c = _client(db_session, user)
    due = _next_due()
    created = c.post("/bill-overrides", json={
        "recurring_item_id": item.id, "due_date": due.isoformat(), "actual_amount": "214.07"}).json()
    assert _amount_on(db_session, user, acct, _posts_on(due), "Duke Electric") == Decimal("-214.07")

    assert c.delete(f"/bill-overrides/{created['id']}").status_code == 204
    assert _amount_on(db_session, user, acct, _posts_on(due), "Duke Electric") == Decimal("-180.00")


def test_cannot_override_another_users_bill(db_session):
    user, acct, item = _seed(db_session)
    other = models.User(username="o2", hashed_password="x", display_name="O")
    db_session.add(other); db_session.commit()

    r = _client(db_session, other).post("/bill-overrides", json={
        "recurring_item_id": item.id, "due_date": _next_due().isoformat(), "actual_amount": "1.00"})
    assert r.status_code == 404


def test_past_due_dates_are_hidden_from_the_upcoming_list(db_session):
    """Once the date passes the real transaction is in the ledger and the
    forecast no longer projects that day, so the record is just history."""
    user, acct, item = _seed(db_session)
    db_session.add_all([
        models.BillAmountOverride(user_id=user.id, recurring_item_id=item.id,
                                  due_date=date.today() - timedelta(days=30),
                                  actual_amount=Decimal("100.00")),
        models.BillAmountOverride(user_id=user.id, recurring_item_id=item.id,
                                  due_date=date.today() + timedelta(days=10),
                                  actual_amount=Decimal("214.07")),
    ])
    db_session.commit()
    c = _client(db_session, user)

    assert len(c.get("/bill-overrides").json()) == 1
    assert len(c.get("/bill-overrides", params={"upcoming_only": False}).json()) == 2
