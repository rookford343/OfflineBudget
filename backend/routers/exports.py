"""Export transactions and budget reports to CSV or JSON."""
from __future__ import annotations
import csv
import io
import json
from calendar import monthrange
from datetime import date
from decimal import Decimal
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session
from backend import models
from backend.dependencies import get_db, get_current_user

router = APIRouter(prefix="/export", tags=["export"])


@router.get("/transactions")
def export_transactions(
    start: date | None = None,
    end: date | None = None,
    account_id: int | None = None,
    format: str = Query("csv", pattern="^(csv|json)$"),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Export checking transactions to CSV or JSON."""
    query = db.query(models.Transaction).filter(models.Transaction.user_id == user.id)
    if account_id:
        query = query.filter(models.Transaction.account_id == account_id)
    if start:
        query = query.filter(models.Transaction.date >= start)
    if end:
        query = query.filter(models.Transaction.date <= end)
    txns = query.order_by(models.Transaction.date.desc()).all()

    if format == "json":
        data = [
            {
                "id": t.id,
                "date": t.date.isoformat(),
                "description": t.description,
                "amount": str(t.amount),
                "category_id": t.category_id,
                "account_id": t.account_id,
                "notes": t.notes,
                "source": t.source.value,
            }
            for t in txns
        ]
        return StreamingResponse(
            io.StringIO(json.dumps(data, indent=2)),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=transactions.json"},
        )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Description", "Amount", "Category ID", "Account ID", "Notes", "Source"])
    for t in txns:
        writer.writerow([
            t.date.isoformat(), t.description, t.amount,
            t.category_id or "", t.account_id, t.notes or "", t.source.value,
        ])
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=transactions.csv"},
    )


@router.get("/budget-report")
def export_budget_report(
    year: int,
    month: int = Query(..., ge=1, le=12),
    format: str = Query("csv", pattern="^(csv|json)$"),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Export monthly budget vs. actuals to CSV or JSON."""
    start = date(year, month, 1)
    end = date(year, month, monthrange(year, month)[1])

    allocs = {
        a.category_id: a.budgeted_amount
        for a in db.query(models.BudgetAllocation).filter(
            models.BudgetAllocation.user_id == user.id,
            models.BudgetAllocation.year == year,
            models.BudgetAllocation.month == month,
        ).all()
    }

    actuals: dict[int, Decimal] = dict(
        db.query(models.Transaction.category_id, func.sum(models.Transaction.amount))
        .filter(
            models.Transaction.user_id == user.id,
            models.Transaction.date >= start,
            models.Transaction.date <= end,
            models.Transaction.category_id.isnot(None),
        )
        .group_by(models.Transaction.category_id)
        .all()
    )

    cats = {c.id: c for c in db.query(models.Category).filter(models.Category.user_id == user.id).all()}
    rows = []
    for cat_id in sorted(set(allocs) | set(actuals)):
        cat = cats.get(cat_id)
        if not cat:
            continue
        budgeted = allocs.get(cat_id, Decimal("0"))
        actual = actuals.get(cat_id, Decimal("0"))
        rows.append({
            "category": cat.name,
            "type": cat.type.value,
            "budgeted": str(budgeted),
            "actual": str(actual),
            "variance": str(budgeted - actual),
        })

    filename = f"budget-{year}-{month:02d}"

    if format == "json":
        return StreamingResponse(
            io.StringIO(json.dumps(rows, indent=2)),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename={filename}.json"},
        )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Category", "Type", "Budgeted", "Actual", "Variance"])
    for r in rows:
        writer.writerow([r["category"], r["type"], r["budgeted"], r["actual"], r["variance"]])
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}.csv"},
    )
