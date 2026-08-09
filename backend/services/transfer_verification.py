"""Matches scheduled PlannedTransfers against real synced/imported
transactions, closing the loop without a second manual confirmation click.
Reuses the same fuzzy amount + date window matching idea already used
elsewhere in this codebase (e.g. import_service.py's recurring-item
auto-match), rather than a new algorithm."""
from __future__ import annotations
from datetime import timedelta
from decimal import Decimal
from sqlalchemy.orm import Session
from backend import models

_DATE_WINDOW_DAYS = 5
_AMOUNT_TOLERANCE_PCT = Decimal("0.05")  # 5%


def verify_scheduled_transfers(db: Session, user_id: int) -> int:
    """Scans this user's `scheduled` PlannedTransfers for a matching real
    transaction on the destination account, within a 5-day window of
    target_date and 5% of the planned amount. On match, flips status to
    `verified` and records the link. Returns the count verified.

    Two guards keep amount+date fuzziness from producing false positives,
    which are the expensive kind of error here: a transfer marked done that
    Dan never actually made looks safe on the forecast while the real money
    isn't there.

    1. One transaction, one transfer. A transaction already claimed by
       another PlannedTransfer.verified_transaction_id can never match a
       second one -- otherwise two transfers near the same date both flip to
       verified off a single real deposit. The claimed set is seeded from the
       database (so it survives across runs) and extended as this run
       assigns matches.
    2. Recurring items are never manual transfers. A transaction already
       linked to a RecurringItem is a recognized paycheck/bill, so it's
       excluded outright -- that rules out the most common real-world
       collision, a paycheck landing inside the tolerance window.
    """
    scheduled = db.query(models.PlannedTransfer).filter(
        models.PlannedTransfer.user_id == user_id,
        models.PlannedTransfer.status == models.PlannedTransferStatus.scheduled,
    ).all()

    claimed_txn_ids: set[int] = {
        row[0] for row in db.query(models.PlannedTransfer.verified_transaction_id).filter(
            models.PlannedTransfer.user_id == user_id,
            models.PlannedTransfer.verified_transaction_id.isnot(None),
        ).all()
    }

    verified_count = 0
    for transfer in scheduled:
        window_start = transfer.target_date - timedelta(days=_DATE_WINDOW_DAYS)
        window_end = transfer.target_date + timedelta(days=_DATE_WINDOW_DAYS)
        low = transfer.amount * (1 - _AMOUNT_TOLERANCE_PCT)
        high = transfer.amount * (1 + _AMOUNT_TOLERANCE_PCT)

        query = db.query(models.Transaction).filter(
            models.Transaction.user_id == user_id,
            models.Transaction.account_id == transfer.to_account_id,
            models.Transaction.date >= window_start,
            models.Transaction.date <= window_end,
            models.Transaction.amount >= low,
            models.Transaction.amount <= high,
            models.Transaction.recurring_item_id.is_(None),
        )
        if claimed_txn_ids:
            query = query.filter(models.Transaction.id.notin_(claimed_txn_ids))

        match = query.order_by(models.Transaction.date, models.Transaction.id).first()

        if match:
            transfer.status = models.PlannedTransferStatus.verified
            transfer.verified_transaction_id = match.id
            claimed_txn_ids.add(match.id)
            verified_count += 1

    if verified_count:
        db.commit()
    return verified_count
