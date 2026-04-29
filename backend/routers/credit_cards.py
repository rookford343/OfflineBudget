from datetime import date
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from backend import models, schemas
from backend.dependencies import get_db, get_current_user

router = APIRouter(prefix="/credit-cards", tags=["credit-cards"])


@router.get("", response_model=list[schemas.CreditCardOut])
def list_cards(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    cards = db.query(models.CreditCard).filter(
        models.CreditCard.user_id == user.id,
        models.CreditCard.is_active == True,
    ).all()
    return [_enrich(c) for c in cards]


@router.post("", response_model=schemas.CreditCardOut, status_code=status.HTTP_201_CREATED)
def create_card(
    body: schemas.CreditCardCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    card = models.CreditCard(user_id=user.id, **body.model_dump())
    db.add(card)
    db.commit()
    db.refresh(card)
    return _enrich(card)


@router.get("/{card_id}", response_model=schemas.CreditCardOut)
def get_card(
    card_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    return _enrich(_get_or_404(db, user.id, card_id))


@router.patch("/{card_id}", response_model=schemas.CreditCardOut)
def update_card(
    card_id: int,
    body: schemas.CreditCardUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    card = _get_or_404(db, user.id, card_id)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(card, field, value)
    db.commit()
    db.refresh(card)
    return _enrich(card)


@router.delete("/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_card(
    card_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    card = _get_or_404(db, user.id, card_id)
    card.is_active = False
    db.commit()


@router.post("/{card_id}/payment", response_model=schemas.CreditCardPaymentOut, status_code=status.HTTP_201_CREATED)
def record_payment(
    card_id: int,
    body: schemas.CreditCardPaymentCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    card = _get_or_404(db, user.id, card_id)
    checking = db.query(models.Account).filter(
        models.Account.id == body.checking_account_id,
        models.Account.user_id == user.id,
        models.Account.is_active == True,
    ).first()
    if not checking:
        raise HTTPException(status_code=404, detail="Checking account not found")
    payment = models.CreditCardPayment(
        user_id=user.id,
        card_id=card_id,
        **body.model_dump(),
    )
    db.add(payment)
    # Deduct from checking account
    checking.current_balance -= body.amount
    # Reduce card balance_due
    card.balance_due = max(Decimal("0"), Decimal(str(card.balance_due)) - body.amount)
    db.commit()
    db.refresh(payment)
    return payment


@router.get("/{card_id}/transactions", response_model=list[schemas.CardTransactionOut])
def list_card_transactions(
    card_id: int,
    start: date | None = None,
    end: date | None = None,
    category_id: int | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    _get_or_404(db, user.id, card_id)
    q = db.query(models.CreditCardTransaction).filter(
        models.CreditCardTransaction.card_id == card_id,
        models.CreditCardTransaction.user_id == user.id,
    )
    if start:
        q = q.filter(models.CreditCardTransaction.date >= start)
    if end:
        q = q.filter(models.CreditCardTransaction.date <= end)
    if category_id:
        q = q.filter(models.CreditCardTransaction.category_id == category_id)
    return q.order_by(models.CreditCardTransaction.date.desc()).all()


@router.post("/{card_id}/transactions", response_model=schemas.CardTransactionOut, status_code=status.HTTP_201_CREATED)
def add_card_transaction(
    card_id: int,
    body: schemas.CardTransactionCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    card = _get_or_404(db, user.id, card_id)
    txn = models.CreditCardTransaction(
        card_id=card_id,
        user_id=user.id,
        source=models.CardTransactionSource.manual,
        **body.model_dump(),
    )
    db.add(txn)
    # Update current card balance
    if body.amount > 0:
        card.current_balance = Decimal(str(card.current_balance)) + body.amount
    else:
        card.current_balance = max(Decimal("0"), Decimal(str(card.current_balance)) + body.amount)
    db.commit()
    db.refresh(txn)
    return txn


@router.patch("/{card_id}/transactions/{txn_id}", response_model=schemas.CardTransactionOut)
def update_card_transaction(
    card_id: int,
    txn_id: int,
    body: schemas.CardTransactionUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    _get_or_404(db, user.id, card_id)
    txn = db.query(models.CreditCardTransaction).filter(
        models.CreditCardTransaction.id == txn_id,
        models.CreditCardTransaction.card_id == card_id,
        models.CreditCardTransaction.user_id == user.id,
    ).first()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(txn, field, value)
    db.commit()
    db.refresh(txn)
    return txn


def _get_or_404(db: Session, user_id: int, card_id: int) -> models.CreditCard:
    card = db.query(models.CreditCard).filter(
        models.CreditCard.id == card_id,
        models.CreditCard.user_id == user_id,
    ).first()
    if not card:
        raise HTTPException(status_code=404, detail="Credit card not found")
    return card


def _enrich(card: models.CreditCard) -> schemas.CreditCardOut:
    out = schemas.CreditCardOut.model_validate(card)
    if card.credit_limit and card.credit_limit > 0:
        out.utilization_pct = round(float(card.current_balance) / float(card.credit_limit) * 100, 1)
    return out
