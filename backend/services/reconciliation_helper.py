from __future__ import annotations
from calendar import monthrange
from datetime import date
from decimal import Decimal
from sqlalchemy.orm import Session, joinedload
from backend import models
from backend.schemas import (
    ReconcileResponse, ReconcileMatchedItem,
    ReconcileUnmatchedRecurring, ReconcileUnmatchedTransaction,
)

# Keyword fragments that identify CC autopay debits in bank descriptions.
_CC_AUTOPAY_KEYWORDS = ("autopay", "gsbank payment", "credit crd", "creditcard")


def _is_cc_autopay_desc(desc: str) -> bool:
    d = desc.lower()
    return any(kw in d for kw in _CC_AUTOPAY_KEYWORDS)


def _card_matches_desc(card: models.CreditCard, desc: str) -> bool:
    desc_lower = desc.lower()
    card_name = (card.name or "").lower().strip()
    first_token = card_name.split()[0] if card_name else ""
    if first_token and first_token in desc_lower:
        return True
    if card.last_four and card.last_four in desc:
        return True
    return False


def _fuzzy_match_cc_ri(
    txn: models.Transaction,
    cc_items: list[models.RecurringItem],
) -> models.RecurringItem | None:
    """Match against credit_card_payment recurring items by card name token."""
    desc_lower = txn.description.lower()
    for item in cc_items:
        if not item.card:
            continue
        card_name = (item.card.name or "").lower().strip()
        first_token = card_name.split()[0] if card_name else ""
        if first_token and first_token in desc_lower:
            return item
    return None


def _fires_this_month(item: models.RecurringItem, month: int) -> bool:
    if item.frequency == models.RecurringFrequency.yearly:
        if item.month_of_year and item.month_of_year != month:
            return False
    return True


def compute_reconciliation(
    db: Session,
    user_id: int,
    account_id: int,
    year: int,
    month: int,
) -> ReconcileResponse:
    start = date(year, month, 1)
    end = date(year, month, monthrange(year, month)[1])

    txns = db.query(models.Transaction).filter(
        models.Transaction.user_id == user_id,
        models.Transaction.account_id == account_id,
        models.Transaction.is_actual == True,
        models.Transaction.date >= start,
        models.Transaction.date <= end,
    ).all()

    # All user RIs with card loaded — for matched lookup without account restriction.
    all_user_ri = db.query(models.RecurringItem).options(
        joinedload(models.RecurringItem.card)
    ).filter(
        models.RecurringItem.user_id == user_id,
    ).all()
    all_user_ri_map = {r.id: r for r in all_user_ri}

    # Active RIs expected as direct checking debits/credits.
    # Excludes CC charge expenses (card_id + type=expense) — those hit the card, not checking.
    active_recurring = [
        r for r in all_user_ri
        if r.account_id == account_id
        and r.is_active
        and r.start_date <= end
        and (r.end_date is None or r.end_date >= start)
        and not (r.type == models.RecurringType.expense and r.card_id is not None)
        and _fires_this_month(r, month)
    ]

    # All active CC cards — for card-based autopay matching when no RI exists.
    all_cards = db.query(models.CreditCard).filter(
        models.CreditCard.user_id == user_id,
        models.CreditCard.is_active == True,
    ).all()
    card_by_id = {c.id: c for c in all_cards}

    linked_txns = [t for t in txns if t.recurring_item_id is not None]
    unlinked_txns = [t for t in txns if t.recurring_item_id is None]
    matched_ri_ids: set[int] = set()

    # ── Tier 1: explicit matches via recurring_item_id (no account restriction) ──
    matched = []
    for t in linked_txns:
        ri = all_user_ri_map.get(t.recurring_item_id)
        if ri:
            expected = ri.amount if ri.type == models.RecurringType.income else -ri.amount
            matched.append(ReconcileMatchedItem(
                transaction_id=t.id,
                date=t.date,
                description=t.description,
                actual_amount=t.amount,
                recurring_item_id=ri.id,
                recurring_name=ri.name,
                expected_amount=expected,
                variance=t.amount - expected,
            ))
            matched_ri_ids.add(ri.id)

    # ── Tier 2: fuzzy match CC autopay to credit_card_payment recurring items ──
    # Handles cases where a RI exists but account_id or card linkage varies.
    cc_ri_pool = [
        r for r in all_user_ri
        if r.type == models.RecurringType.credit_card_payment
        and r.is_active
        and r.id not in matched_ri_ids
    ]

    remaining_after_ri = []
    for t in unlinked_txns:
        if t.amount < 0 and cc_ri_pool:
            ri = _fuzzy_match_cc_ri(t, cc_ri_pool)
            if ri:
                expected = -ri.amount
                matched.append(ReconcileMatchedItem(
                    transaction_id=t.id,
                    date=t.date,
                    description=t.description,
                    actual_amount=t.amount,
                    recurring_item_id=ri.id,
                    recurring_name=ri.name,
                    expected_amount=expected,
                    variance=t.amount - expected,
                ))
                matched_ri_ids.add(ri.id)
                cc_ri_pool = [r for r in cc_ri_pool if r.id != ri.id]
                continue
        remaining_after_ri.append(t)

    # ── Tier 3: card-based autopay matching (no RI required) ──
    # Group ALL CC autopay transactions for the same card into one combined row.
    # Expected = monthly_spend_estimate so the variance reflects over/under spend.
    cc_autopay_by_card: dict[int, tuple[models.CreditCard, list[models.Transaction]]] = {}
    remaining_unlinked = []
    for t in remaining_after_ri:
        if t.amount < 0 and _is_cc_autopay_desc(t.description):
            matched_card = None
            for card in all_cards:
                if _card_matches_desc(card, t.description):
                    matched_card = card
                    break
            if matched_card:
                if matched_card.id not in cc_autopay_by_card:
                    cc_autopay_by_card[matched_card.id] = (matched_card, [])
                cc_autopay_by_card[matched_card.id][1].append(t)
                continue
        remaining_unlinked.append(t)

    for card_id, (card, txns) in cc_autopay_by_card.items():
        total_actual = sum(Decimal(str(t.amount)) for t in txns)
        if card.monthly_spend_estimate and card.monthly_spend_estimate > 0:
            expected = -Decimal(str(card.monthly_spend_estimate))
        else:
            expected = total_actual  # no estimate configured; show zero variance
        matched.append(ReconcileMatchedItem(
            transaction_id=txns[0].id,
            date=txns[0].date,
            description=txns[0].description,
            actual_amount=total_actual,
            card_id=card.id,
            recurring_name=f"CC Payment: {card.name}",
            expected_amount=expected,
            variance=total_actual - expected,
        ))

    unmatched_recurring = [
        ReconcileUnmatchedRecurring(
            recurring_item_id=r.id,
            name=r.name,
            expected_amount=r.amount,
            expected_day=r.day_of_month,
        )
        for r in active_recurring
        if r.id not in matched_ri_ids
    ]

    unmatched_transactions = [
        ReconcileUnmatchedTransaction(
            transaction_id=t.id,
            date=t.date,
            description=t.description,
            amount=t.amount,
        )
        for t in remaining_unlinked
    ]

    return ReconcileResponse(
        account_id=account_id,
        year=year,
        month=month,
        matched=matched,
        unmatched_recurring=unmatched_recurring,
        unmatched_transactions=unmatched_transactions,
    )
