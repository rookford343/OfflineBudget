"""Export transactions and budget reports to CSV or JSON."""
from __future__ import annotations
import csv
import io
import json
from datetime import date
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
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
    # The same rows the Budget page shows: budgets plus real spending from the
    # one real-spending rule (cards included; transfers and card payments
    # excluded; refunds netted). The export never sums transactions itself.
    from backend.services.budget_calculator import compute_overview
    overview = compute_overview(db, user.id, year, month)
    by_id = {r.category_id: r for r in overview}
    parents_of_children = {r.parent_id for r in overview if r.parent_id in by_id}

    def label(r) -> str:
        # "Parent / Child": the flat file has no hierarchy column.
        names = [r.category_name]
        while r.parent_id in by_id:
            r = by_id[r.parent_id]
            names.append(r.category_name)
        return " / ".join(reversed(names))

    # A parent row's actual already includes its subcategories (the Budget page
    # rolls them up), so summing a column over every row would count them twice.
    # Sum the rows with no parent, or the rows not flagged "Includes subcategories".
    rows = [
        {
            "category": label(r),
            "type": r.category_type,
            "budgeted": str(r.budgeted),
            "actual": str(r.actual_total),
            "variance": str(r.variance),
            "includes_subcategories": "yes" if r.category_id in parents_of_children else "",
        }
        for r in overview
        if r.budgeted != 0 or r.actual_total != 0
    ]

    filename = f"budget-{year}-{month:02d}"

    if format == "json":
        return StreamingResponse(
            io.StringIO(json.dumps(rows, indent=2)),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename={filename}.json"},
        )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Category", "Type", "Budgeted", "Actual", "Variance", "Includes subcategories"])
    for r in rows:
        writer.writerow([r["category"], r["type"], r["budgeted"], r["actual"], r["variance"],
                         r["includes_subcategories"]])
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}.csv"},
    )
