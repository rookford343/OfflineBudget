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
from backend.services.merchant_normalizer import normalize_merchant, strip_descriptor_noise
from backend.services.recurring_detector import detect_patterns, transactions_for_pattern
from backend.services.recurring_math import monthly_equivalent
from backend.services.rules_engine import apply_rules

_WORD = re.compile(r"[a-z]{4,}")
DUPLICATE_AMOUNT_TOLERANCE = Decimal("0.10")
PATTERN_MAX = 256  # TransactionRule.pattern / RecurringDismissal.pattern_key width

# Names too broad to become a merchant-wide "contains" rule: "Gas" would
# claim every VEGAS and GASTROPUB charge. The item still gets classified;
# only the rule and the card-merchant backfill are skipped.
_MIN_RULE_PATTERN = 4
_GENERIC_PATTERNS = {
    "gas", "water", "hoa", "apple", "max", "bill", "payment", "service", "auto",
    "fee", "electric", "internet", "phone", "insurance", "subscription",
}


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


def rule_pattern(raw: str) -> str | None:
    """The stable, noise-free part of a descriptor to match future charges
    on, or None when it is too weak to match on safely.

    The noise-stripped words must appear together in the raw descriptor.
    When stripping removed something from the MIDDLE ("ACH DEBIT 20260903
    CITY OF ..."), what's left isn't contiguous raw text, and a fragment of
    it ("ACH DEBIT") would be a rule that claims every future ACH debit --
    so that is weak too. Runs of whitespace are matched loosely and the rule
    keeps the raw text's own spacing, so a bank's double space neither makes
    a good pattern weak nor produces a rule that can't match raw text.
    """
    words = strip_descriptor_noise(raw).split()
    if not words:
        return None
    m = re.search(r"\s+".join(re.escape(w) for w in words), raw, re.IGNORECASE)
    if m is None:
        return None
    pattern = m.group(0)[:PATTERN_MAX]
    if len(pattern) < _MIN_RULE_PATTERN or pattern.lower() in _GENERIC_PATTERNS:
        return None
    return pattern


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


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


class TriageError(Exception):
    """Request is well-formed but not allowed (-> 400)."""


class TriageNotFound(Exception):
    """Target item or pattern doesn't exist for this user (-> 404)."""


def _expense_category_or_error(db: Session, user_id: int, category_id: int) -> models.Category:
    cat = db.query(models.Category).filter(
        models.Category.id == category_id,
        models.Category.user_id == user_id,
    ).first()
    if cat is None or cat.type != models.CategoryType.expense:
        raise TriageError("category must be one of your expense categories")
    return cat


def _ensure_rule(db: Session, user_id: int, label: str, pattern: str, category_id: int) -> tuple[int, bool]:
    # Truncate before the lookup so it compares against what was stored.
    pattern = pattern[:PATTERN_MAX]
    existing = db.query(models.TransactionRule).filter(
        models.TransactionRule.user_id == user_id,
        models.TransactionRule.pattern == pattern,
        models.TransactionRule.category_id == category_id,
    ).first()
    if existing:
        return existing.id, False
    rule = models.TransactionRule(
        user_id=user_id, name=f"Auto: {label}"[:128],
        field=models.RuleField.merchant, pattern_type=models.RulePatternType.contains,
        pattern=pattern, action=models.RuleAction.set_category, category_id=category_id,
    )
    db.add(rule)
    db.flush()
    return rule.id, True


def _classify_item(db, user_id, item_id, cat) -> schemas.TriageClassifyResult:
    item = db.query(models.RecurringItem).filter(
        models.RecurringItem.id == item_id,
        models.RecurringItem.user_id == user_id,
    ).first()
    if item is None:
        raise TriageNotFound("recurring item not found")
    item.category_id = cat.id

    latest = _latest_linked(db, item.id)
    pattern = rule_pattern(latest.description if latest else item.name)
    rule_id, created = None, False
    if pattern:
        rule_id, created = _ensure_rule(db, user_id, item.name, pattern, cat.id)

    # Only rows nobody has categorized yet -- a category set by hand or by an
    # earlier rule is a decision, and this must never overwrite it.
    backfilled = 0
    for t in db.query(models.Transaction).filter(
        models.Transaction.recurring_item_id == item.id,
        models.Transaction.category_id.is_(None),
    ).all():
        t.category_id = cat.id
        backfilled += 1
    # Card rows have no recurring_item_id, so match them on merchant within
    # the item's own card -- only on a pattern strong enough to be a rule.
    if item.card_id and pattern:
        for t in db.query(models.CreditCardTransaction).filter(
            models.CreditCardTransaction.user_id == user_id,
            models.CreditCardTransaction.card_id == item.card_id,
            models.CreditCardTransaction.category_id.is_(None),
            models.CreditCardTransaction.merchant.ilike(f"%{_escape_like(pattern)}%", escape="\\"),
        ).all():
            t.category_id = cat.id
            backfilled += 1

    db.commit()
    return schemas.TriageClassifyResult(
        recurring_item_id=item.id, category_id=cat.id,
        rule_id=rule_id, rule_created=created, backfilled=backfilled,
    )


def _classify_pattern(db, user_id, pattern_key, cat) -> schemas.TriageClassifyResult:
    suggestion = next((s for s in detect_patterns(db, user_id) if s.pattern_key == pattern_key), None)
    txns = transactions_for_pattern(db, user_id, pattern_key)
    if suggestion is None or not txns:
        raise TriageNotFound("pattern not found")
    latest = max(txns, key=lambda t: t.date)

    item = models.RecurringItem(
        user_id=user_id, account_id=latest.account_id, category_id=cat.id,
        name=normalize_merchant(latest.description)[:128],
        amount=suggestion.median_amount, type=models.RecurringType.expense,
        frequency=models.RecurringFrequency(suggestion.frequency),
        day_of_month=latest.date.day, start_date=latest.date, is_active=True,
    )
    db.add(item)
    db.flush()

    backfilled = 0
    for t in txns:
        t.recurring_item_id = item.id
        if t.category_id is None:
            t.category_id = cat.id
            backfilled += 1
    pattern = rule_pattern(latest.description)
    rule_id, created = None, False
    if pattern:
        rule_id, created = _ensure_rule(db, user_id, item.name, pattern, cat.id)
    db.commit()
    return schemas.TriageClassifyResult(
        recurring_item_id=item.id, category_id=cat.id,
        rule_id=rule_id, rule_created=created, backfilled=backfilled,
    )


def classify(db: Session, user_id: int, body: schemas.TriageClassify) -> schemas.TriageClassifyResult:
    cat = _expense_category_or_error(db, user_id, body.category_id)
    if body.recurring_item_id is not None:
        return _classify_item(db, user_id, body.recurring_item_id, cat)
    return _classify_pattern(db, user_id, body.pattern_key, cat)


def dismiss(db: Session, user_id: int, pattern_key: str) -> None:
    pattern_key = pattern_key[:PATTERN_MAX]  # before the lookup, so it matches what was stored
    exists = db.query(models.RecurringDismissal).filter(
        models.RecurringDismissal.user_id == user_id,
        models.RecurringDismissal.pattern_key == pattern_key,
    ).first()
    if exists is None:
        db.add(models.RecurringDismissal(user_id=user_id, pattern_key=pattern_key))
        db.commit()


def mark_duplicate(db: Session, user_id: int, keep_id: int, deactivate_id: int) -> schemas.TriageDuplicateResult:
    if keep_id == deactivate_id:
        raise TriageError("keep_id and deactivate_id must differ")
    found = {
        i.id: i for i in db.query(models.RecurringItem).filter(
            models.RecurringItem.user_id == user_id,
            models.RecurringItem.id.in_([keep_id, deactivate_id]),
        ).all()
    }
    if len(found) != 2:
        raise TriageNotFound("recurring item not found")
    if not (found[keep_id].is_active and found[deactivate_id].is_active):
        raise TriageError("both items must be active")

    found[deactivate_id].is_active = False
    relinked = 0
    for t in db.query(models.Transaction).filter(models.Transaction.recurring_item_id == deactivate_id).all():
        t.recurring_item_id = keep_id
        relinked += 1
    db.commit()
    return schemas.TriageDuplicateResult(deactivated_id=deactivate_id, relinked=relinked)
