"""POST /planned-expenses/preview: what a one-off does to the Safety Margin,
computed by the same snapshot the Dashboard reads, writing nothing.

All figures are invented; the repo is public."""
from datetime import date, timedelta
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import models
from backend.dependencies import get_current_user, get_db
from backend.routers import planned_expenses as pe_router
from backend.services.budget_snapshot import compute_budget_snapshot
from backend.services.card_payment_model import card_payment_plan
from backend.services.forecast_engine import build_forecast


def _next_25th() -> date:
    today = date.today()
    d = today.replace(day=25)
    return d if d >= today else (d.replace(day=1) + timedelta(days=32)).replace(day=25)


def _seed(db):
    user = models.User(username="preview", hashed_password="x", display_name="Preview")
    db.add(user)
    db.flush()
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("5000.00"),
    )
    card = models.CreditCard(
        user_id=user.id, name="Chase Sapphire", credit_limit=Decimal("27500.00"),
        statement_day=28, due_day=25, balance_due=Decimal("500.00"),
        current_balance=Decimal("800.00"), monthly_spend_estimate=Decimal("1000.00"),
        next_payment_date=_next_25th(),
    )
    db.add_all([account, card])
    db.flush()
    db.add(models.RecurringItem(
        user_id=user.id, account_id=account.id, name="Rent", amount=Decimal("1200.00"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=1, start_date=date(2026, 1, 1),
    ))
    db.commit()
    return user, account, card


def _client(db, user):
    app = FastAPI()
    app.include_router(pe_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _body(account, card=None):
    body = {
        "name": "Trip", "amount": "600.00",
        "expected_date": (date.today() + timedelta(days=20)).isoformat(),
    }
    if card is not None:
        body["card_id"] = card.id
    else:
        body["account_id"] = account.id
    return body


def _count(db):
    return db.query(models.PlannedExpense).count()


def _dec(v):
    return Decimal(str(v))


def test_preview_writes_nothing(db_session):
    user, account, _ = _seed(db_session)
    client = _client(db_session, user)
    before = _count(db_session)
    r = client.post(f"/planned-expenses/preview?account_id={account.id}", json=_body(account))
    assert r.status_code == 200, r.text
    assert _count(db_session) == before
    assert not db_session.new and not db_session.dirty


def test_preview_matches_commit__checking(db_session):
    user, account, _ = _seed(db_session)
    client = _client(db_session, user)
    base = compute_budget_snapshot(db_session, user, account.id)
    r = client.post(f"/planned-expenses/preview?account_id={account.id}", json=_body(account))
    assert r.status_code == 200, r.text
    out = r.json()
    assert client.post("/planned-expenses", json=_body(account)).status_code == 201
    after = compute_budget_snapshot(db_session, user, account.id)
    assert _dec(out["safety_margin_weekly"]["before"]) == base.safety_margin_weekly
    assert _dec(out["safety_margin"]["before"]) == base.safety_margin
    assert _dec(out["safety_margin_weekly"]["after"]) == after.safety_margin_weekly
    assert _dec(out["safety_margin"]["after"]) == after.safety_margin
    assert out["card_payment"] is None


def test_preview_matches_commit__card(db_session):
    user, account, card = _seed(db_session)
    client = _client(db_session, user)
    base = compute_budget_snapshot(db_session, user, account.id)
    body = _body(account, card)
    r = client.post(f"/planned-expenses/preview?account_id={account.id}", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert client.post("/planned-expenses", json=body).status_code == 201
    after = compute_budget_snapshot(db_session, user, account.id)
    assert _dec(out["safety_margin_weekly"]["before"]) == base.safety_margin_weekly
    assert _dec(out["safety_margin_weekly"]["after"]) == after.safety_margin_weekly
    assert _dec(out["safety_margin"]["after"]) == after.safety_margin

    cp = out["card_payment"]
    assert cp["card_id"] == card.id
    assert _dec(cp["after"]) - _dec(cp["before"]) == Decimal("600.00")
    assert _dec(cp["delta"]) == Decimal("600.00")
    # The payoff leaving checking on cp["due"] in the real forecast, after commit.
    expected = date.fromisoformat(body["expected_date"])
    entries = build_forecast(db_session, user.id, account.id, date.today(), expected + timedelta(days=70))
    due = date.fromisoformat(cp["due"])
    names = [t.name for e in entries if e.date == due for t in e.transactions]
    assert "Trip (via Chase Sapphire)" in names
    plan = card_payment_plan(
        db_session, user, account, date.today(), expected + timedelta(days=70),
        include_unbilled_card_bills=True,
    )
    modelled = sum((p.amount for p in plan.payments if p.card_id == card.id and p.due == due), Decimal("0"))
    assert _dec(cp["after"]) == modelled + Decimal("600.00")
    assert _dec(cp["before"]) == modelled


def test_cancel_leaves_no_trace(db_session):
    user, account, card = _seed(db_session)
    client = _client(db_session, user)
    base = compute_budget_snapshot(db_session, user, account.id)
    rows = _count(db_session)
    for body in (_body(account), _body(account, card)):
        assert client.post(f"/planned-expenses/preview?account_id={account.id}", json=body).status_code == 200
    assert _count(db_session) == rows
    again = compute_budget_snapshot(db_session, user, account.id)
    assert again.safety_margin == base.safety_margin
    assert again.safety_margin_weekly == base.safety_margin_weekly


def test_preview_other_users_account_param_is_404(db_session):
    user, account, _ = _seed(db_session)
    other = models.User(username="other", hashed_password="x", display_name="O")
    db_session.add(other)
    db_session.commit()
    r = _client(db_session, other).post(
        f"/planned-expenses/preview?account_id={account.id}", json=_body(account))
    assert r.status_code == 404
