import re
from datetime import date
from decimal import Decimal
from sqlalchemy import or_
from sqlalchemy.orm import Session
from backend import models

NOT_SAVINGS = or_(
    models.Transaction.category_id.is_(None),
    models.Category.type != models.CategoryType.savings,
)

# Merchant text that means "this row is a payment settling the card", not a
# purchase. Paying the card moves money between accounts; the charges being
# settled were already counted individually, so counting the payment too
# double-counts the whole statement.
#
# These reach the card table with a positive (charge-side) amount, so they
# inflate spend rather than netting out. Found live 2026-08-12: a single
# "AUTOMATIC PAYMENT - THANK" row of $9,000.00 was the largest line in the user's
# card spending and the top entry in the weekly email's merchant list. The
# checking side already excludes the mirror-image debit via
# card_matching.card_matches_description; this is the card-side counterpart.
#
# Matched on a word-boundary basis against the whole merchant string so
# "MINDBODY PAYMENTS" (a real gym charge) is not caught.
_CARD_PAYMENT_PATTERNS = re.compile(
    r"(^|\b)(automatic\s+payment|autopay|online\s+payment|payment\s*-\s*thank"
    r"|payment\s+thank\s+you|mobile\s+payment|electronic\s+payment"
    # Apple Card's payment credit: "ACH DEPOSIT INTERNET TRANSFER FROM
    # ACCOUNT ENDING IN ...".
    r"|internet\s+transfer\s+from\s+account)(\b|$)",
    re.IGNORECASE,
)


def is_card_payment(merchant: str | None) -> bool:
    """True when a card-table row is a payment against the card, not a purchase."""
    if not merchant:
        return False
    return _CARD_PAYMENT_PATTERNS.search(merchant) is not None


# Bank wordings for money moved between the user's own accounts.
_TRANSFER_DESCRIPTION_MARKERS = ("online transfer", "transfer to", "transfer from")


def looks_like_internal_transfer(description: str | None) -> bool:
    """True when a CHECKING description looks like money moved between the
    user's own accounts rather than spent.

    HEURISTIC, not a fact: `Transaction` has no persisted `is_transfer`
    column (it exists only transiently on CSV-import row schemas and is
    discarded once categorization decisions are made), so the description
    text is the only signal available at this layer. False positives (a
    merchant literally named "Transfer To ...") and false negatives (a bank
    wording we don't list) are both possible -- the same accuracy tolerance
    the codebase already accepts from card_matching.card_matches_description.
    """
    desc = (description or "").lower()
    return any(marker in desc for marker in _TRANSFER_DESCRIPTION_MARKERS)


def is_real_checking_spend(description: str | None, active_cards: list) -> bool:
    """Whether a negative checking row is money actually leaving the household.

    Two things routinely land in checking as plain uncategorized debits and
    are not spending:

      - A credit-card payoff ("CHASE CREDIT CRD AUTOPAY"). The charges it
        settles were already counted individually on the card side, so
        counting the payment double-counts the entire statement. Live on
        2026-08-15 this was $9,000.00 -- by far the largest "merchant" in
        the user's July list, above his mortgage.
      - An internal transfer ("Online Transfer to CHK ...XXXX"). It never
        leaves the household at all, yet showed up as the top August
        "merchant" at $1,000.

    Description-only: the full verdict (savings and income categories,
    refunds) is services/real_spend.classify_checking, which every total
    uses. This predicate shares its card-payment and transfer checks.
    """
    from backend.services.real_spend import is_checking_card_payment

    if is_checking_card_payment(description, active_cards):
        return False
    if looks_like_internal_transfer(description):
        return False
    return True


def _active_cards(db: Session, user_id: int) -> list:
    from backend.services.real_spend import active_cards
    return active_cards(db, user_id)


def merchant_totals(
    db: Session,
    user_id: int,
    start: date,
    end: date,
    *,
    account_id: int | None = None,
    card_id: int | None = None,
    category_ids: list[int] | None = None,
    limit: int = 50,
) -> list[tuple[str, Decimal, int]]:
    """Returns [(name, total, count), ...] sorted by total descending.

    Combines checking rows (keyed by description) and card rows (keyed by
    merchant), counting only what the real-spending rule
    (services/real_spend.py) calls spend. Refunds net against the matching
    merchant; `count` counts charges only.
    """
    from backend.services.merchant_normalizer import build_alias_map, display_name
    from backend.services.real_spend import classified_rows

    totals: dict[str, Decimal] = {}
    counts: dict[str, int] = {}
    # Group by normalized merchant, not the raw descriptor. Keyed raw, Amazon
    # split across 138 strings totalling $6,762 in 2026 and never surfaced.
    alias_map = build_alias_map(db, user_id)
    wanted = set(category_ids) if category_ids is not None else None

    for r in classified_rows(db, user_id, start, end, account_id=account_id, card_id=card_id):
        if r.verdict.kind != "spend":
            continue
        # Narrowing to a category set is what lets the Budget page ask "which
        # merchants made up Subscriptions this month?" through this function
        # rather than a parallel query that would drift from its rules.
        if wanted is not None and r.category_id not in wanted:
            continue
        raw = r.row.description if r.source == "checking" else r.row.merchant
        key = display_name(raw, alias_map)
        totals[key] = totals.get(key, Decimal("0")) + r.verdict.amount
        if r.verdict.amount > 0:
            counts[key] = counts.get(key, 0) + 1

    sorted_entries = sorted(totals.items(), key=lambda x: x[1], reverse=True)[:limit]
    # counts.get, not counts[]: a merchant appearing ONLY as a refund in this
    # window lands in `totals` but never increments `counts`, which is
    # guarded to charges. That raised KeyError and took the whole Spending
    # page down with a 500 on the user's real July data.
    return [(name, total, counts.get(name, 0)) for name, total in sorted_entries]


def category_totals_for_range(db: Session, user_id: int, start: date, end: date) -> dict[int | None, Decimal]:
    """Real spending per category_id across checking + card rows in
    [start, end], net of refunds (a category may be negative). Uncategorized
    spend is grouped under the `None` key. The rule lives in
    services/real_spend.py; this is its per-category view."""
    from backend.services.real_spend import spend_totals
    return spend_totals(db, user_id, start, end).by_category


def filter_real_spend(db: Session, user_id: int, rows: list) -> list:
    """Drop card payoffs and transfers from fetched actual checking rows,
    keeping spend and income. A thin wrapper over the real-spending rule
    (services/real_spend.classify_checking) for list views such as the
    Dashboard's recent activity."""
    from backend.services.real_spend import classify_checking
    cards = _active_cards(db, user_id)
    return [t for t in rows if classify_checking(t, cards).kind in ("spend", "income")]
