"""The one pending-charges accessor (services/pending.py).

Card pending is the issuer's synced rows when there are any, else a
hand-typed figure only while it is under 7 days old. Checking pending debits
come from the Plaid snapshot. All figures are invented; the repo is public.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal

from backend import models
from backend.services.pending import (
    PENDING_FRESH_DAYS,
    card_pending,
    checking_balance_with_pending,
    checking_pending_debits,
)

TODAY = date(2026, 3, 15)


def _user(db):
    user = models.User(username="pendingacc", hashed_password="x", display_name="PA")
    db.add(user)
    db.flush()
    return user


def _card(db, user, name="Chase Sapphire", pending="0", stamped=None):
    card = models.CreditCard(
        user_id=user.id, name=name, credit_limit=Decimal("5000.00"), statement_day=28, due_day=25,
        pending_charges=Decimal(pending), pending_charges_updated_at=stamped,
    )
    db.add(card)
    db.flush()
    return card


def _checking(db, user, balance="1000.00", link=True):
    acct = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal(balance),
    )
    db.add(acct)
    db.flush()
    if link:
        conn = models.BankConnection(
            user_id=user.id, provider="plaid", access_url_encrypted="tok", plaid_item_id="item-1",
        )
        db.add(conn)
        db.flush()
        db.add(models.BankConnectionAccountLink(
            connection_id=conn.id, simplefin_account_id="p-chk", simplefin_account_name="Checking",
            local_account_id=acct.id, is_active=True,
        ))
        db.flush()
    return acct


def _debit(db, user, acct, amount, description, ext):
    db.add(models.AccountPendingTransaction(
        user_id=user.id, account_id=acct.id, external_id=ext, date=TODAY,
        amount=Decimal(amount), description=description, synced_at=datetime(2026, 3, 15),
    ))
    db.flush()


def test_stale_hand_typed_pending_ignored(db_session):
    user = _user(db_session)
    stamped = datetime.combine(TODAY - timedelta(days=PENDING_FRESH_DAYS + 1), datetime.min.time())
    card = _card(db_session, user, pending="120.00", stamped=stamped)
    assert card_pending(card, TODAY) == Decimal("0")


def test_unstamped_hand_typed_pending_ignored(db_session):
    user = _user(db_session)
    assert card_pending(_card(db_session, user, pending="120.00"), TODAY) == Decimal("0")


def test_fresh_hand_typed_pending_used(db_session):
    user = _user(db_session)
    stamped = datetime.combine(TODAY - timedelta(days=PENDING_FRESH_DAYS), datetime.min.time())
    card = _card(db_session, user, pending="120.00", stamped=stamped)
    assert card_pending(card, TODAY) == Decimal("120.00")


def test_synced_rows_win_over_field(db_session):
    user = _user(db_session)
    stale = datetime.combine(TODAY - timedelta(days=30), datetime.min.time())
    card = _card(db_session, user, pending="999.00", stamped=stale)
    for i, amt in enumerate(("40.00", "25.50")):
        db_session.add(models.CardPendingTransaction(
            user_id=user.id, card_id=card.id, external_id=f"p{i}", date=TODAY,
            amount=Decimal(amt), merchant="Shop", synced_at=datetime(2026, 3, 15),
        ))
    db_session.flush()
    assert card_pending(card, TODAY) == Decimal("65.50")


def test_synced_card_with_no_rows_now_is_zero_not_stale_field(db_session):
    """After a sync clears the last pending row, replace_pending_snapshot
    writes 0 stamped now; the old hand-typed figure must not come back."""
    user = _user(db_session)
    card = _card(db_session, user, pending="0", stamped=datetime.combine(TODAY, datetime.min.time()))
    assert card_pending(card, TODAY) == Decimal("0")


def test_checking_pending_card_only_filter(db_session):
    user = _user(db_session)
    _card(db_session, user)
    acct = _checking(db_session, user)
    _debit(db_session, user, acct, "-300.00", "CHASE CREDIT CRD AUTOPAY 1234", "a")
    _debit(db_session, user, acct, "-40.00", "GROCERY MART 55", "b")
    _debit(db_session, user, acct, "50.00", "CHASE CREDIT CRD REFUND", "c")
    only = checking_pending_debits(db_session, acct, TODAY, card_payments_only=True)
    assert [r.external_id for r in only] == ["a"]
    every = checking_pending_debits(db_session, acct, TODAY, card_payments_only=False)
    assert [r.external_id for r in every] == ["a", "b"]


def test_checking_pending_ignored_without_live_plaid_link(db_session):
    user = _user(db_session)
    acct = _checking(db_session, user, link=False)
    _debit(db_session, user, acct, "-40.00", "GROCERY MART 55", "b")
    assert checking_pending_debits(db_session, acct, TODAY, card_payments_only=False) == []
    assert checking_balance_with_pending(db_session, acct, TODAY) == Decimal("1000.00")


def test_balance_with_pending_subtracts_all_debits(db_session):
    user = _user(db_session)
    _card(db_session, user)
    acct = _checking(db_session, user)
    _debit(db_session, user, acct, "-300.00", "CHASE CREDIT CRD AUTOPAY 1234", "a")
    _debit(db_session, user, acct, "-40.00", "GROCERY MART 55", "b")
    _debit(db_session, user, acct, "50.00", "REFUND", "c")
    assert checking_balance_with_pending(db_session, acct, TODAY) == Decimal("660.00")
