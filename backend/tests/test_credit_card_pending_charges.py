from decimal import Decimal
from backend import models


def test_pending_charges_defaults_to_zero(db_session):
    user = models.User(username="t", hashed_password="x", display_name="T")
    db_session.add(user)
    db_session.flush()
    card = models.CreditCard(
        user_id=user.id, name="Visa", credit_limit=Decimal("5000.00"),
        statement_day=15, due_day=1,
    )
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)

    assert card.pending_charges == Decimal("0")


def test_pending_charges_persists_a_set_value(db_session):
    user = models.User(username="t2", hashed_password="x", display_name="T2")
    db_session.add(user)
    db_session.flush()
    card = models.CreditCard(
        user_id=user.id, name="Visa", credit_limit=Decimal("5000.00"),
        statement_day=15, due_day=1, pending_charges=Decimal("312.50"),
    )
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)

    assert card.pending_charges == Decimal("312.50")
