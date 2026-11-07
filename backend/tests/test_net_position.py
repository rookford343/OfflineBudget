"""Net Position and card cycle figures (services/net_position.py).

All figures are invented; the repo is public."""
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import models
from backend.dependencies import get_current_user, get_db
from backend.routers import accounts as accounts_router
from backend.routers import credit_cards as cards_router
from backend.services.explain import children_consistent, replay
from backend.services.net_position import card_cycle_figures, net_position

TODAY = date(2027, 3, 15)


def _user(db):
    user = models.User(username="npowner", hashed_password="x", display_name="the user")
    db.add(user)
    db.flush()
    return user


def _account(db, user, name, balance, kind=models.AccountType.checking, active=True):
    a = models.Account(user_id=user.id, name=name, type=kind,
                       current_balance=Decimal(balance), is_active=active)
    db.add(a)
    db.flush()
    return a


def _card(db, user, name="Card A", balance="500.00", due="200.00", pending="0", stamped=None):
    c = models.CreditCard(user_id=user.id, name=name, credit_limit=Decimal("5000"), statement_day=1,
                          due_day=20, current_balance=Decimal(balance), balance_due=Decimal(due),
                          pending_charges=Decimal(pending), pending_charges_updated_at=stamped)
    db.add(c)
    db.flush()
    return c


def test_net_position_and_explain_replay(db_session):
    user = _user(db_session)
    _account(db_session, user, "Main", "1500.00")
    _account(db_session, user, "Second", "250.50")
    _account(db_session, user, "Savings", "9999.00", kind=models.AccountType.savings)
    _account(db_session, user, "Closed", "777.00", active=False)
    _card(db_session, user, "Card A", due="200.00")
    _card(db_session, user, "Card B", due="75.25")
    out = net_position(db_session, user.id)
    assert out.checking_total == Decimal("1750.50")
    assert out.cards_due_total == Decimal("275.25")
    assert out.net_position == Decimal("1475.25")
    assert replay(out.explain) == out.net_position
    assert children_consistent(out.explain)
    start, sub = out.explain.rows[0], out.explain.rows[1]
    assert [c.label for c in start.children] == ["Main", "Second"]
    assert [c.label for c in sub.children] == ["Card A", "Card B"]


def test_net_position_with_nothing_is_zero(db_session):
    user = _user(db_session)
    out = net_position(db_session, user.id)
    assert out.net_position == Decimal("0")
    assert replay(out.explain) == Decimal("0")


def test_spent_this_cycle_uses_card_pending(db_session):
    user = _user(db_session)
    card = _card(db_session, user, balance="500.00", due="200.00", pending="40.00",
                 stamped=datetime(2027, 3, 14))
    pending, spent, after = card_cycle_figures(card, TODAY)
    assert pending == Decimal("40.00")
    assert spent == Decimal("340.00")
    assert after == Decimal("540.00")


def test_issuer_pending_rows_win_over_hand_typed(db_session):
    user = _user(db_session)
    card = _card(db_session, user, balance="500.00", due="200.00", pending="40.00",
                 stamped=datetime(2027, 3, 14))
    db_session.add(models.CardPendingTransaction(
        user_id=user.id, card_id=card.id, external_id="p1", date=TODAY,
        amount=Decimal("10.00"), merchant="pending", synced_at=datetime(2027, 3, 15)))
    db_session.flush()
    pending, spent, after = card_cycle_figures(card, TODAY)
    assert (pending, spent, after) == (Decimal("10.00"), Decimal("310.00"), Decimal("510.00"))


def test_stale_hand_typed_pending_ignored_in_cycle_figures(db_session):
    user = _user(db_session)
    card = _card(db_session, user, balance="500.00", due="200.00", pending="40.00",
                 stamped=datetime(2027, 3, 7))  # 8 days before TODAY
    pending, spent, after = card_cycle_figures(card, TODAY)
    assert pending == Decimal("0")
    assert spent == Decimal("300.00")
    assert after == Decimal("500.00")


def test_spent_this_cycle_floors_at_zero(db_session):
    user = _user(db_session)
    card = _card(db_session, user, balance="100.00", due="250.00")
    _, spent, after = card_cycle_figures(card, TODAY)
    assert spent == Decimal("0")
    assert after == Decimal("100.00")


def test_endpoints_expose_the_figures(db_session):
    user = _user(db_session)
    _account(db_session, user, "Main", "1000.00")
    # Stamped now so the 7-day freshness rule holds whatever today is.
    _card(db_session, user, balance="500.00", due="200.00", pending="40.00", stamped=datetime.now())
    app = FastAPI()
    app.include_router(accounts_router.router)
    app.include_router(cards_router.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(app)
    body = client.get("/accounts/net-position").json()
    assert set(body) == {"checking_total", "cards_due_total", "net_position", "explain"}
    assert Decimal(body["net_position"]) == Decimal("800.00")
    row = client.get("/credit-cards").json()[0]
    assert Decimal(row["pending_charges"]) == Decimal("40.00")
    assert Decimal(row["pending_effective"]) == Decimal("40.00")
    assert Decimal(row["spent_this_cycle"]) == Decimal("340.00")
    assert Decimal(row["after_pending"]) == Decimal("540.00")
    stale = db_session.query(models.CreditCard).one()
    stale.pending_charges_updated_at = datetime.now() - timedelta(days=8)
    db_session.flush()
    row = client.get("/credit-cards").json()[0]
    assert Decimal(row["pending_charges"]) == Decimal("40.00")  # raw stays for the edit form
    assert Decimal(row["pending_effective"]) == Decimal("0")
    assert Decimal(row["spent_this_cycle"]) == Decimal("300.00")


def test_explicit_pending_save_restamps_even_when_unchanged(db_session):
    user = _user(db_session)
    stale = datetime.now() - timedelta(days=8)
    card = _card(db_session, user, pending="40.00", stamped=stale)
    app = FastAPI()
    app.include_router(cards_router.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(app)
    assert Decimal(client.get(f"/credit-cards/{card.id}").json()["pending_effective"]) == Decimal("0")
    row = client.patch(f"/credit-cards/{card.id}", json={"pending_charges": 40}).json()
    assert Decimal(row["pending_effective"]) == Decimal("40.00")
    assert Decimal(row["spent_this_cycle"]) == Decimal("340.00")
    # An unrelated edit leaves the stamp alone; saving zero clears it.
    db_session.refresh(card)
    stamp = card.pending_charges_updated_at
    client.patch(f"/credit-cards/{card.id}", json={"notes": "x"})
    db_session.refresh(card)
    assert card.pending_charges_updated_at == stamp
    client.patch(f"/credit-cards/{card.id}", json={"pending_charges": 0})
    db_session.refresh(card)
    assert card.pending_charges_updated_at is None
