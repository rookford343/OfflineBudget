"""Cross-provider cutover matcher.

When a bank moves from SimpleFIN (or a CSV import) to Plaid, Plaid re-sends
transactions the old provider already stored, under its own transaction id.
External-id dedup can't catch that -- the ids never match -- so for a short
window around the cutover date every existing checking/card row is a
candidate, regardless of its own external_id, and is matched to the incoming
Plaid row by amount, a date window, and a fuzzy description match (see the
Matching rule in the Plaid sync design's global constraints).

`cutover_zone` tells a caller (the sync loop) whether a row even needs this:
outside the window it's either too old to matter or new enough that both
providers already agree on ids, so `find_match` is skipped entirely."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from sqlalchemy.orm import Session

from backend import models
from backend.services.import_service import _evidence_tokens, _normalize_desc
from backend.services.plaid_client import PlaidTransaction

# Cutover window global constraint: rows older than this many days before
# cutover are ignored outright; rows from this far before cutover through
# WINDOW_AFTER_DAYS after it get cross-provider matching; later rows rely on
# external-id dedup only.
WINDOW_BEFORE_DAYS = 10
WINDOW_AFTER_DAYS = 3
# Matching rule global constraint: a candidate's date must be within this
# many days of Plaid's `date` or `authorized_date`.
MATCH_DAYS = 3


def cutover_zone(row_date: date, cutover: date) -> Literal["ignore", "match", "normal"]:
    """Where `row_date` falls relative to `cutover`, per the Cutover window
    global constraint."""
    if row_date < cutover - timedelta(days=WINDOW_BEFORE_DAYS):
        return "ignore"
    if row_date <= cutover + timedelta(days=WINDOW_AFTER_DAYS):
        return "match"
    return "normal"


def _text_matches(candidate_text: str, txn: PlaidTransaction) -> bool:
    """The Matching rule's description test: normalized equality, a shared
    `_evidence_tokens` token, or the lowercased Plaid merchant name found
    inside the stored text -- any one of the three is enough."""
    if _normalize_desc(candidate_text) == _normalize_desc(txn.description):
        return True
    if _evidence_tokens(candidate_text) & _evidence_tokens(txn.description):
        return True
    if txn.merchant_name and txn.merchant_name.lower() in candidate_text.lower():
        return True
    return False


def _distance_days(txn: PlaidTransaction, candidate_date: date) -> int:
    """`min(|c.date - date|, |c.date - authorized_date|)`, falling back to
    `date` alone when there's no `authorized_date` to compare against."""
    by_date = abs((candidate_date - txn.date).days)
    if txn.authorized_date is None:
        return by_date
    by_auth = abs((candidate_date - txn.authorized_date).days)
    return min(by_date, by_auth)


def find_match(
    db: Session,
    user_id: int,
    *,
    account_id: int | None,
    card_id: int | None,
    txn: PlaidTransaction,
    consumed: set[int],
) -> models.Transaction | models.CreditCardTransaction | None:
    """Finds the existing SimpleFIN/CSV row that `txn` (a newly-synced Plaid
    transaction) is the same real-world event as. Every existing row on this
    account/card is a candidate regardless of its own `external_id` -- that's
    the whole point, since a SimpleFIN row carries its own id, never Plaid's.

    Exactly one of `account_id`/`card_id` must be given. On a match, the
    winning row's id is added to `consumed`, so a caller looping over several
    Plaid rows against the same shared set gets 1:1 matching."""
    if (account_id is None) == (card_id is None):
        raise ValueError("find_match takes exactly one of account_id or card_id")

    window_dates = [txn.date] if txn.authorized_date is None else [txn.date, txn.authorized_date]
    lo = min(window_dates) - timedelta(days=MATCH_DAYS)
    hi = max(window_dates) + timedelta(days=MATCH_DAYS)

    if account_id is not None:
        rows = db.query(models.Transaction).filter(
            models.Transaction.user_id == user_id,
            models.Transaction.account_id == account_id,
            models.Transaction.amount == txn.amount,
            models.Transaction.date.between(lo, hi),
        ).all()
        texts = {row.id: row.description for row in rows}
    else:
        rows = db.query(models.CreditCardTransaction).filter(
            models.CreditCardTransaction.user_id == user_id,
            models.CreditCardTransaction.card_id == card_id,
            models.CreditCardTransaction.amount == -txn.amount,
            models.CreditCardTransaction.date.between(lo, hi),
        ).all()
        texts = {row.id: row.merchant for row in rows}

    eligible = [
        row for row in rows
        if row.id not in consumed and _text_matches(texts[row.id], txn)
    ]
    if not eligible:
        return None

    best = min(eligible, key=lambda row: (_distance_days(txn, row.date), row.id))
    consumed.add(best.id)
    return best
