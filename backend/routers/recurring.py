from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from backend import models
from backend import schemas
from backend.dependencies import get_db, get_current_user

router = APIRouter(prefix="/recurring", tags=["recurring"])


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
