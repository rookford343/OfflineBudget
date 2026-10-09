"""Dashboard 'Recent transactions' card -- a newest-first merge of checking
+ card activity, built on the same exclusion predicates the Spending page
uses (filter_real_spend, is_card_payment). The two views must never
disagree about what counts as a transfer, a card payoff, or real spend.
"""
import pytest
from datetime import date
from decimal import Decimal
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.dependencies import get_db, get_current_user
from backend.routers import spending as spending_router_module
from backend.services.recent_activity import get_recent_activity


def _setup(db):
    user = models.User(username="dan", hashed_password="x", display_name="the user")
    db.add(user)
    db.flush()
    account = models.Account(user_id=user.id, name="Main Checking",
                              type=models.AccountType.checking, current_balance=Decimal("5000"))
    card = models.CreditCard(user_id=user.id, name="Chase Sapphire", credit_limit=Decimal("29000"),
                              statement_day=28, due_day=25, is_active=True)
    db.add_all([account, card])
    db.flush()
    return user, account, card


def _txn(db, user, account, desc, amount, when):
    t = models.Transaction(user_id=user.id, account_id=account.id, date=when,
                            amount=Decimal(amount), description=desc, is_actual=True)
    db.add(t)
    return t


def _card_txn(db, user, card, merchant, amount, when):
    t = models.CreditCardTransaction(user_id=user.id, card_id=card.id, date=when,
                                      amount=Decimal(amount), merchant=merchant)
    db.add(t)
    return t


def _client(db, user):
    app = FastAPI()
    app.include_router(spending_router_module.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


# --- Merge order -----------------------------------------------------------

def test_merge_order_newest_first_across_sources_with_tiebreak(db_session):
    user, account, card = _setup(db_session)
    # Bump the checking id sequence past the card id sequence first, so a
    # same-date row from each source has a well-defined (non-colliding) id
    # to tie-break on -- checking and card ids come from independent
    # sequences and would otherwise both start at 1.
    _txn(db_session, user, account, "Online Transfer to SAV", "-1.00", date(2020, 1, 1))
    db_session.flush()

    k1 = _card_txn(db_session, user, card, "COSTCO WHSE", "80.00", date(2026, 9, 20))
    db_session.flush()
    c1 = _txn(db_session, user, account, "KROGER #5001", "-50.00", date(2026, 9, 20))
    db_session.flush()
    older = _txn(db_session, user, account, "TARGET", "-30.00", date(2026, 9, 18))
    db_session.commit()

    rows = get_recent_activity(db_session, user.id, limit=10)

    assert [r.uid for r in rows] == [f"checking-{c1.id}", f"card-{k1.id}", f"checking-{older.id}"]


# --- Exclusions --------------------------------------------------------

def test_transfer_excluded_both_directions(db_session):
    user, account, card = _setup(db_session)
    _txn(db_session, user, account, "Online Transfer to SAV ...XXXX0000", "-500.00", date(2026, 9, 20))
    _txn(db_session, user, account, "Online Transfer from SAV ...XXXX0000", "500.00", date(2026, 9, 19))
    kept = _txn(db_session, user, account, "KROGER #5001", "-50.00", date(2026, 9, 18))
    db_session.commit()

    rows = get_recent_activity(db_session, user.id, limit=10)

    assert [r.uid for r in rows] == [f"checking-{kept.id}"]


def test_card_payoff_excluded(db_session):
    user, account, card = _setup(db_session)
    _card_txn(db_session, user, card, "AUTOMATIC PAYMENT - THANK", "1074.64", date(2026, 9, 20))
    kept = _card_txn(db_session, user, card, "COSTCO WHSE", "80.00", date(2026, 9, 19))
    db_session.commit()

    rows = get_recent_activity(db_session, user.id, limit=10)

    assert [r.uid for r in rows] == [f"card-{kept.id}"]


def test_savings_account_row_excluded(db_session):
    """Bank sync writes rows for every linked account, not just checking --
    a savings/money-market row is real activity on that account but out of
    scope for this feed, which is checking + card only."""
    user, account, card = _setup(db_session)
    savings = models.Account(user_id=user.id, name="Savings", type=models.AccountType.savings,
                              current_balance=Decimal("1000"))
    db_session.add(savings)
    db_session.flush()
    _txn(db_session, user, savings, "Interest paid", "5.00", date(2026, 9, 20))
    kept = _txn(db_session, user, account, "KROGER #5001", "-50.00", date(2026, 9, 19))
    db_session.commit()

    rows = get_recent_activity(db_session, user.id, limit=10)

    assert [r.uid for r in rows] == [f"checking-{kept.id}"]


# --- Signs ---------------------------------------------------------------

def test_income_is_included_and_positive(db_session):
    user, account, card = _setup(db_session)
    _txn(db_session, user, account, "ACME CORP PAYROLL", "2500.00", date(2026, 9, 20))
    db_session.commit()

    rows = get_recent_activity(db_session, user.id, limit=10)

    assert len(rows) == 1
    assert rows[0].amount == Decimal("2500.00")
    assert rows[0].source == "checking"


def test_card_charges_come_out_negative(db_session):
    user, account, card = _setup(db_session)
    _card_txn(db_session, user, card, "COSTCO WHSE", "80.00", date(2026, 9, 20))
    db_session.commit()

    rows = get_recent_activity(db_session, user.id, limit=10)

    assert len(rows) == 1
    assert rows[0].amount == Decimal("-80.00")
    assert rows[0].source == "card"


def test_zero_amount_card_row_is_not_negative_zero(db_session):
    """-Decimal("0.00") == Decimal("0.00") but prints as "-0.00" -- a $0
    card row (e.g. an authorization hold that settled at $0) must come out
    as a plain zero, not a negative-looking one the frontend would render
    with a spurious sign."""
    user, account, card = _setup(db_session)
    _card_txn(db_session, user, card, "ZERO DOLLAR AUTH", "0.00", date(2026, 9, 20))
    db_session.commit()

    rows = get_recent_activity(db_session, user.id, limit=10)

    assert len(rows) == 1
    assert rows[0].amount == Decimal("0")
    assert not rows[0].amount.is_signed(), f"expected a non-negative zero, got {rows[0].amount!r}"


# --- Limit / candidate over-fetch -----------------------------------------

def test_limit_respected_even_when_many_rows_excluded(db_session):
    user, account, card = _setup(db_session)
    # 10 transfers at the NEWEST dates, 5 real purchases just older -- exactly
    # fills limit*3 (5*3=15) candidates. A fetch window that isn't wide
    # enough (e.g. just `limit` candidates) would see only transfers and
    # starve the list below the requested 5.
    for i in range(10):
        _txn(db_session, user, account, "Online Transfer to SAV", "-10.00", date(2026, 9, 11 + i))
    for i in range(5):
        _txn(db_session, user, account, f"KROGER #{5000 + i}", "-20.00", date(2026, 9, 6 + i))
    db_session.commit()

    rows = get_recent_activity(db_session, user.id, limit=5)

    assert len(rows) == 5
    assert all(r.description == "Kroger" for r in rows)


# --- User scoping ----------------------------------------------------------

def test_only_current_user_rows_appear(db_session):
    user, account, card = _setup(db_session)
    other = models.User(username="other", hashed_password="x", display_name="Other")
    db_session.add(other)
    db_session.flush()
    other_account = models.Account(user_id=other.id, name="Other Checking",
                                    type=models.AccountType.checking, current_balance=Decimal("100"))
    db_session.add(other_account)
    db_session.flush()
    _txn(db_session, other, other_account, "OTHER USER SPEND", "-40.00", date(2026, 9, 20))
    mine = _txn(db_session, user, account, "KROGER #5001", "-50.00", date(2026, 9, 19))
    db_session.commit()

    rows = get_recent_activity(db_session, user.id, limit=10)

    assert [r.uid for r in rows] == [f"checking-{mine.id}"]


# --- Endpoint --------------------------------------------------------------

def test_endpoint_returns_200(db_session):
    user, account, card = _setup(db_session)
    _txn(db_session, user, account, "KROGER #5001", "-50.00", date(2026, 9, 20))
    db_session.commit()

    c = _client(db_session, user)
    resp = c.get("/spending/recent")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["source"] == "checking"


@pytest.mark.parametrize("limit", [pytest.param(0, id="zero"), pytest.param(51, id="too_high")])
def test_endpoint_422_limit_out_of_range(db_session, limit):
    user, account, card = _setup(db_session)
    db_session.commit()
    c = _client(db_session, user)

    resp = c.get("/spending/recent", params={"limit": limit})

    assert resp.status_code == 422

