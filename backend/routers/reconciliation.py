from __future__ import annotations
from calendar import monthrange
from datetime import date
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from backend import models
from backend.dependencies import get_db, get_current_user
from backend.schemas import (
    ReconcileResponse, ReconcileMatchedItem,
    ReconcileUnmatchedRecurring, ReconcileUnmatchedTransaction,
)

router = APIRouter(prefix="/reconciliation", tags=["reconciliation"])


@router.get("", response_model=ReconcileResponse)
def reconcile(
    account_id: int,
    year: int,
    month: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    start = date(year, month, 1)
    end = date(year, month, monthrange(year, month)[1])

    txns = db.query(models.Transaction).filter(
        models.Transaction.user_id == user.id,
        models.Transaction.account_id == account_id,
        models.Transaction.is_actual == True,
        models.Transaction.date >= start,
        models.Transaction.date <= end,
    ).all()

    recurring = db.query(models.RecurringItem).filter(
        models.RecurringItem.user_id == user.id,
        models.RecurringItem.account_id == account_id,
        models.RecurringItem.is_active == True,
        models.RecurringItem.start_date <= end,
    ).filter(
        (models.RecurringItem.end_date == None) | (models.RecurringItem.end_date >= start)
    ).all()

    def fires_this_month(item: models.RecurringItem) -> bool:
        if item.frequency == models.RecurringFrequency.yearly:
            if item.month_of_year and item.month_of_year != month:
                return False
        return True

    active_recurring = [r for r in recurring if fires_this_month(r)]
    linked_txns = [t for t in txns if t.recurring_item_id is not None]
    unlinked_txns = [t for t in txns if t.recurring_item_id is None]
    linked_ri_ids = {t.recurring_item_id for t in linked_txns}

    matched = []
    for t in linked_txns:
        ri = next((r for r in active_recurring if r.id == t.recurring_item_id), None)
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

    unmatched_recurring = [
        ReconcileUnmatchedRecurring(
            recurring_item_id=r.id,
            name=r.name,
            expected_amount=r.amount,
            expected_day=r.day_of_month,
        )
        for r in active_recurring
        if r.id not in linked_ri_ids
    ]

    unmatched_transactions = [
        ReconcileUnmatchedTransaction(
            transaction_id=t.id,
            date=t.date,
            description=t.description,
            amount=t.amount,
        )
        for t in unlinked_txns
    ]

    return ReconcileResponse(
        account_id=account_id,
        year=year,
        month=month,
        matched=matched,
        unmatched_recurring=unmatched_recurring,
        unmatched_transactions=unmatched_transactions,
    )
