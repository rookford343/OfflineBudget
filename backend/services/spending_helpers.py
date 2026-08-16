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
# "AUTOMATIC PAYMENT - THANK" row of $11,312.54 was the largest line in Dan's
# card spending and the top entry in the weekly email's merchant list. The
# checking side already excludes the mirror-image debit via
# card_matching.card_matches_description; this is the card-side counterpart.
#
# Matched on a word-boundary basis against the whole merchant string so
# "MINDBODY PAYMENTS" (a real gym charge) is not caught.
_CARD_PAYMENT_PATTERNS = re.compile(
    r"(^|\b)(automatic\s+payment|autopay|online\s+payment|payment\s*-\s*thank"
    r"|payment\s+thank\s+you|mobile\s+payment|electronic\s+payment)(\b|$)",
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
        2026-08-15 this was $11,312.54 -- by far the largest "merchant" in
        Dan's July list, above his mortgage.
      - An internal transfer ("Online Transfer to CHK ...0054"). It never
        leaves the household at all, yet showed up as the top August
        "merchant" at $1,000.

    This predicate is the single source of truth for that question.
    spendable_pacer.py held the only copy until 2026-08-15, which is exactly
    why the Spending page and the weekly email -- built on
    spending_helpers -- never got the fix and stayed inflated. Same class of
    drift as forecast_engine._fires_on vs summary_generator._fires_soon.
    """
    from backend.services.card_matching import card_matches_description

    if any(card_matches_description(card, description or "") for card in active_cards):
        return False
    if looks_like_internal_transfer(description):
        return False
    return True


def _active_cards(db: Session, user_id: int) -> list:
    return db.query(models.CreditCard).filter(
        models.CreditCard.user_id == user_id,
        models.CreditCard.is_active == True,
    ).all()


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

    Combines checking-account expense transactions (keyed by description) and
    credit-card charges (keyed by merchant) — same behavior as the existing
    /spending/by-merchant endpoint.

    Refunds/credits net against the matching charge rather than being
    dropped. On the card side this is unconditional -- CreditCardTransaction
    only ever holds charges and their refunds, never unrelated income, so a
    negative amount is always a credit against that same merchant's spend.
    On the checking side a positive amount could just as easily be a
    paycheck, a Zelle from a relative, or a transfer from savings -- none of
    which should net against "spending". A checking credit only nets in when
    its description exactly matches a debit description already counted in
    this window, which is what a same-merchant refund looks like and what an
    unrelated deposit never does.
    """
    from backend.services.merchant_normalizer import build_alias_map, display_name

    totals: dict[str, Decimal] = {}
    counts: dict[str, int] = {}
    # Group by normalized merchant, not the raw descriptor. Keyed raw, Amazon
    # split across 138 strings totalling $6,762 in 2026 and never surfaced.
    alias_map = build_alias_map(db, user_id)

    checking_q = (
        db.query(models.Transaction)
        .outerjoin(models.Category, models.Transaction.category_id == models.Category.id)
        .filter(
            models.Transaction.user_id == user_id,
            models.Transaction.is_actual == True,
            models.Transaction.date >= start,
            models.Transaction.date <= end,
            models.Transaction.amount < 0,
            NOT_SAVINGS,
        )
    )
    if account_id:
        checking_q = checking_q.filter(models.Transaction.account_id == account_id)
    # Narrowing to a category set is what lets the Budget page ask "which
    # merchants made up Subscriptions this month?" through this function
    # rather than a parallel query that would drift from its normalization
    # and refund-netting rules.
    if category_ids is not None:
        checking_q = checking_q.filter(models.Transaction.category_id.in_(category_ids))
    # Card payoffs and internal transfers can't be expressed as SQL: both need
    # the description matched against Python-side data. Filter after fetch.
    cards = _active_cards(db, user_id)
    debit_rows = [t for t in checking_q.all() if is_real_checking_spend(t.description, cards)]
    debit_descriptions = {t.description for t in debit_rows if t.description}
    for t in debit_rows:
        key = display_name(t.description, alias_map)
        totals[key] = totals.get(key, Decimal("0")) + abs(t.amount)
        counts[key] = counts.get(key, 0) + 1

    if debit_descriptions:
        refund_q = db.query(models.Transaction).filter(
            models.Transaction.user_id == user_id,
            models.Transaction.is_actual == True,
            models.Transaction.date >= start,
            models.Transaction.date <= end,
            models.Transaction.amount > 0,
            models.Transaction.description.in_(debit_descriptions),
        )
        if account_id:
            refund_q = refund_q.filter(models.Transaction.account_id == account_id)
        if category_ids is not None:
            refund_q = refund_q.filter(models.Transaction.category_id.in_(category_ids))
        for t in refund_q.all():
            key = display_name(t.description, alias_map)
            totals[key] = totals.get(key, Decimal("0")) - t.amount

    card_q = db.query(models.CreditCardTransaction).filter(
        models.CreditCardTransaction.user_id == user_id,
        models.CreditCardTransaction.date >= start,
        models.CreditCardTransaction.date <= end,
    )
    if card_id:
        card_q = card_q.filter(models.CreditCardTransaction.card_id == card_id)
    if category_ids is not None:
        card_q = card_q.filter(models.CreditCardTransaction.category_id.in_(category_ids))
    for t in card_q.all():
        if is_card_payment(t.merchant):
            continue
        key = display_name(t.merchant, alias_map)
        totals[key] = totals.get(key, Decimal("0")) + t.amount
        if t.amount > 0:
            counts[key] = counts.get(key, 0) + 1

    sorted_entries = sorted(totals.items(), key=lambda x: x[1], reverse=True)[:limit]
    # counts.get, not counts[]: a merchant appearing ONLY as a refund in this
    # window (negative card row) lands in `totals` but never increments
    # `counts`, which is guarded to charges. That raised KeyError and took the
    # whole Spending page down with a 500. Latent before 2026-08-15 and only
    # reachable once the transfer/payoff filter changed which rows survive --
    # hit immediately on Dan's real July data ("MICHAELS STORES 9951").
    return [(name, total, counts.get(name, 0)) for name, total in sorted_entries]


def category_totals_for_range(db: Session, user_id: int, start: date, end: date) -> dict[int | None, Decimal]:
    """Sum of expense spending per category_id across checking + credit-card
    transactions in [start, end]. Savings-type categories are excluded, matching
    the rest of the app's spending totals. Transactions with no category_id are
    grouped under the `None` key so callers can surface an "Uncategorized"
    bucket instead of silently dropping that spend.

    Refunds/credits net against the matching charge rather than being
    dropped -- see merchant_totals' docstring for why the card side nets
    unconditionally while the checking side only nets a credit whose
    description matches an already-counted debit (a same-merchant refund,
    not unrelated income landing in the same category).
    """
    totals: dict[int | None, Decimal] = {}

    checking_q = (
        db.query(models.Transaction)
        .outerjoin(models.Category, models.Transaction.category_id == models.Category.id)
        .filter(
            models.Transaction.user_id == user_id,
            models.Transaction.is_actual == True,
            models.Transaction.date >= start,
            models.Transaction.date <= end,
            models.Transaction.amount < 0,
            NOT_SAVINGS,
        )
    )
    cards = _active_cards(db, user_id)
    debit_rows = [t for t in checking_q.all() if is_real_checking_spend(t.description, cards)]
    debit_descriptions = {t.description for t in debit_rows if t.description}
    for t in debit_rows:
        totals[t.category_id] = totals.get(t.category_id, Decimal("0")) + abs(t.amount)

    if debit_descriptions:
        refund_q = db.query(models.Transaction).filter(
            models.Transaction.user_id == user_id,
            models.Transaction.is_actual == True,
            models.Transaction.date >= start,
            models.Transaction.date <= end,
            models.Transaction.amount > 0,
            models.Transaction.description.in_(debit_descriptions),
        )
        for t in refund_q.all():
            totals[t.category_id] = totals.get(t.category_id, Decimal("0")) - t.amount

    card_q = (
        db.query(models.CreditCardTransaction)
        .outerjoin(models.Category, models.CreditCardTransaction.category_id == models.Category.id)
        .filter(
            models.CreditCardTransaction.user_id == user_id,
            models.CreditCardTransaction.date >= start,
            models.CreditCardTransaction.date <= end,
            or_(
                models.CreditCardTransaction.category_id.is_(None),
                models.Category.type != models.CategoryType.savings,
            ),
        )
    )
    for t in card_q.all():
        if is_card_payment(t.merchant):
            continue
        totals[t.category_id] = totals.get(t.category_id, Decimal("0")) + t.amount

    return totals

def filter_real_spend(db: Session, user_id: int, rows: list) -> list:
    """Drop card payoffs and internal transfers from fetched checking rows.

    The list-level companion to is_real_checking_spend, for the endpoints that
    build their own query rather than going through merchant_totals /
    category_totals_for_range.

    Those endpoints are exactly where this kept getting missed. On Dan's real
    data the Trends chart reported ~$58,000 for April 2026; $32,000 of it was
    a single "Online Transfer to SAV" and another $5,915 a Chase autopay --
    neither a dollar of spending. Same defect the Spending page had, in a
    different query, because each endpoint filtered `amount < 0` itself.
    """
    cards = _active_cards(db, user_id)
    return [t for t in rows if is_real_checking_spend(t.description, cards)]

