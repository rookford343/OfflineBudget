"""Tests for the shared bank-description -> credit-card matching heuristic.

This heuristic is used by forecast_engine.py (CC payoff suppression),
import_service.py (import-time card payment detection) and spendable_pacer.py
(excluding card payments from discretionary spend). The pacer use is the
highest-stakes one: a false positive there silently hides real spending.
"""
from decimal import Decimal

from backend import models
from backend.services.card_matching import card_matches_description


def _card(name: str, last_four: str | None = None) -> models.CreditCard:
    return models.CreditCard(
        user_id=1, name=name, last_four=last_four,
        credit_limit=Decimal("5000.00"), statement_day=28, due_day=15,
    )


# ── Genuine matches ──────────────────────────────────────────────────────────

def test_matches_a_real_chase_autopay_description():
    card = _card("Chase Sapphire", "1312")
    assert card_matches_description(
        card, "CHASE CREDIT CRD AUTOPAY                    PPD ID: 4760039224") is True


def test_matches_a_real_chase_payment_description():
    card = _card("Chase Sapphire", "1312")
    assert card_matches_description(card, "Payment to Chase card ending in 3076 08/20") is True


def test_matches_a_compacted_card_name():
    """'Apple Card' pays out as the single token 'APPLECARD'; that card's
    last_four is blank in real data, so the name is the only signal."""
    card = _card("Apple Card", "")
    assert card_matches_description(
        card, "APPLECARD GSBANK PAYMENT    16069006        WEB ID: 9999999999") is True


def test_matches_on_a_word_bounded_last_four():
    card = _card("Generic Rewards", "1312")
    assert card_matches_description(card, "PAYMENT TO CARD 1312") is True


# ── Regressions: substring collisions that must NOT match ────────────────────

def test_does_not_match_purchase_for_a_chase_card():
    """Regression (NF3): 'chase' is a literal substring of 'pur-chase-'. A bare
    substring test made every ordinary card purchase look like a payment to the
    Chase card, which in spendable_pacer.py silently hides real spending."""
    card = _card("Chase Sapphire", "1312")
    assert card_matches_description(card, "POS PURCHASE TARGET #1234") is False
    assert card_matches_description(card, "DEBIT CARD PURCHASE KROGER") is False


def test_does_not_match_a_merchant_that_merely_starts_with_the_name_token():
    """The compacted-name rule must not degrade into a bare prefix match --
    'APPLEBEES' starts with 'apple' but is a restaurant, not a card payment."""
    card = _card("Apple Card", "")
    assert card_matches_description(card, "APPLEBEES GRILL + BAR") is False


def test_does_not_match_last_four_buried_inside_a_longer_number():
    """A transaction number containing the digits is not a card match."""
    card = _card("Generic Rewards", "1312")
    assert card_matches_description(
        card, "Online Transfer transaction#: 30131234567 07/31") is False


def test_unrelated_description_does_not_match():
    card = _card("Chase Sapphire", "1312")
    assert card_matches_description(card, "KROGER #5001") is False


# ── Degenerate inputs ────────────────────────────────────────────────────────

def test_blank_card_name_and_last_four_never_match():
    card = _card("", "")
    assert card_matches_description(card, "CHASE CREDIT CRD AUTOPAY") is False


def test_matching_is_case_insensitive_on_the_card_name():
    card = _card("CHASE Sapphire", "1312")
    assert card_matches_description(card, "chase credit crd autopay") is True
