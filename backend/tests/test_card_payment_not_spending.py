"""A payment settling a credit card is not spending.

Paying the card moves money between accounts. The charges being settled were
already counted one by one, so counting the payment as well double-counts the
whole statement.

These rows arrive on the charge side (positive amount) rather than netting out
like a refund. Found live 2026-08-12: one "AUTOMATIC PAYMENT - THANK" row of
$11,312.54 was the single largest line in Dan's card spending and the top entry
in the weekly email his wife reads. The checking-side mirror image was already
excluded via card_matching.card_matches_description; this pins the card side.
"""
from datetime import date
from decimal import Decimal
import pytest
from backend import models
from backend.services.spending_helpers import (
    category_totals_for_range, is_card_payment, merchant_totals,
)
from backend.services.spendable_pacer import discretionary_spend_card


@pytest.mark.parametrize("merchant", [
    "AUTOMATIC PAYMENT - THANK",
    "AUTOMATIC PAYMENT - THANK YOU",
    "Autopay Payment",
    "ONLINE PAYMENT FROM CHK 1234",
    "MOBILE PAYMENT - THANK YOU",
    "ELECTRONIC PAYMENT RECEIVED",
])
def test_recognises_payment_merchants(merchant):
    assert is_card_payment(merchant)


@pytest.mark.parametrize("merchant", [
    "MINDBODY PAYMENTS",      # a real gym charge in Dan's live data
    "PAYPAL *BLISS DIAMO",
    "PAYMENTS PLUS SALON",
    "TARGET T-1063",
    None,
    "",
])
def test_does_not_catch_real_merchants(merchant):
    assert not is_card_payment(merchant)


def _seed(db):
    user = models.User(username="cardpay", hashed_password="x", display_name="CardPay")
    db.add(user)
    db.flush()
    card = models.CreditCard(
        user_id=user.id, name="Chase Sapphire", credit_limit=Decimal("29000.00"),
        statement_day=28, due_day=25,
    )
    db.add(card)
    db.flush()
    db.add_all([
        models.CreditCardTransaction(
            card_id=card.id, user_id=user.id, date=date(2026, 7, 20),
            amount=Decimal("120.00"), merchant="MEIJER STORE #130",
        ),
        models.CreditCardTransaction(
            card_id=card.id, user_id=user.id, date=date(2026, 7, 24),
            amount=Decimal("11312.54"), merchant="AUTOMATIC PAYMENT - THANK",
        ),
    ])
    db.commit()
    return user, card


def test_payment_excluded_from_category_totals(db_session):
    user, _ = _seed(db_session)

    totals = category_totals_for_range(db_session, user.id, date(2026, 7, 1), date(2026, 7, 31))

    assert sum(totals.values()) == Decimal("120.00"), (
        "the $11,312.54 payment must not appear as spending"
    )


def test_payment_excluded_from_top_merchants(db_session):
    user, _ = _seed(db_session)

    merchants = merchant_totals(db_session, user.id, date(2026, 7, 1), date(2026, 7, 31))
    names = [name for name, _, _ in merchants]

    assert "AUTOMATIC PAYMENT - THANK" not in names
    assert names == ["Meijer"]  # normalized from "MEIJER STORE #130" (2026-08-15)


def test_payment_excluded_from_discretionary_spend(db_session):
    """This is the number behind "Spendable this week" -- an $11k payment
    counted as spend would show the household wildly over pace."""
    user, _ = _seed(db_session)

    spend = discretionary_spend_card(db_session, user.id, date(2026, 7, 1), date(2026, 7, 31))

    assert spend == Decimal("120.00")


def test_a_real_refund_still_nets(db_session):
    """The payment filter must not disturb refund netting."""
    user, card = _seed(db_session)
    db_session.add(models.CreditCardTransaction(
        card_id=card.id, user_id=user.id, date=date(2026, 7, 22),
        amount=Decimal("-20.00"), merchant="MEIJER STORE #130",
    ))
    db_session.commit()

    spend = discretionary_spend_card(db_session, user.id, date(2026, 7, 1), date(2026, 7, 31))

    assert spend == Decimal("100.00")
