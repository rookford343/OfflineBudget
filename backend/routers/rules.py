"""CRUD for user-defined transaction categorization rules."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from backend import models, schemas
from backend.dependencies import get_db, get_current_user
from backend.services.rules_engine import test_rule

router = APIRouter(prefix="/rules", tags=["rules"])


@router.get("", response_model=list[schemas.TransactionRuleOut])
def list_rules(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    return (
        db.query(models.TransactionRule)
        .filter(models.TransactionRule.user_id == user.id)
        .order_by(models.TransactionRule.priority.desc(), models.TransactionRule.id)
        .all()
    )


@router.post("", response_model=schemas.TransactionRuleOut, status_code=status.HTTP_201_CREATED)
def create_rule(
    body: schemas.TransactionRuleCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    rule = models.TransactionRule(user_id=user.id, **body.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.patch("/{rule_id}", response_model=schemas.TransactionRuleOut)
def update_rule(
    rule_id: int,
    body: schemas.TransactionRuleUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    rule = _get_or_404(db, user.id, rule_id)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(rule, field, value)
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    rule = _get_or_404(db, user.id, rule_id)
    db.delete(rule)
    db.commit()


@router.post("/test", response_model=schemas.RuleTestResponse)
def test_rule_endpoint(
    body: schemas.RuleTestRequest,
    user: models.User = Depends(get_current_user),
):
    """Live pattern test — used by the Settings UI when creating/editing rules."""
    matched = test_rule(body.pattern, body.pattern_type.value, body.description)
    return schemas.RuleTestResponse(matched=matched)


def _get_or_404(db: Session, user_id: int, rule_id: int) -> models.TransactionRule:
    rule = db.query(models.TransactionRule).filter(
        models.TransactionRule.id == rule_id,
        models.TransactionRule.user_id == user_id,
    ).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule
