from datetime import date
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from backend import models
from backend import schemas
from backend.dependencies import get_db, get_current_user
from backend.services.recurring_math import monthly_equivalent as _monthly_equivalent

router = APIRouter(prefix="/recurring", tags=["recurring"])


def _today() -> date:
    # Indirection so tests can pin "today" without patching the date class.
    return date.today()


def _months_until(today: date, end: date) -> int:
    """Whole months from today to `end`, floored at 0 once it has passed.

    An item already past its end date reports 0 rather than a negative --
    it is still listed (an active item past its term is worth seeing) but
    has no runway left to report.
    """
    if end <= today:
        return 0
    months = (end.year - today.year) * 12 + (end.month - today.month)
    if end.day < today.day:
        months -= 1
    return max(months, 0)


@router.get("", response_model=list[schemas.RecurringOut])
def list_recurring(
    active_only: bool = True,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    q = db.query(models.RecurringItem).filter(models.RecurringItem.user_id == user.id)
    if active_only:
        q = q.filter(models.RecurringItem.is_active == True)
    return q.order_by(models.RecurringItem.day_of_month).all()


@router.post("", response_model=schemas.RecurringOut, status_code=status.HTTP_201_CREATED)
def create_recurring(
    body: schemas.RecurringCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    _assert_account_owned(db, user.id, body.account_id)
    item = models.RecurringItem(user_id=user.id, **body.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/suggestions", response_model=list[schemas.RecurringSuggestion])
def get_suggestions(
    min_occurrences: int = 2,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    from backend.services.recurring_detector import detect_patterns
    return detect_patterns(db, user.id, min_occurrences=min_occurrences)


# Declared BEFORE /{item_id} on purpose: FastAPI matches routes in
# declaration order, so the other way round "triage" is read as an item_id
# and this endpoint 422s instead of answering.
@router.get("/triage", response_model=schemas.TriageOut)
def get_triage(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    from backend.services.recurring_triage import build_triage
    return build_triage(db, user.id)


def _triage_call(fn, *args):
    from backend.services.recurring_triage import TriageError, TriageNotFound
    try:
        return fn(*args)
    except TriageNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except TriageError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/triage/classify", response_model=schemas.TriageClassifyResult)
def triage_classify(
    body: schemas.TriageClassify,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    from backend.services.recurring_triage import classify
    return _triage_call(classify, db, user.id, body)


@router.post("/triage/dismiss")
def triage_dismiss(
    body: schemas.TriageDismiss,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    from backend.services.recurring_triage import dismiss
    _triage_call(dismiss, db, user.id, body.pattern_key)
    return {"ok": True}


@router.post("/triage/duplicate", response_model=schemas.TriageDuplicateResult)
def triage_duplicate(
    body: schemas.TriageDuplicateAction,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    from backend.services.recurring_triage import mark_duplicate
    return _triage_call(mark_duplicate, db, user.id, body.keep_id, body.deactivate_id)


# Declared BEFORE /{item_id} on purpose: FastAPI matches routes in
# declaration order, so the other way round "breakdown" is read as an
# item_id and this endpoint 422s instead of answering.
@router.get("/breakdown", response_model=schemas.RecurringBreakdown)
def get_breakdown(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Recurring commitments split by whether they ever stop.

    Answers three things at once: what life costs indefinitely (ongoing),
    what is temporary and when it frees up (ending, soonest first), and how
    much of the monthly burn is each.
    """
    items = db.query(models.RecurringItem).filter(
        models.RecurringItem.user_id == user.id,
        models.RecurringItem.is_active == True,
    ).all()
    # Scoped to this user only -- an item's category_id is looked up through
    # this dict, so a category belonging to someone else (or since deleted)
    # simply misses and the item falls into Unclassified rather than leaking
    # a foreign category's name into this user's rollup.
    categories = {
        c.id: c for c in db.query(models.Category).filter(
            models.Category.user_id == user.id,
        ).all()
    }

    today = date.today()
    ongoing: list[schemas.RecurringBreakdownItem] = []
    ending: list[schemas.RecurringBreakdownItem] = []
    ongoing_monthly = Decimal("0")
    ending_monthly = Decimal("0")
    income_monthly = Decimal("0")
    expense_monthly = Decimal("0")
    groups: dict[int | None, dict] = {}

    def _group(group_id: int | None, group_name: str) -> dict:
        return groups.setdefault(group_id, {
            "group_id": group_id, "group_name": group_name,
            "monthly": Decimal("0"), "categories": {}, "items": [],
        })

    for item in items:
        monthly = _monthly_equivalent(item)
        out = schemas.RecurringBreakdownItem(
            id=item.id, name=item.name, amount=item.amount, type=item.type,
            frequency=item.frequency, monthly_equivalent=monthly,
            end_date=item.end_date,
            months_remaining=_months_until(today, item.end_date) if item.end_date else None,
        )
        is_expense = item.type == models.RecurringType.expense
        if item.end_date:
            ending.append(out)
            if is_expense:
                ending_monthly += monthly
        else:
            ongoing.append(out)
            if is_expense:
                ongoing_monthly += monthly

        if item.type == models.RecurringType.income:
            income_monthly += monthly
        elif is_expense:
            # credit_card_payment falls through neither branch: it pays off
            # card charges already counted elsewhere, so folding it in here
            # would double-count that spending.
            expense_monthly += monthly
            cat = categories.get(item.category_id) if item.category_id else None
            if cat is None:
                g = _group(None, "Unclassified")
                g["items"].append(out)
                g["monthly"] += monthly
            elif cat.parent_id is None:
                g = _group(cat.id, cat.name)
                g["items"].append(out)
                g["monthly"] += monthly
            else:
                parent = categories.get(cat.parent_id)
                if parent is None:
                    g = _group(None, "Unclassified")
                    g["items"].append(out)
                    g["monthly"] += monthly
                else:
                    g = _group(parent.id, parent.name)
                    node = g["categories"].setdefault(cat.id, {
                        "category_id": cat.id, "category_name": cat.name,
                        "monthly": Decimal("0"), "items": [],
                    })
                    node["items"].append(out)
                    node["monthly"] += monthly
                    g["monthly"] += monthly

    ending.sort(key=lambda i: i.end_date)

    unclassified = groups.pop(None, None)
    by_category = [
        schemas.RecurringCategoryGroup(
            group_id=g["group_id"], group_name=g["group_name"], monthly=g["monthly"],
            categories=sorted(
                (schemas.RecurringCategoryNode(
                    category_id=c["category_id"], category_name=c["category_name"],
                    monthly=c["monthly"],
                    items=sorted(c["items"], key=lambda i: i.monthly_equivalent, reverse=True),
                ) for c in g["categories"].values()),
                key=lambda n: n.monthly, reverse=True,
            ),
            items=sorted(g["items"], key=lambda i: i.monthly_equivalent, reverse=True),
        )
        for g in groups.values()
    ]
    by_category.sort(key=lambda g: g.monthly, reverse=True)
    if unclassified is not None:
        by_category.append(schemas.RecurringCategoryGroup(
            group_id=None, group_name="Unclassified", monthly=unclassified["monthly"],
            categories=[],
            items=sorted(unclassified["items"], key=lambda i: i.monthly_equivalent, reverse=True),
        ))

    return schemas.RecurringBreakdown(
        ongoing=ongoing, ending=ending,
        ongoing_monthly=ongoing_monthly, ending_monthly=ending_monthly,
        income_monthly=income_monthly, expense_monthly=expense_monthly,
        by_category=by_category,
    )


@router.get("/bills-to-confirm", response_model=list[schemas.BillToConfirmOut])
def get_bills_to_confirm(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    from backend.services.bill_prompts import bills_to_confirm
    return bills_to_confirm(db, user.id, _today())


# Declared BEFORE /{item_id} on purpose: FastAPI matches routes in
# declaration order, so the other way round "month-summary" is read as an
# item_id and this endpoint 422s instead of answering.
@router.get("/month-summary", response_model=schemas.MonthSummaryOut)
def get_month_summary(
    year: int,
    month: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    if not (1 <= month <= 12):
        raise HTTPException(status_code=400, detail="month must be between 1 and 12")
    if not (1 <= year <= 9999):
        raise HTTPException(status_code=400, detail="year must be between 1 and 9999")
    from backend.services.month_summary import build_month_summary
    return build_month_summary(db, user.id, year, month)


@router.get("/{item_id}", response_model=schemas.RecurringOut)
def get_recurring(
    item_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    return _get_or_404(db, user.id, item_id)


@router.patch("/{item_id}", response_model=schemas.RecurringOut)
def update_recurring(
    item_id: int,
    body: schemas.RecurringUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    item = _get_or_404(db, user.id, item_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_recurring(
    item_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    item = _get_or_404(db, user.id, item_id)
    item.is_active = False
    db.commit()


def _get_or_404(db: Session, user_id: int, item_id: int) -> models.RecurringItem:
    item = db.query(models.RecurringItem).filter(
        models.RecurringItem.id == item_id,
        models.RecurringItem.user_id == user_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Recurring item not found")
    return item


def _assert_account_owned(db: Session, user_id: int, account_id: int) -> None:
    if not db.query(models.Account).filter(
        models.Account.id == account_id,
        models.Account.user_id == user_id,
    ).first():
        raise HTTPException(status_code=404, detail="Account not found")


@router.post("/{item_id}/link-pattern", response_model=schemas.RecurringLinkResult)
def link_pattern_to_item(
    item_id: int,
    body: schemas.RecurringLinkPattern,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Point a detected bank descriptor at a recurring item that already exists.

    A suggestion is only ever "here is a repeating descriptor" -- accepting it
    created a SECOND recurring item even when the bill was already tracked
    under a friendlier name, because raw descriptors carry biller IDs that
    never match what a person typed. Linking instead does the two things that
    were being done by hand: it files matching transactions under the existing
    item, and it leaves a rule behind so future ones classify on arrival.

    The rule is only created when the target item has a category, since
    set_category with no category is a no-op that would look like it worked.
    """
    item = _get_or_404(db, user.id, item_id)
    pattern = body.pattern

    result = schemas.RecurringLinkResult(
        category_name=item.category.name if item.category_id and item.category else None,
    )

    if item.category_id:
        existing = db.query(models.TransactionRule).filter(
            models.TransactionRule.user_id == user.id,
            models.TransactionRule.pattern == pattern,
            models.TransactionRule.category_id == item.category_id,
        ).first()
        if existing:
            result.rule_id = existing.id
        else:
            rule = models.TransactionRule(
                user_id=user.id,
                name=f"Auto: {item.name}"[:128],
                field=models.RuleField(body.field),
                pattern_type=models.RulePatternType(body.pattern_type),
                pattern=pattern,
                action=models.RuleAction.set_category,
                category_id=item.category_id,
            )
            db.add(rule)
            db.flush()
            result.rule_id = rule.id
            result.rule_created = True

    if body.backfill:
        like = f"%{pattern}%"
        # Only rows not already claimed by a recurring item: re-pointing a
        # transaction that belongs to a different bill would corrupt that
        # bill's history rather than fix this one.
        checking = db.query(models.Transaction).filter(
            models.Transaction.user_id == user.id,
            models.Transaction.recurring_item_id.is_(None),
            models.Transaction.description.ilike(like),
        ).all()
        for txn in checking:
            txn.recurring_item_id = item.id
            if item.category_id:
                txn.category_id = item.category_id
        result.linked_checking = len(checking)

        # Card rows have no recurring_item_id column, so the useful half there
        # is categorisation.
        if item.category_id:
            card_rows = db.query(models.CreditCardTransaction).filter(
                models.CreditCardTransaction.user_id == user.id,
                models.CreditCardTransaction.category_id.is_(None),
                models.CreditCardTransaction.merchant.ilike(like),
            ).all()
            for txn in card_rows:
                txn.category_id = item.category_id
            result.linked_card = len(card_rows)

    db.commit()
    return result
