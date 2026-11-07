"""POST /planned-expenses/preview: what a one-off does to the Safety Margin,
computed by the same snapshot the Dashboard reads, writing nothing.

The seed has income on the 1st and 15th and a bill, so a one-off near today
really lowers the window's low point; each equality test also asserts that the
margin moved, so a preview that ignored the draft could not pass.

All figures are invented; the repo is public."""
import logging
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import models
from backend.dependencies import get_current_user, get_db
from backend.routers import planned_expenses as pe_router
from backend.services.budget_snapshot import compute_budget_snapshot
from backend.services.forecast_engine import build_forecast


def _next_25th() -> date:
    today = date.today()
    d = today.replace(day=25)
    return d if d >= today else (d.replace(day=1) + timedelta(days=32)).replace(day=25)


def _recurring(db, user, account, name, amount, kind, day):
    db.add(models.RecurringItem(
        user_id=user.id, account_id=account.id, name=name, amount=Decimal(amount), type=kind,
        frequency=models.RecurringFrequency.monthly, day_of_month=day, start_date=date(2026, 1, 1),
    ))


def _seed(db):
    user = models.User(username="preview", hashed_password="x", display_name="Preview")
    db.add(user)
    db.flush()
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("5000.00"),
    )
    second = models.Account(
        user_id=user.id, name="Second checking", type=models.AccountType.checking,
        current_balance=Decimal("3000.00"),
    )
    card = models.CreditCard(
        user_id=user.id, name="Chase Sapphire", credit_limit=Decimal("27500.00"),
        statement_day=28, due_day=25, balance_due=Decimal("500.00"),
        current_balance=Decimal("800.00"), monthly_spend_estimate=Decimal("1000.00"),
        next_payment_date=_next_25th(),
    )
    db.add_all([account, second, card])
    db.flush()
    for acct in (account, second):
        _recurring(db, user, acct, "Rent", "1200.00", models.RecurringType.expense, 1)
        _recurring(db, user, acct, "Pay one", "1000.00", models.RecurringType.income, 1)
        _recurring(db, user, acct, "Pay two", "1000.00", models.RecurringType.income, 15)
    _recurring(db, user, account, "Utilities", "900.00", models.RecurringType.expense, 28)
    db.commit()
    return user, account, second, card


def _client(db, user):
    app = FastAPI()
    app.include_router(pe_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _body(account=None, card=None, days=1, amount="2000.00"):
    body = {"name": "Trip", "amount": amount,
            "expected_date": (date.today() + timedelta(days=days)).isoformat()}
    if card is not None:
        body["card_id"] = card.id
    elif account is not None:
        body["account_id"] = account.id
    return body


def _count(db):
    return db.query(models.PlannedExpense).count()


def _dec(v):
    return Decimal(str(v))


def _preview(client, account, body):
    r = client.post(f"/planned-expenses/preview?account_id={account.id}", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _assert_matches_commit(db, client, user, account, body):
    base = compute_budget_snapshot(db, user, account.id)
    out = _preview(client, account, body)
    assert client.post("/planned-expenses", json=body).status_code == 201
    after = compute_budget_snapshot(db, user, account.id)
    for key in ("safety_margin_weekly", "safety_margin"):
        assert _dec(out[key]["before"]) == getattr(base, key)
        assert _dec(out[key]["after"]) == getattr(after, key)
        assert _dec(out[key]["after"]) < _dec(out[key]["before"]), f"{key} did not move"
    return out


def test_preview_writes_nothing(db_session, caplog):
    user, account, _, card = _seed(db_session)
    client = _client(db_session, user)
    before = _count(db_session)
    real_flush = db_session.flush
    pending_at_flush = []

    def spy_flush(*a, **kw):
        # Autoflush runs before every query; it must always find nothing pending.
        pending_at_flush.append(bool(db_session.new or db_session.dirty or db_session.deleted))
        return real_flush(*a, **kw)

    with caplog.at_level(logging.WARNING), \
            patch.object(db_session, "add") as add, patch.object(db_session, "flush", spy_flush), \
            patch.object(db_session, "rollback") as rollback:
        _preview(client, account, _body(account))
        _preview(client, account, _body(card=card))
    assert not add.called and not rollback.called
    assert pending_at_flush and not any(pending_at_flush)
    assert "rolling back" not in caplog.text
    assert _count(db_session) == before
    assert not db_session.new and not db_session.dirty


def test_preview_matches_commit__checking(db_session):
    user, account, _, _ = _seed(db_session)
    out = _assert_matches_commit(db_session, _client(db_session, user), user, account, _body(account))
    assert out["card_payment"] is None


def test_preview_matches_commit__card(db_session):
    user, account, _, card = _seed(db_session)
    client = _client(db_session, user)
    body = _body(card=card, days=1)
    out = _assert_matches_commit(db_session, client, user, account, body)

    cp = out["card_payment"]
    assert cp["card_id"] == card.id
    assert _dec(cp["amount"]) == Decimal("2000.00")
    # `due` is the date of the draft's "(via card)" line in the real forecast.
    entries = build_forecast(
        db_session, user.id, account.id, date.today(), date.today() + timedelta(days=90))
    line_dates = [e.date for e in entries for t in e.transactions if t.name == "Trip (via Chase Sapphire)"]
    assert line_dates == [date.fromisoformat(cp["due"])]


def test_preview_other_checking_account_moves_that_accounts_margin(db_session):
    user, account, second, _ = _seed(db_session)
    client = _client(db_session, user)
    body = _body(second)
    out = _assert_matches_commit(db_session, client, user, second, body)
    assert _dec(out["safety_margin"]["after"]) < _dec(out["safety_margin"]["before"])


def test_cancel_leaves_no_trace(db_session):
    user, account, _, card = _seed(db_session)
    client = _client(db_session, user)
    base = compute_budget_snapshot(db_session, user, account.id)
    rows = _count(db_session)
    for body in (_body(account), _body(card=card)):
        out = _preview(client, account, body)
        assert _dec(out["safety_margin"]["after"]) <= _dec(out["safety_margin"]["before"])
    moving = _preview(client, account, _body(account))
    assert _dec(moving["safety_margin"]["after"]) < _dec(moving["safety_margin"]["before"])
    assert _count(db_session) == rows
    again = compute_budget_snapshot(db_session, user, account.id)
    assert again.safety_margin == base.safety_margin
    assert again.safety_margin_weekly == base.safety_margin_weekly


def test_preview_other_users_account_param_is_404(db_session):
    user, account, _, _ = _seed(db_session)
    other = models.User(username="other", hashed_password="x", display_name="O")
    db_session.add(other)
    db_session.commit()
    r = _client(db_session, other).post(
        f"/planned-expenses/preview?account_id={account.id}", json=_body(account))
    assert r.status_code == 404
