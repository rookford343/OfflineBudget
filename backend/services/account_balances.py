"""Account balances as if pending goes through, and the month's change on them.

One recipe for the sidebar list and total, the Dashboard Checking card and the
sidebar's percent-change badge (docs/architecture.md, "Account balance with
pending"). The frontend displays these figures and does no math on them.
"""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend import models, schemas
from backend.services.pending import checking_pending_rows

ZERO = Decimal("0")
# A start-of-month balance closer to zero than this gives no meaningful percentage.
MIN_START_FOR_PCT = Decimal("0.01")


def _posted_month_flow(db: Session, account: models.Account, month_start: date) -> Decimal:
    total = db.query(func.coalesce(func.sum(models.Transaction.amount), 0)).filter(
        models.Transaction.user_id == account.user_id,
        models.Transaction.account_id == account.id,
        models.Transaction.is_actual == True,
        models.Transaction.date >= month_start,
    ).scalar()
    return Decimal(str(total))


def account_balances(db: Session, user_id: int, today: date) -> schemas.AccountBalancesOut:
    accounts = db.query(models.Account).filter(
        models.Account.user_id == user_id,
        models.Account.is_active == True,
    ).order_by(models.Account.id).all()
    month_start = today.replace(day=1)
    out: list[schemas.AccountBalanceOut] = []
    for account in accounts:
        posted = Decimal(str(account.current_balance))
        rows = checking_pending_rows(db, account, today)
        pending_total = sum((Decimal(str(r.amount)) for r in rows), ZERO)
        after = posted + pending_total
        posted_flow = _posted_month_flow(db, account, month_start)
        # Start of month = posted balance before this month's posted flow; the
        # pending flow is inside `after` and is not in the start.
        start = after - (posted_flow + pending_total)
        pct = None
        if abs(start) >= MIN_START_FOR_PCT:
            pct = ((after - start) / abs(start) * 100).quantize(Decimal("0.01"), ROUND_HALF_UP)
        out.append(schemas.AccountBalanceOut(
            account_id=account.id,
            posted=posted,
            pending_total=pending_total,
            pending_count=len(rows),
            pending=[schemas.AccountPendingTransactionOut.model_validate(r) for r in rows],
            after_pending=after,
            month_start_balance=start,
            month_change_pct=pct,
        ))
    return schemas.AccountBalancesOut(
        accounts=out,
        total_after_pending=sum((a.after_pending for a in out), ZERO),
    )


def running_balance(
    db: Session, user_id: int, account_id: int, start: date, today: date,
) -> list[schemas.RunningBalanceRow]:
    """The Balance column on the Transactions page, for one account.

    Pending rows walk forward from the posted balance, oldest first, so the
    last one ends at `after_pending`. Posted rows walk backward from the posted
    balance, newest first: a posted row's figure is the balance right after it
    posted. Posted rows are every row from `start` to `today`, as the page's
    list has always counted them.
    """
    account = db.query(models.Account).filter(
        models.Account.id == account_id, models.Account.user_id == user_id,
    ).one()
    posted = Decimal(str(account.current_balance))
    out: list[schemas.RunningBalanceRow] = []
    run = posted
    for p in sorted(checking_pending_rows(db, account, today), key=lambda r: (r.date, r.id)):
        run += Decimal(str(p.amount))
        out.append(schemas.RunningBalanceRow(kind="pending", id=p.id, date=p.date, balance_after=run))
    run = posted
    txns = db.query(models.Transaction).filter(
        models.Transaction.user_id == user_id,
        models.Transaction.account_id == account_id,
        models.Transaction.date >= start,
        models.Transaction.date <= today,
    ).order_by(models.Transaction.date.desc(), models.Transaction.id.desc()).all()
    for t in txns:
        out.append(schemas.RunningBalanceRow(kind="posted", id=t.id, date=t.date, balance_after=run))
        run -= Decimal(str(t.amount))
    return out
