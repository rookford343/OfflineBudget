from datetime import date
from decimal import Decimal
from backend import models, schemas
from backend.services.import_service import run_import


def _rows():
    return [
        schemas.ImportConfirmRow(date=date(2026, 1, 5), description="DEPOSIT",
                                 amount=Decimal("500.00"), category_id=None, is_transfer=False),
        schemas.ImportConfirmRow(date=date(2026, 1, 9), description="WITHDRAWAL",
                                 amount=Decimal("-200.00"), category_id=None, is_transfer=False),
    ]


def _user(db, name):
    u = models.User(username=name, hashed_password="x", display_name=name)
    db.add(u); db.flush()
    return u


def test_manual_account_balance_still_moves_with_an_import(db_session):
    """An account the app tracks by arithmetic has no other source of truth."""
    u = _user(db_session, "m1")
    acct = models.Account(user_id=u.id, name="Manual", type=models.AccountType.savings,
                          current_balance=Decimal("1000.00"))
    db_session.add(acct); db_session.commit()

    run_import(db_session, u, _rows(), account_id=acct.id, card_id=None)
    db_session.refresh(acct)
    assert acct.current_balance == Decimal("1300.00")


def test_bank_linked_account_balance_is_left_to_the_sync(db_session):
    """Backfilling statements onto a synced account double-counted every row,
    silently inflating the balance even though the rows were correct."""
    u = _user(db_session, "m2")
    acct = models.Account(user_id=u.id, name="Synced", type=models.AccountType.savings,
                          current_balance=Decimal("1000.00"))
    db_session.add(acct); db_session.flush()
    conn = models.BankConnection(user_id=u.id, access_url_encrypted="x",
                                 status=models.BankConnectionStatus.active)
    db_session.add(conn); db_session.flush()
    db_session.add(models.BankConnectionAccountLink(
        connection_id=conn.id, simplefin_account_id="ACT-1",
        simplefin_account_name="Synced", local_account_id=acct.id))
    db_session.commit()

    res = run_import(db_session, u, _rows(), account_id=acct.id, card_id=None)
    db_session.refresh(acct)
    assert res.imported == 2          # the history still lands
    assert acct.current_balance == Decimal("1000.00")   # the balance does not move


def test_another_users_link_does_not_shield_the_balance(db_session):
    """The guard must key on this user's connection, not any connection."""
    owner = _user(db_session, "m3")
    other = _user(db_session, "m4")
    acct = models.Account(user_id=owner.id, name="Manual", type=models.AccountType.savings,
                          current_balance=Decimal("1000.00"))
    db_session.add(acct); db_session.flush()
    conn = models.BankConnection(user_id=other.id, access_url_encrypted="x",
                                 status=models.BankConnectionStatus.active)
    db_session.add(conn); db_session.flush()
    db_session.add(models.BankConnectionAccountLink(
        connection_id=conn.id, simplefin_account_id="ACT-2",
        simplefin_account_name="Other", local_account_id=acct.id))
    db_session.commit()

    run_import(db_session, owner, _rows(), account_id=acct.id, card_id=None)
    db_session.refresh(acct)
    assert acct.current_balance == Decimal("1300.00")
