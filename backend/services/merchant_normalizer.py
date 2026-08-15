"""Collapse raw bank descriptors into one display name per merchant.

Spending's merchant list was keyed on the raw string, so every transaction
id, store number and payment reference split one merchant into many rows.
Measured on Dan's 2026 data before this existed:

    Amazon   138 distinct strings   $6,762   -- never appeared in the top list
    Church     7 strings            $9,100
    Kroger     5 strings            $2,739
    Costco     2 strings            $2,170
    53 merchants split across multiple descriptors in total

Amazon being his largest discretionary merchant and invisible is the whole
problem: the list was answering "which single descriptor cost the most",
which is not a question anyone has.

Two layers, in order:
  1. MerchantAlias rows -- explicit user corrections, always win. The
     heuristics below WILL get things wrong on some bank's wording, and a
     wrong grouping that can't be corrected is worse than no grouping.
  2. The heuristics here -- strip the noise, then title-case what's left.

Deliberately conservative: when nothing matches, the cleaned original is
returned rather than an aggressive guess. Over-merging two genuinely
different merchants silently corrupts the totals, while under-merging just
leaves the list as long as it already was.
"""
from __future__ import annotations
import re

# Well-known merchants whose descriptors vary so much that pattern-stripping
# alone won't converge them. Matched as a substring on the uppercased raw
# string, first hit wins, so order matters only where one is a prefix of
# another.
_KNOWN_MERCHANTS: list[tuple[str, str]] = [
    ("AMAZON MKTPL", "Amazon"),
    ("AMAZON.COM", "Amazon"),
    ("AMZN MKTP", "Amazon"),
    ("AMAZON PRIME", "Amazon Prime"),
    ("WHOLEFDS", "Whole Foods"),
    ("WHOLE FOODS", "Whole Foods"),
    ("TRADER JOE", "Trader Joe's"),
    ("KROGER", "Kroger"),
    ("COSTCO", "Costco"),
    ("MEIJER", "Meijer"),
    ("ALDI", "Aldi"),
    ("TARGET", "Target"),
    ("WALMART", "Walmart"),
    ("WM SUPERCENTER", "Walmart"),
    ("CHIPOTLE", "Chipotle"),
    ("STARBUCKS", "Starbucks"),
    ("JIMMY JOHNS", "Jimmy John's"),
    ("NETFLIX", "Netflix"),
    ("SPOTIFY", "Spotify"),
    ("HULU", "Hulu"),
    ("LOWES", "Lowe's"),
    ("HOME DEPOT", "Home Depot"),
    ("TRACTOR-SUPPLY", "Tractor Supply"),
    ("TRACTOR SUPPLY", "Tractor Supply"),
    ("ETSY", "Etsy"),
    ("PAYPAL", "PayPal"),
    ("DUKEENERGY", "Duke Energy"),
    ("DUKE ENERGY", "Duke Energy"),
    ("VERIZON", "Verizon"),
    ("INDIANA BMV", "Indiana BMV"),
    ("IN BMV", "Indiana BMV"),
    ("NEWREZ", "Mortgage (NewRez)"),
    ("PROG SO EASTERN", "Progressive Insurance"),
    ("CLAUDE.AI", "Claude.ai"),
]

# Noise stripped from whatever is left after the known-merchant pass. Each
# targets a specific descriptor convention seen in Dan's real data.
_NOISE_PATTERNS = [
    re.compile(r"\b(?:PPD|CCD|WEB|ARC|TEL)\s*ID:?\s*\S+", re.IGNORECASE),   # "PPD ID: 4760039224"
    re.compile(r"\bORIG (?:CO NAME|ID):\S*", re.IGNORECASE),
    re.compile(r"\bCO ENTRY DESCR:\S*", re.IGNORECASE),
    re.compile(r"\bSEC:\S+", re.IGNORECASE),
    re.compile(r"\bIND ID:\S+", re.IGNORECASE),
    re.compile(r"\btransaction#:?\s*\d+", re.IGNORECASE),
    re.compile(r"\bST-[A-Z0-9]+", re.IGNORECASE),                            # church payment ref
    re.compile(r"\*[A-Z0-9]{6,}", re.IGNORECASE),                            # "*BJ1O92ZW1"
    re.compile(r"#\s*\d+\*?"),                                               # "#5001", "#01525*"
    re.compile(r"\b\d{6,}\b"),                                               # long ids
    re.compile(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b"),                         # trailing dates
    re.compile(r"\s+-\s+\d+\s*-\s*[A-Z]?$", re.IGNORECASE),                  # "- 2344 - E"
    # Trailing store number: "MICHAELS STORES 9951", "CHIPOTLE 0686". Anchored
    # to the END and 3+ digits, because that is specifically where a store
    # number sits -- a merchant name rarely ends in a bare 3-digit run, while
    # store numbers there are everywhere and split one chain into a row per
    # location.
    re.compile(r"\s+\d{3,}\s*$"),
]

# Prefixes some processors bolt on that aren't part of the merchant name.
_STRIP_PREFIXES = re.compile(r"^(TST\*|SQ \*|SP \*|PY \*|LS |POS PURCHASE |DEBIT CARD PURCHASE )", re.IGNORECASE)


def normalize_merchant(raw: str | None) -> str:
    """Best-effort display name for a raw bank descriptor.

    Never returns empty: falls back to the original string so a descriptor
    the rules don't understand still shows up rather than vanishing into an
    "Unknown" bucket.
    """
    if not raw or not raw.strip():
        return "Unknown"

    original = raw.strip()
    upper = original.upper()

    for needle, display in _KNOWN_MERCHANTS:
        if needle in upper:
            return display

    cleaned = _STRIP_PREFIXES.sub("", original)
    for pattern in _NOISE_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    cleaned = re.sub(r"[\s,]{2,}", " ", cleaned).strip(" -*,.")

    if not cleaned or len(cleaned) < 3:
        return original

    # Title-case only for SCREAMING descriptors; leave mixed case ("Netflix",
    # "mercyroad.cc") alone, since the bank already wrote those readably.
    if cleaned.isupper():
        cleaned = cleaned.title()
    return cleaned


def build_alias_map(db, user_id: int) -> dict[str, str]:
    """User corrections: normalized-or-raw name -> the display name they chose."""
    from backend import models
    rows = db.query(models.MerchantAlias).filter(models.MerchantAlias.user_id == user_id).all()
    return {r.pattern.strip().lower(): r.display_name for r in rows}


def display_name(raw: str | None, alias_map: dict[str, str]) -> str:
    """Full resolution: an explicit alias on either the raw string or the
    heuristic result wins; otherwise the heuristic result stands.

    Checking the raw string too means a correction can target one specific
    descriptor when the heuristics have merged two things that shouldn't be.
    """
    if raw:
        direct = alias_map.get(raw.strip().lower())
        if direct:
            return direct
    normalized = normalize_merchant(raw)
    return alias_map.get(normalized.strip().lower(), normalized)
