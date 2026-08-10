"""Shared heuristic for matching a bank-transaction description to a credit card.

Bank-generated autopay/payment descriptions ("CHASE CREDIT CRD AUTOPAY") never
contain a card's full display name ("Chase Sapphire") verbatim -- only the
issuer name in common. Matching on the first word of the card's name (plus a
last-four fallback when the description happens to include it) is the same
heuristic forecast_engine.py's CC-actuals suppression already relies on.

Matching is WORD-BOUNDED, not a bare substring test. A bare substring test made
"chase" match "pur-chase-", so a card named "Chase Sapphire" matched ordinary
descriptions like "POS PURCHASE TARGET #1234" and "DEBIT CARD PURCHASE KROGER".
That was tolerable when the only caller was forecast_engine.py's narrow "is this
the payoff for card X" check, but spendable_pacer.py now uses this to SUPPRESS
spend, where a false positive silently makes real spending invisible and reports
more money available than actually exists.

Two patterns are accepted, because real issuers write their name both ways:
  - the first name token as a whole word     -- "CHASE CREDIT CRD AUTOPAY"
  - the whole name with spaces removed       -- "APPLECARD GSBANK PAYMENT"
The second is required: "Apple Card" pays out as the single token "APPLECARD",
which a plain \\bapple\\b would miss. Matching the compacted name rather than
just accepting a leading-boundary prefix keeps "APPLEBEES GRILL" from matching
an "Apple Card" -- a prefix-only rule would wrongly suppress that restaurant
charge.
"""
from __future__ import annotations
import re
from backend import models


def _matches_whole_word(needle: str, haystack: str) -> bool:
    """True when `needle` appears in `haystack` delimited by word boundaries."""
    if not needle:
        return False
    return re.search(rf"\b{re.escape(needle)}\b", haystack) is not None


def card_matches_description(card: models.CreditCard, description: str) -> bool:
    name_lower = (card.name or "").lower().strip()
    desc_lower = (description or "").lower()

    if name_lower:
        first_token = name_lower.split()[0]
        # "chase" from "Chase Sapphire" -> "CHASE CREDIT CRD AUTOPAY"
        if _matches_whole_word(first_token, desc_lower):
            return True
        # "applecard" from "Apple Card" -> "APPLECARD GSBANK PAYMENT"
        compact_name = "".join(name_lower.split())
        if compact_name != first_token and _matches_whole_word(compact_name, desc_lower):
            return True

    # Word-bounded so a card ending 1312 isn't matched by a transaction number
    # that merely contains those digits (e.g. "transaction#: 30131234567").
    if card.last_four and _matches_whole_word(card.last_four, description or ""):
        return True
    return False
