from datetime import datetime
from decimal import Decimal
from typing import Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session
from backend import models
from backend import schemas
from backend.dependencies import get_db, get_current_user
from backend.services.csv_parser import parse_csv
from backend.services.auto_categorizer import categorize

router = APIRouter(prefix="/import", tags=["import"])


@router.post("/preview", response_model=schemas.ImportPreviewResponse)
async def preview_import(
    file: UploadFile = File(...),
    account_id: Optional[int] = Form(None),
    card_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    if not account_id and not card_id:
        raise HTTPException(status_code=400, detail="Provide either account_id or card_id")

    content = await file.read()
    try:
        parsed_rows = parse_csv(content)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Failed to parse CSV: {e}")

    if not parsed_rows:
        raise HTTPException(status_code=422, detail="No valid rows found in CSV")

    # Detect format from the file content
    import csv, io
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    headers = list(reader.fieldnames or [])
    from backend.services.csv_parser import detect_format
    fmt = detect_format(headers)

    # Load all user categories for auto-categorization
    all_cats = db.query(models.Category).filter(
        models.Category.user_id == user.id,
    ).all()

    preview_rows: list[schemas.ImportPreviewRow] = []
    categorized = 0

    for i, row in enumerate(parsed_rows):
        matched_cat = categorize(row.description, all_cats)
        needs_review = matched_cat is None
        if not needs_review:
            categorized += 1
        preview_rows.append(schemas.ImportPreviewRow(
            row_index=i,
            date=row.date,
            description=row.description,
            amount=row.amount,
            category_id=matched_cat.id if matched_cat else None,
            category_name=matched_cat.name if matched_cat else None,
            needs_review=needs_review,
            is_transfer=row.is_transfer,
        ))

    return schemas.ImportPreviewResponse(
        format=fmt,
        rows=preview_rows,
        stats=schemas.ImportPreviewStats(
            total=len(preview_rows),
            categorized=categorized,
            needs_review=len(preview_rows) - categorized,
        ),
    )


@router.post("/confirm", response_model=schemas.ImportConfirmResponse)
def confirm_import(
    body: schemas.ImportConfirmRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    if not body.account_id and not body.card_id:
        raise HTTPException(status_code=400, detail="Provide either account_id or card_id")

    imported = 0
    skipped = 0
    now = datetime.utcnow()

    for row in body.rows:
        if body.account_id:
            # Check for duplicate in checking transactions
            dup = db.query(models.Transaction).filter(
                models.Transaction.user_id == user.id,
                models.Transaction.account_id == body.account_id,
                models.Transaction.date == row.date,
                models.Transaction.amount == row.amount,
                models.Transaction.description == row.description,
            ).first()
            if dup:
                skipped += 1
                continue

            txn = models.Transaction(
                user_id=user.id,
                account_id=body.account_id,
                category_id=row.category_id,
                date=row.date,
                amount=row.amount,
                description=row.description,
                is_actual=True,
                source=models.TransactionSource.csv_import,
                imported_at=now,
            )
            db.add(txn)

            # Update account balance
            account = db.get(models.Account, body.account_id)
            if account and account.user_id == user.id:
                account.current_balance += row.amount

            imported += 1

        elif body.card_id:
            # Check for duplicate in card transactions
            dup = db.query(models.CreditCardTransaction).filter(
                models.CreditCardTransaction.user_id == user.id,
                models.CreditCardTransaction.card_id == body.card_id,
                models.CreditCardTransaction.date == row.date,
                models.CreditCardTransaction.amount == abs(row.amount),
                models.CreditCardTransaction.merchant == row.description,
            ).first()
            if dup:
                skipped += 1
                continue

            ct = models.CreditCardTransaction(
                card_id=body.card_id,
                user_id=user.id,
                category_id=row.category_id,
                date=row.date,
                amount=abs(row.amount),
                merchant=row.description,
                source=models.CardTransactionSource.csv_import,
            )
            db.add(ct)

            # Update card balance
            card = db.get(models.CreditCard, body.card_id)
            if card and card.user_id == user.id:
                card.current_balance += abs(row.amount)

            imported += 1

    db.commit()
    return schemas.ImportConfirmResponse(imported=imported, skipped_duplicates=skipped)
