"""Shared heuristic for matching a bank-transaction description to a credit card.

Bank-generated autopay/payment descriptions ("CHASE CREDIT CRD AUTOPAY") never
contain a card's full display name ("Chase Sapphire") verbatim -- only the
issuer name in common. Matching on the first word of the card's name (plus a
last-four fallback when the description happens to include it) is the same
heuristic forecast_engine.py's CC-actuals suppression already relies on.
"""
from __future__ import annotations
from backend import models


def card_matches_description(card: models.CreditCard, description: str) -> bool:
    name_lower = (card.name or "").lower().strip()
    first_token = name_lower.split()[0] if name_lower else ""
    desc_lower = description.lower()
    if first_token and first_token in desc_lower:
        return True
    if card.last_four and card.last_four in description:
        return True
    return False
