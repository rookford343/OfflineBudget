from datetime import date
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend import models, schemas
from backend.dependencies import get_db, get_current_user

router = APIRouter(prefix="/net-worth", tags=["net-worth"])


@router.get("/assets", response_model=list[schemas.ManualAssetOut])
def list_assets(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return db.query(models.ManualAsset).filter(models.ManualAsset.user_id == user.id).all()


@router.get("/liabilities", response_model=list[schemas.ManualLiabilityOut])
def list_liabilities(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return db.query(models.ManualLiability).filter(models.ManualLiability.user_id == user.id).all()


@router.post("/assets", response_model=schemas.ManualAssetOut)
def create_asset(body: schemas.ManualAssetCreate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    asset = models.ManualAsset(user_id=user.id, **body.model_dump())
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


@router.patch("/assets/{asset_id}", response_model=schemas.ManualAssetOut)
def update_asset(asset_id: int, body: schemas.ManualAssetUpdate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    asset = db.query(models.ManualAsset).filter(models.ManualAsset.id == asset_id, models.ManualAsset.user_id == user.id).first()
    if not asset:
        raise HTTPException(404, "Asset not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(asset, k, v)
    db.commit()
    db.refresh(asset)
    return asset


@router.delete("/assets/{asset_id}")
def delete_asset(asset_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    asset = db.query(models.ManualAsset).filter(models.ManualAsset.id == asset_id, models.ManualAsset.user_id == user.id).first()
    if not asset:
        raise HTTPException(404, "Asset not found")
    db.delete(asset)
    db.commit()
    return {"ok": True}


@router.post("/liabilities", response_model=schemas.ManualLiabilityOut)
def create_liability(body: schemas.ManualLiabilityCreate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    liability = models.ManualLiability(user_id=user.id, **body.model_dump())
    db.add(liability)
    db.commit()
    db.refresh(liability)
    return liability


@router.patch("/liabilities/{liability_id}", response_model=schemas.ManualLiabilityOut)
def update_liability(liability_id: int, body: schemas.ManualLiabilityUpdate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    liability = db.query(models.ManualLiability).filter(models.ManualLiability.id == liability_id, models.ManualLiability.user_id == user.id).first()
    if not liability:
        raise HTTPException(404, "Liability not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(liability, k, v)
    db.commit()
    db.refresh(liability)
    return liability


@router.delete("/liabilities/{liability_id}")
def delete_liability(liability_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    liability = db.query(models.ManualLiability).filter(models.ManualLiability.id == liability_id, models.ManualLiability.user_id == user.id).first()
    if not liability:
        raise HTTPException(404, "Liability not found")
    db.delete(liability)
    db.commit()
    return {"ok": True}


@router.get("", response_model=schemas.NetWorthTotals)
def get_totals(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    assets = db.query(models.ManualAsset).filter(models.ManualAsset.user_id == user.id).all()
    liabilities = db.query(models.ManualLiability).filter(models.ManualLiability.user_id == user.id).all()
    accounts = db.query(models.Account).filter(models.Account.user_id == user.id, models.Account.is_active == True).all()
    cards = db.query(models.CreditCard).filter(models.CreditCard.user_id == user.id, models.CreditCard.is_active == True).all()

    total_assets = sum((a.current_value for a in assets), Decimal("0"))
    total_liabilities = sum((l.current_balance for l in liabilities), Decimal("0"))
    account_balances = sum((a.current_balance for a in accounts), Decimal("0"))
    card_balances = sum((c.current_balance for c in cards), Decimal("0"))
    net_worth = total_assets + account_balances - card_balances - total_liabilities

    return schemas.NetWorthTotals(
        total_assets=total_assets,
        account_balances=account_balances,
        card_balances=card_balances,
        total_liabilities=total_liabilities,
        net_worth=net_worth,
    )


@router.post("/snapshot", response_model=schemas.NetWorthSnapshotOut)
def capture_snapshot(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    assets = db.query(models.ManualAsset).filter(models.ManualAsset.user_id == user.id).all()
    liabilities = db.query(models.ManualLiability).filter(models.ManualLiability.user_id == user.id).all()
    accounts = db.query(models.Account).filter(models.Account.user_id == user.id, models.Account.is_active == True).all()
    cards = db.query(models.CreditCard).filter(models.CreditCard.user_id == user.id, models.CreditCard.is_active == True).all()

    total_assets = sum((a.current_value for a in assets), Decimal("0")) + sum((a.current_balance for a in accounts), Decimal("0"))
    total_liabilities = sum((l.current_balance for l in liabilities), Decimal("0")) + sum((c.current_balance for c in cards), Decimal("0"))
    net_worth = total_assets - total_liabilities

    snapshot = models.NetWorthSnapshot(
        user_id=user.id,
        snapshot_date=date.today(),
        total_assets=total_assets,
        total_liabilities=total_liabilities,
        net_worth=net_worth,
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


@router.get("/history", response_model=list[schemas.NetWorthSnapshotOut])
def get_history(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return db.query(models.NetWorthSnapshot).filter(
        models.NetWorthSnapshot.user_id == user.id
    ).order_by(models.NetWorthSnapshot.snapshot_date.asc()).all()
