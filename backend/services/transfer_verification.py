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
    `verified` and records the link. Returns the count verified."""
    scheduled = db.query(models.PlannedTransfer).filter(
        models.PlannedTransfer.user_id == user_id,
        models.PlannedTransfer.status == models.PlannedTransferStatus.scheduled,
    ).all()

    verified_count = 0
    for transfer in scheduled:
        window_start = transfer.target_date - timedelta(days=_DATE_WINDOW_DAYS)
        window_end = transfer.target_date + timedelta(days=_DATE_WINDOW_DAYS)
        low = transfer.amount * (1 - _AMOUNT_TOLERANCE_PCT)
        high = transfer.amount * (1 + _AMOUNT_TOLERANCE_PCT)

        match = db.query(models.Transaction).filter(
            models.Transaction.user_id == user_id,
            models.Transaction.account_id == transfer.to_account_id,
            models.Transaction.date >= window_start,
            models.Transaction.date <= window_end,
            models.Transaction.amount >= low,
            models.Transaction.amount <= high,
        ).first()

        if match:
            transfer.status = models.PlannedTransferStatus.verified
            transfer.verified_transaction_id = match.id
            verified_count += 1

    if verified_count:
        db.commit()
    return verified_count
