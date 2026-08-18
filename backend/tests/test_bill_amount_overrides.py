from datetime import date, timedelta
from decimal import Decimal
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.dependencies import get_db, get_current_user
from backend.routers import bill_overrides as bill_overrides_router_module
from backend.services.forecast_engine import build_forecast


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
    """Dan's real case: Duke Electric modelled at $180.00/month, the statement
    due 2026-09-08 is $224.31."""
    user, acct, item = _seed(db_session)
    due = date(2026, 9, 8)
    db_session.add(models.BillAmountOverride(
        user_id=user.id, recurring_item_id=item.id,
        due_date=due, actual_amount=Decimal("224.31")))
    db_session.commit()

    assert _amount_on(db_session, user, acct, due, "Duke Electric") == Decimal("-224.31")


def test_other_months_keep_the_modelled_amount(db_session):
    """The override must not become the new normal -- overwriting the item
    itself would rewrite every future month to a September-only figure."""
    user, acct, item = _seed(db_session)
    db_session.add(models.BillAmountOverride(
        user_id=user.id, recurring_item_id=item.id,
        due_date=date(2026, 9, 8), actual_amount=Decimal("224.31")))
    db_session.commit()

    assert _amount_on(db_session, user, acct, date(2026, 10, 8), "Duke Electric") == Decimal("-180.00")
    assert item.amount == Decimal("180.00")


def test_upsert_restates_rather_than_conflicting(db_session):
    """A bill can be restated before it's paid, and correcting a typo should
    not require delete-then-recreate."""
    user, acct, item = _seed(db_session)
    c = _client(db_session, user)
    payload = {"recurring_item_id": item.id, "due_date": "2026-09-08", "actual_amount": "224.31"}

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
        "recurring_item_id": item.id, "due_date": "2026-09-08", "actual_amount": "224.31"}).json()

    assert Decimal(r["projected_amount"]) == Decimal("180.00")
    assert Decimal(r["actual_amount"]) == Decimal("224.31")
    assert r["recurring_item_name"] == "Duke Electric"


def test_deleting_an_override_restores_the_projection(db_session):
    user, acct, item = _seed(db_session)
    c = _client(db_session, user)
    due = date(2026, 9, 8)
    created = c.post("/bill-overrides", json={
        "recurring_item_id": item.id, "due_date": "2026-09-08", "actual_amount": "224.31"}).json()
    assert _amount_on(db_session, user, acct, due, "Duke Electric") == Decimal("-224.31")

    assert c.delete(f"/bill-overrides/{created['id']}").status_code == 204
    assert _amount_on(db_session, user, acct, due, "Duke Electric") == Decimal("-180.00")


def test_cannot_override_another_users_bill(db_session):
    user, acct, item = _seed(db_session)
    other = models.User(username="o2", hashed_password="x", display_name="O")
    db_session.add(other); db_session.commit()

    r = _client(db_session, other).post("/bill-overrides", json={
        "recurring_item_id": item.id, "due_date": "2026-09-08", "actual_amount": "1.00"})
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
                                  actual_amount=Decimal("224.31")),
    ])
    db_session.commit()
    c = _client(db_session, user)

    assert len(c.get("/bill-overrides").json()) == 1
    assert len(c.get("/bill-overrides", params={"upcoming_only": False}).json()) == 2
