"""Shared import logic used by both the HTTP router and CLI."""
from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from sqlalchemy import func
from sqlalchemy.orm import Session
from backend import models, schemas
from backend.services.csv_parser import ParsedRow
from backend.services.auto_categorizer import categorize


def _try_auto_match(txn: models.Transaction, db: Session) -> None:
    """Link txn to a recurring item if amount and day-of-month are close enough."""
    recurring = db.query(models.RecurringItem).filter(
        models.RecurringItem.user_id == txn.user_id,
        models.RecurringItem.account_id == txn.account_id,
        models.RecurringItem.is_active == True,
        models.RecurringItem.type != models.RecurringType.income,
    ).all()

    txn_amount = abs(txn.amount)
    txn_day = txn.date.day

    for item in recurring:
        item_day = item.day_of_month or 28
        if abs(txn_day - item_day) > 3:
            continue
        if txn_amount == 0 or item.amount == 0:
            continue
        ratio = txn_amount / item.amount
        if 0.9 <= ratio <= 1.1:
            txn.recurring_item_id = item.id
            return


def build_preview(
    db: Session,
    user: models.User,
    parsed_rows: list[ParsedRow],
    skip_categorization: bool = False,
) -> list[schemas.ImportPreviewRow]:
    """Categorize parsed rows using transaction history and keyword rules."""
    if skip_categorization:
        return [
            schemas.ImportPreviewRow(
                row_index=i,
                date=row.date,
                description=row.description,
                amount=row.amount,
                category_id=None,
                category_name=None,
                needs_review=False,
                is_transfer=row.is_transfer,
            )
            for i, row in enumerate(parsed_rows)
        ]

    all_cats = db.query(models.Category).filter(
        models.Category.user_id == user.id,
    ).all()

    history_map: dict[str, int] = {}
    checking_hist = (
        db.query(models.Transaction.description, models.Transaction.category_id, func.count().label("cnt"))
        .filter(models.Transaction.user_id == user.id, models.Transaction.category_id.isnot(None))
        .group_by(models.Transaction.description, models.Transaction.category_id)
        .order_by(func.count().desc())
        .all()
    )
    for desc, cat_id, _ in checking_hist:
        key = desc.lower()
        if key not in history_map:
            history_map[key] = cat_id

    card_hist = (
        db.query(models.CreditCardTransaction.merchant, models.CreditCardTransaction.category_id, func.count().label("cnt"))
        .filter(models.CreditCardTransaction.user_id == user.id, models.CreditCardTransaction.category_id.isnot(None))
        .group_by(models.CreditCardTransaction.merchant, models.CreditCardTransaction.category_id)
        .order_by(func.count().desc())
        .all()
    )
    for merchant, cat_id, _ in card_hist:
        key = merchant.lower()
        if key not in history_map:
            history_map[key] = cat_id

    # Load user's custom rules, sorted by priority descending
    from backend.services.rules_engine import apply_rules
    cat_by_id = {c.id: c for c in all_cats}
    user_rules = (
        db.query(models.TransactionRule)
        .filter(models.TransactionRule.user_id == user.id, models.TransactionRule.is_active == True)
        .order_by(models.TransactionRule.priority.desc())
        .all()
    )

    preview_rows: list[schemas.ImportPreviewRow] = []
    for i, row in enumerate(parsed_rows):
        # Priority: history → user rules → keyword rules
        matched_cat = categorize(row.description, all_cats, history_map)
        is_transfer = row.is_transfer

        if matched_cat is None and user_rules:
            rule_match = apply_rules(row.description, user_rules)
            if rule_match:
                if rule_match.is_transfer:
                    is_transfer = True
                elif rule_match.category_id and rule_match.category_id in cat_by_id:
                    matched_cat = cat_by_id[rule_match.category_id]

        preview_rows.append(schemas.ImportPreviewRow(
            row_index=i,
            date=row.date,
            description=row.description,
            amount=row.amount,
            category_id=matched_cat.id if matched_cat else None,
            category_name=matched_cat.name if matched_cat else None,
            needs_review=matched_cat is None and not is_transfer,
            is_transfer=is_transfer,
        ))
    return preview_rows


def run_import(
    db: Session,
    user: models.User,
    rows: list[schemas.ImportConfirmRow],
    account_id: int | None,
    card_id: int | None,
) -> schemas.ImportConfirmResponse:
    """Insert transactions, update balances, and skip duplicates."""
    imported = 0
    skipped = 0
    now = datetime.utcnow()

    for row in rows:
        if account_id:
            dup = db.query(models.Transaction).filter(
                models.Transaction.user_id == user.id,
                models.Transaction.account_id == account_id,
                models.Transaction.date == row.date,
                models.Transaction.amount == row.amount,
                models.Transaction.description == row.description,
            ).first()
            if dup:
                skipped += 1
                continue

            txn = models.Transaction(
                user_id=user.id,
                account_id=account_id,
                category_id=row.category_id,
                date=row.date,
                amount=row.amount,
                description=row.description,
                notes=row.notes,
                recurring_item_id=row.recurring_item_id,
                is_actual=True,
                source=models.TransactionSource.csv_import,
                imported_at=now,
            )
            if not row.recurring_item_id:
                _try_auto_match(txn, db)
            db.add(txn)

            account = db.get(models.Account, account_id)
            if account and account.user_id == user.id:
                account.current_balance += row.amount

            # CC payoff detection: reduce matched card's balance
            if row.is_transfer:
                desc_lower = row.description.lower()
                for card in db.query(models.CreditCard).filter_by(user_id=user.id).all():
                    name_lower = (card.name or "").lower()
                    if (name_lower and name_lower in desc_lower) or \
                       (card.last_four and card.last_four in row.description):
                        card.current_balance = max(
                            Decimal("0"),
                            Decimal(str(card.current_balance)) - abs(Decimal(str(row.amount)))
                        )
                        break

            imported += 1

        elif card_id:
            dup = db.query(models.CreditCardTransaction).filter(
                models.CreditCardTransaction.user_id == user.id,
                models.CreditCardTransaction.card_id == card_id,
                models.CreditCardTransaction.date == row.date,
                models.CreditCardTransaction.amount == abs(row.amount),
                models.CreditCardTransaction.merchant == row.description,
            ).first()
            if dup:
                skipped += 1
                continue

            ct = models.CreditCardTransaction(
                card_id=card_id,
                user_id=user.id,
                category_id=row.category_id,
                date=row.date,
                amount=abs(row.amount),
                merchant=row.description,
                source=models.CardTransactionSource.csv_import,
            )
            db.add(ct)

            card = db.get(models.CreditCard, card_id)
            if card and card.user_id == user.id:
                card.current_balance += abs(row.amount)

            imported += 1

    db.commit()
    return schemas.ImportConfirmResponse(imported=imported, skipped_duplicates=skipped)
