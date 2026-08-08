"""Shared import logic used by both the HTTP router and CLI."""
from __future__ import annotations
import re
from datetime import datetime
from decimal import Decimal
from sqlalchemy import func
from sqlalchemy.orm import Session
from backend import models, schemas
from backend.services.csv_parser import ParsedRow
from backend.services.auto_categorizer import categorize
from backend.services.card_matching import card_matches_description

# ACH/bank noise suffixes to strip before matching
_ACH_NOISE = re.compile(
    r"\s+(ppd|ccd|web|tel|ctx)\s+id[:\s]*\S*$"
    r"|\s+id[:\s]*\d{6,}$"
    r"|\s+(ach|autopay|online\s+payment|direct\s+dep(osit)?)$",
    re.IGNORECASE,
)

_STOP_WORDS = {"the", "ppd", "id", "ind", "crd", "inc", "llc", "co", "a", "an"}

# Synonym collapse: normalize these to a common token before scoring
_SYNONYMS: dict[str, str] = {
    "payroll": "paycheck",
    "salary": "paycheck",
    "wages": "paycheck",
    "direct": "paycheck",
    "dep": "paycheck",
    "deposit": "paycheck",
    "autopay": "payment",
    "auto": "payment",
    "pay": "payment",
}


def _normalize_for_match(text: str) -> set[str]:
    """Return a set of normalized tokens for fuzzy name matching."""
    text = _ACH_NOISE.sub("", text)
    tokens = re.sub(r"[^a-z0-9\s]", " ", text.lower()).split()
    result: set[str] = set()
    for t in tokens:
        if t in _STOP_WORDS or len(t) < 2:
            continue
        result.add(_SYNONYMS.get(t, t))
    return result


def _name_score(txn_desc: str, item_name: str) -> int:
    """Shared-token count between normalized description and recurring item name."""
    return len(_normalize_for_match(txn_desc) & _normalize_for_match(item_name))


def _fires_near(item: models.RecurringItem, txn_date) -> bool:
    """True if this recurring item would fire within ±3 days of txn_date."""
    import calendar
    from datetime import date as date_type
    day = item.day_of_month or 28
    for month_offset in (0, -1, 1):
        m = txn_date.month + month_offset
        y = txn_date.year
        if m < 1:
            m += 12
            y -= 1
        elif m > 12:
            m -= 12
            y += 1
        last_day = calendar.monthrange(y, m)[1]
        clamped_day = min(day, last_day)
        try:
            fire_date = date_type(y, m, clamped_day)
        except ValueError:
            continue
        if abs((txn_date - fire_date).days) <= 3:
            return True
    return False


def _try_auto_match(txn: models.Transaction, db: Session) -> None:
    """Link txn to a recurring item if amount, day-of-month, and name are close enough.

    Covers income credits, expense debits, and CC payment debits — previously only
    expenses were considered, which silently dropped paycheck and autopay links.
    """
    recurring = db.query(models.RecurringItem).filter(
        models.RecurringItem.user_id == txn.user_id,
        models.RecurringItem.account_id == txn.account_id,
        models.RecurringItem.is_active == True,
    ).all()

    txn_amount = abs(txn.amount)
    txn_day = txn.date.day
    is_credit = txn.amount > 0

    best: models.RecurringItem | None = None
    best_score = -1

    for item in recurring:
        # Direction guard: income items match credits, everything else matches debits
        if item.type == models.RecurringType.income and not is_credit:
            continue
        if item.type != models.RecurringType.income and is_credit:
            continue

        item_day = item.day_of_month or 28
        if abs(txn_day - item_day) > 3:
            continue
        if txn_amount == 0 or item.amount == 0:
            continue
        ratio = txn_amount / item.amount
        if not (Decimal("0.9") <= ratio <= Decimal("1.1")):
            continue

        score = _name_score(txn.description, item.name)
        if score > best_score:
            best_score = score
            best = item

    if best is not None:
        txn.recurring_item_id = best.id


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

    from backend.services.rules_engine import apply_rules
    cat_by_id = {c.id: c for c in all_cats}
    user_rules = (
        db.query(models.TransactionRule)
        .filter(models.TransactionRule.user_id == user.id, models.TransactionRule.is_active == True)
        .order_by(models.TransactionRule.priority.desc())
        .all()
    )

    # Pre-load all active recurring items for this user once
    all_recurring = db.query(models.RecurringItem).filter(
        models.RecurringItem.user_id == user.id,
        models.RecurringItem.is_active == True,
    ).all()
    expense_recurring = [r for r in all_recurring if r.type == models.RecurringType.expense]
    income_recurring = [r for r in all_recurring if r.type == models.RecurringType.income]
    cc_payment_recurring = [r for r in all_recurring if r.type == models.RecurringType.credit_card_payment]

    def _best_suggestion(
        candidates: list[models.RecurringItem],
        row: ParsedRow,
        amount_lo: Decimal = Decimal("0.85"),
        amount_hi: Decimal = Decimal("1.15"),
    ) -> tuple[int | None, str | None]:
        txn_amount = abs(row.amount)
        best_item: models.RecurringItem | None = None
        best_score = -1
        for item in candidates:
            if item.amount <= 0 or not _fires_near(item, row.date):
                continue
            ratio = txn_amount / item.amount
            if not (amount_lo <= ratio <= amount_hi):
                continue
            score = _name_score(row.description, item.name)
            if score > best_score:
                best_score = score
                best_item = item
        if best_item:
            return best_item.id, best_item.name
        return None, None

    preview_rows: list[schemas.ImportPreviewRow] = []
    for i, row in enumerate(parsed_rows):
        matched_cat = categorize(row.description, all_cats, history_map)
        is_transfer = row.is_transfer

        if matched_cat is None and user_rules:
            rule_match = apply_rules(row.description, user_rules)
            if rule_match:
                if rule_match.is_transfer:
                    is_transfer = True
                elif rule_match.category_id and rule_match.category_id in cat_by_id:
                    matched_cat = cat_by_id[rule_match.category_id]

        suggested_item_id = None
        suggested_item_name = None

        if row.amount < 0:
            if is_transfer:
                # CC autopay and other transfer-flagged debits: check CC payment recurring items
                suggested_item_id, suggested_item_name = _best_suggestion(cc_payment_recurring, row)
            else:
                # Regular expense debit
                suggested_item_id, suggested_item_name = _best_suggestion(expense_recurring, row)
        elif row.amount > 0:
            # Credit (income)
            suggested_item_id, suggested_item_name = _best_suggestion(income_recurring, row)

        preview_rows.append(schemas.ImportPreviewRow(
            row_index=i,
            date=row.date,
            description=row.description,
            amount=row.amount,
            category_id=matched_cat.id if matched_cat else None,
            category_name=matched_cat.name if matched_cat else None,
            needs_review=matched_cat is None and not is_transfer,
            is_transfer=is_transfer,
            suggested_recurring_item_id=suggested_item_id,
            suggested_recurring_item_name=suggested_item_name,
        ))
    return preview_rows


def run_import(
    db: Session,
    user: models.User,
    rows: list[schemas.ImportConfirmRow],
    account_id: int | None,
    card_id: int | None,
    source: models.TransactionSource = models.TransactionSource.csv_import,
    card_source: models.CardTransactionSource = models.CardTransactionSource.csv_import,
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
                source=source,
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
                for card in db.query(models.CreditCard).filter_by(user_id=user.id).all():
                    if card_matches_description(card, row.description):
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
                source=card_source,
            )
            db.add(ct)

            card = db.get(models.CreditCard, card_id)
            if card and card.user_id == user.id:
                # Sales are negative (increase what's owed), returns/credits are
                # positive (decrease it) -- subtracting the signed amount handles both.
                card.current_balance -= row.amount

            imported += 1

    db.commit()
    return schemas.ImportConfirmResponse(imported=imported, skipped_duplicates=skipped)
