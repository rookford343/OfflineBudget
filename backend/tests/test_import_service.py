from datetime import date
from decimal import Decimal
from backend import models, schemas
from backend.services.import_service import run_import


def _make_user_and_card(db):
    user = models.User(username="t", hashed_password="x", display_name="T")
    db.add(user)
    db.flush()
    card = models.CreditCard(
        user_id=user.id, name="Visa", credit_limit=Decimal("5000.00"),
        statement_day=15, due_day=1, current_balance=Decimal("100.00"),
    )
    db.add(card)
    db.flush()
    return user, card


def test_card_sale_increases_balance(db_session):
    user, card = _make_user_and_card(db_session)
    rows = [schemas.ImportConfirmRow(date=date(2026, 8, 4), description="Meijer", amount=Decimal("-52.90"))]

    run_import(db_session, user, rows, account_id=None, card_id=card.id)

    assert card.current_balance == Decimal("152.90")


def test_card_return_decreases_balance(db_session):
    user, card = _make_user_and_card(db_session)
    rows = [schemas.ImportConfirmRow(date=date(2026, 8, 3), description="Ozwell Return", amount=Decimal("25.00"))]

    run_import(db_session, user, rows, account_id=None, card_id=card.id)

    assert card.current_balance == Decimal("75.00")


def test_checking_autopay_reduces_matching_card_balance(db_session):
    """A checking-side CC autopay debit should reduce the matching card's
    balance, even though the real bank description ("CHASE CREDIT CRD
    AUTOPAY") never contains the card's full display name ("Chase Sapphire")
    verbatim -- only the issuer name in common."""
    user, card = _make_user_and_card(db_session)
    card.name = "Chase Sapphire"
    checking = models.Account(user_id=user.id, name="Main Checking", type=models.AccountType.checking, current_balance=Decimal("5000.00"))
    db_session.add(checking)
    db_session.flush()

    rows = [schemas.ImportConfirmRow(
        date=date(2026, 7, 27), description="CHASE CREDIT CRD AUTOPAY PPD ID: 4760039224",
        amount=Decimal("-11312.54"), is_transfer=True,
    )]

    run_import(db_session, user, rows, account_id=checking.id, card_id=None)

    assert card.current_balance == Decimal("0.00")  # 100.00 - 11312.54, floored at 0
