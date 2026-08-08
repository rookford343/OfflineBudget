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
