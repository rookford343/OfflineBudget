from datetime import date
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from backend import models, schemas
from backend.dependencies import get_db, get_current_user
from backend.services.net_worth import net_worth_totals

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
    return net_worth_totals(db, user.id)


@router.post("/snapshot", response_model=schemas.NetWorthSnapshotOut)
def capture_snapshot(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    totals = net_worth_totals(db, user.id)
    total_assets = totals.total_assets
    total_liabilities = totals.total_liabilities
    net_worth = totals.net_worth

    # Re-capturing on a day that already has a snapshot REPLACES it rather than
    # appending a second one. A snapshot is "what I was worth on this date", so
    # two rows for one date is never a meaningful state -- it just puts a
    # vertical step in the trend line and doubles the row in history. Correcting
    # a balance and pressing the button again is the normal way to fix a
    # mistake, and it should work without a delete-then-recapture dance.
    today = date.today()
    snapshot = db.query(models.NetWorthSnapshot).filter(
        models.NetWorthSnapshot.user_id == user.id,
        models.NetWorthSnapshot.snapshot_date == today,
    ).first()
    if snapshot:
        snapshot.total_assets = total_assets
        snapshot.total_liabilities = total_liabilities
        snapshot.net_worth = net_worth
    else:
        snapshot = models.NetWorthSnapshot(
            user_id=user.id,
            snapshot_date=today,
            total_assets=total_assets,
            total_liabilities=total_liabilities,
            net_worth=net_worth,
        )
        db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


@router.delete("/snapshot/{snapshot_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_snapshot(
    snapshot_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Remove a snapshot. A wrong one distorts the trend line permanently
    otherwise -- there was no way to take one back."""
    snapshot = db.query(models.NetWorthSnapshot).filter(
        models.NetWorthSnapshot.id == snapshot_id,
        models.NetWorthSnapshot.user_id == user.id,
    ).first()
    if not snapshot:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    db.delete(snapshot)
    db.commit()


@router.get("/history", response_model=list[schemas.NetWorthSnapshotOut])
def get_history(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return db.query(models.NetWorthSnapshot).filter(
        models.NetWorthSnapshot.user_id == user.id
    ).order_by(models.NetWorthSnapshot.snapshot_date.asc()).all()
