"""The "Needs a home" inbox: recurring charges that are uncategorized,
repeating but untracked, or probably entered twice -- plus the actions that
resolve them. Classification feeds reporting, so an unknown here is an
unknown in every rollup until it is answered.
"""
from __future__ import annotations
import re
from decimal import Decimal
from sqlalchemy.orm import Session
from backend import models, schemas
from backend.services.auto_categorizer import categorize
from backend.services.merchant_normalizer import normalize_merchant
from backend.services.recurring_detector import detect_patterns
from backend.services.recurring_math import monthly_equivalent
from backend.services.rules_engine import apply_rules

_WORD = re.compile(r"[a-z]{4,}")
DUPLICATE_AMOUNT_TOLERANCE = Decimal("0.10")


def guess_category(
    text: str,
    categories: list[models.Category],
    rules: list[models.TransactionRule],
) -> models.Category | None:
    """User rules first (they encode a decision already made), then the
    keyword table. No match returns None: a blank picker beats a wrong guess
    someone clicks through."""
    if not text:
        return None
    match = apply_rules(text, rules)
    if match and match.category_id and not match.is_transfer:
        hit = next((c for c in categories if c.id == match.category_id), None)
        if hit:
            return hit
    return categorize(text, categories)


def duplicate_pair_key(a_id: int, b_id: int) -> str:
    lo, hi = sorted((a_id, b_id))
    return f"dup:{lo}:{hi}"


def _first_word(name: str) -> str | None:
    m = _WORD.search(normalize_merchant(name).lower())
    return m.group(0) if m else None


def _expense_categories(db: Session, user_id: int) -> list[models.Category]:
    return db.query(models.Category).filter(
        models.Category.user_id == user_id,
        models.Category.type == models.CategoryType.expense,
    ).all()


def _rules(db: Session, user_id: int) -> list[models.TransactionRule]:
    return db.query(models.TransactionRule).filter(
        models.TransactionRule.user_id == user_id,
        models.TransactionRule.is_active == True,
    ).all()


def _latest_linked(db: Session, item_id: int) -> models.Transaction | None:
    return (
        db.query(models.Transaction)
        .filter(models.Transaction.recurring_item_id == item_id)
        .order_by(models.Transaction.date.desc())
        .first()
    )


def _item_out(db, item, categories, rules, with_guess: bool) -> schemas.TriageItem:
    guess = None
    if with_guess:
        guess = guess_category(item.name, categories, rules)
        if guess is None:
            latest = _latest_linked(db, item.id)
            guess = guess_category(latest.description, categories, rules) if latest else None
    return schemas.TriageItem(
        recurring_item_id=item.id, name=item.name, amount=item.amount,
        frequency=item.frequency, monthly_amount=monthly_equivalent(item),
        card_id=item.card_id,
        guess_category_id=guess.id if guess else None,
        guess_category_name=guess.name if guess else None,
    )


def _dismissed_keys(db: Session, user_id: int) -> set[str]:
    return {
        k for (k,) in db.query(models.RecurringDismissal.pattern_key)
        .filter(models.RecurringDismissal.user_id == user_id).all()
    }


def _find_duplicates(items: list[models.RecurringItem], dismissed: set[str]):
    """Heuristic flag only -- same frequency, amounts within 10%, same first
    significant word. The user decides; nothing is merged automatically."""
    pairs = []
    for i, a in enumerate(items):
        for b in items[i + 1:]:
            if a.frequency != b.frequency:
                continue
            wa, wb = _first_word(a.name), _first_word(b.name)
            if not wa or wa != wb:
                continue
            hi, lo = max(a.amount, b.amount), min(a.amount, b.amount)
            if hi <= 0 or (hi - lo) / hi > DUPLICATE_AMOUNT_TOLERANCE:
                continue
            key = duplicate_pair_key(a.id, b.id)
            if key not in dismissed:
                pairs.append((key, a, b))
    return pairs


def build_triage(db: Session, user_id: int) -> schemas.TriageOut:
    categories = _expense_categories(db, user_id)
    cat_ids = {c.id for c in categories}
    rules = _rules(db, user_id)
    dismissed = _dismissed_keys(db, user_id)

    items = db.query(models.RecurringItem).filter(
        models.RecurringItem.user_id == user_id,
        models.RecurringItem.type == models.RecurringType.expense,
        models.RecurringItem.is_active == True,
    ).order_by(models.RecurringItem.id).all()

    uncategorized = [i for i in items if i.category_id is None or i.category_id not in cat_ids]
    uncategorized_out = [_item_out(db, i, categories, rules, with_guess=True) for i in uncategorized]

    untracked = []
    for s in detect_patterns(db, user_id):
        guess = guess_category(s.description, categories, rules)
        untracked.append(schemas.TriageSuggestion(
            pattern_key=s.pattern_key, description=s.description,
            median_amount=s.median_amount, frequency=s.frequency, occurrences=s.occurrences,
            guess_category_id=guess.id if guess else None,
            guess_category_name=guess.name if guess else None,
        ))

    duplicates = [
        schemas.TriageDuplicate(
            pair_key=key,
            a=_item_out(db, a, categories, rules, with_guess=False),
            b=_item_out(db, b, categories, rules, with_guess=False),
        )
        for key, a, b in _find_duplicates(items, dismissed)
    ]

    return schemas.TriageOut(
        uncategorized=uncategorized_out,
        untracked=untracked,
        duplicates=duplicates,
        unclassified_count=len(uncategorized),
        unclassified_monthly_total=sum((o.monthly_amount for o in uncategorized_out), Decimal("0")),
    )
