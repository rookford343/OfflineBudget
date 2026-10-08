"""/wish-list API. Spec: docs/superpowers/specs/2026-10-07-wish-list-design.md"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from backend import models, schemas
from backend.dependencies import get_db, get_current_user
from backend.routers import scenarios as scenarios_router
from backend.services import wish_lifecycle as life
from backend.services import wish_plan

router = APIRouter(prefix="/wish-list", tags=["wish-list"])


def _today() -> date:
    # Indirection so tests can pin "today" without patching the date class.
    return date.today()


def _own(db: Session, model, obj_id: int, user: models.User):
    obj = db.get(model, obj_id)
    if obj is None or obj.user_id != user.id:
        raise HTTPException(status_code=404, detail="Not found")
    return obj


def _reject_nulls(data: dict, required: set[str]):
    """422s an explicit JSON null on a field the model stores NOT NULL. Without
    this, the setattr loops write None straight through and the eventual
    commit surfaces as an IntegrityError (500) instead of a validation error."""
    for key in required:
        if key in data and data[key] is None:
            raise HTTPException(status_code=422, detail=f"{key} can't be empty")


def _default_checking_account_id(db: Session, user: models.User) -> int | None:
    acct = db.query(models.Account).filter(
        models.Account.user_id == user.id,
        models.Account.type == models.AccountType.checking,
        models.Account.is_active == True,
    ).order_by(models.Account.id).first()
    return acct.id if acct is not None else None


def _resolve_account_id(db: Session, user: models.User, account_id: int | None) -> int:
    if account_id is None:
        resolved = _default_checking_account_id(db, user)
        if resolved is None:
            raise HTTPException(status_code=404, detail="No checking account found")
        return resolved
    acct = db.get(models.Account, account_id)
    if acct is None or acct.user_id != user.id or acct.type != models.AccountType.checking:
        raise HTTPException(status_code=404, detail="Account not found")
    return account_id


def _not_committed(item: models.WishItem, verb: str = "editing"):
    if item.scenario.status == "committed":
        raise HTTPException(status_code=409, detail=f"Uncommit this wish before {verb} it")


def _check_card(db: Session, user: models.User, card_id: int | None):
    if card_id is not None:
        card = db.get(models.CreditCard, card_id)
        if card is None or card.user_id != user.id:
            raise HTTPException(status_code=422, detail="Unknown card")


def _validate_option(opt: models.WishOption) -> None:
    if opt.method == models.WishMethod.financed:
        if opt.months is None or not (1 <= opt.months <= 84):
            raise ValueError("A financed option needs months between 1 and 84")
        if opt.apr is None or opt.apr < 0:
            raise ValueError("A financed option needs an apr of 0 or more")
    elif opt.method == models.WishMethod.full_card:
        if opt.card_id is None:
            raise ValueError("A full_card option needs a card")


def _item_row(item: models.WishItem) -> dict:
    return {
        "id": item.id, "scenario_id": item.scenario_id, "name": item.scenario.name,
        "rank": item.rank, "status": item.scenario.status, "price": item.price,
        "trade_in_value": item.trade_in_value, "trade_in_on": item.trade_in_on,
        "target_date": item.target_date, "plan_option_id": item.plan_option_id,
    }


# ── Plan / cushion ───────────────────────────────────────────────────────────

@router.get("/plan", response_model=schemas.WishPlanOut)
def get_plan(account_id: int | None = Query(None), db: Session = Depends(get_db),
             user: models.User = Depends(get_current_user)):
    account_id = _resolve_account_id(db, user, account_id)
    life.ensure_wish_items(db, user.id)
    db.commit()
    return wish_plan.build_plan(db, user, account_id, _today())


@router.get("/cushion", response_model=schemas.CushionOut)
def get_cushion(account_id: int | None = Query(None), db: Session = Depends(get_db),
                user: models.User = Depends(get_current_user)):
    account_id = _resolve_account_id(db, user, account_id)
    return {"cushion": wish_plan.effective_cushion(db, user, account_id)}


@router.put("/cushion", response_model=schemas.CushionOut)
def put_cushion(body: schemas.CushionIn, account_id: int | None = Query(None),
                db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    account_id = _resolve_account_id(db, user, account_id)
    row = db.query(models.WishSettings).filter(models.WishSettings.user_id == user.id).first()
    if row is None:
        db.add(models.WishSettings(user_id=user.id, cushion=body.cushion))
    else:
        row.cushion = body.cushion
    db.commit()
    return {"cushion": wish_plan.effective_cushion(db, user, account_id)}


# ── Items ────────────────────────────────────────────────────────────────────

@router.post("/items", response_model=schemas.WishItemRowOut, status_code=201)
def create_item(body: schemas.WishItemIn, db: Session = Depends(get_db),
                user: models.User = Depends(get_current_user)):
    scenario = models.ForecastScenario(user_id=user.id, name=body.name)
    db.add(scenario)
    db.flush()
    rank = db.query(models.WishItem).filter(models.WishItem.user_id == user.id).count()
    item = models.WishItem(
        user_id=user.id, scenario_id=scenario.id, rank=rank, price=body.price,
        trade_in_value=body.trade_in_value, trade_in_on=body.trade_in_on, target_date=body.target_date,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return _item_row(item)


@router.patch("/items/{item_id}", response_model=schemas.WishItemRowOut)
def update_item(item_id: int, body: schemas.WishItemUpdate, db: Session = Depends(get_db),
                user: models.User = Depends(get_current_user)):
    item = _own(db, models.WishItem, item_id, user)
    _not_committed(item)
    data = body.model_dump(exclude_unset=True)
    _reject_nulls(data, {"name", "price", "trade_in_value"})
    if "plan_option_id" in data and data["plan_option_id"] is not None:
        opt = db.get(models.WishOption, data["plan_option_id"])
        if opt is None or opt.wish_item_id != item.id:
            raise HTTPException(status_code=422, detail="plan_option_id must belong to this item")
    name = data.pop("name", None)
    for k, v in data.items():
        setattr(item, k, v)
    if name is not None:
        item.scenario.name = name
    db.commit()
    db.refresh(item)
    return _item_row(item)


@router.delete("/items/{item_id}", status_code=204)
def delete_item(item_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    item = _own(db, models.WishItem, item_id, user)
    _not_committed(item, verb="deleting")
    scenario = item.scenario
    item.plan_option_id = None
    db.flush()
    db.delete(item)
    db.flush()
    scenarios_router.delete_scenario(scenario.id, db, user)
    return Response(status_code=204)


@router.post("/items/reorder", status_code=204)
def reorder_items(body: schemas.ReorderIn, db: Session = Depends(get_db),
                  user: models.User = Depends(get_current_user)):
    items = db.query(models.WishItem).filter(models.WishItem.user_id == user.id).all()
    current_ids = {i.id for i in items}
    if len(body.ids) != len(current_ids) or set(body.ids) != current_ids:
        raise HTTPException(status_code=422, detail="ids must be exactly this user's wish items")
    by_id = {i.id: i for i in items}
    for position, item_id in enumerate(body.ids):
        by_id[item_id].rank = position
    db.commit()
    return Response(status_code=204)


# ── Options ──────────────────────────────────────────────────────────────────

@router.post("/items/{item_id}/options", response_model=schemas.WishOptionOut, status_code=201)
def create_option(item_id: int, body: schemas.WishOptionIn, db: Session = Depends(get_db),
                  user: models.User = Depends(get_current_user)):
    item = _own(db, models.WishItem, item_id, user)
    _not_committed(item, verb="adding an option to")
    _check_card(db, user, body.card_id)
    opt = models.WishOption(user_id=user.id, wish_item_id=item.id, sort_order=len(item.options),
                            **body.model_dump())
    try:
        _validate_option(opt)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(e)) from None
    db.add(opt)
    db.commit()
    db.refresh(opt)
    return opt


@router.patch("/items/{item_id}/options/{option_id}", response_model=schemas.WishOptionOut)
def update_option(item_id: int, option_id: int, body: schemas.WishOptionUpdate,
                  db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    item = _own(db, models.WishItem, item_id, user)
    opt = db.get(models.WishOption, option_id)
    if opt is None or opt.user_id != user.id or opt.wish_item_id != item.id:
        raise HTTPException(status_code=404, detail="Not found")
    _not_committed(item, verb="editing an option on")
    data = body.model_dump(exclude_unset=True)
    _reject_nulls(data, {"label", "method", "down_payment"})
    if "card_id" in data:
        _check_card(db, user, data["card_id"])
    for k, v in data.items():
        setattr(opt, k, v)
    try:
        _validate_option(opt)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(e)) from None
    db.commit()
    db.refresh(opt)
    return opt


@router.delete("/items/{item_id}/options/{option_id}", status_code=204)
def delete_option(item_id: int, option_id: int, db: Session = Depends(get_db),
                  user: models.User = Depends(get_current_user)):
    item = _own(db, models.WishItem, item_id, user)
    opt = db.get(models.WishOption, option_id)
    if opt is None or opt.user_id != user.id or opt.wish_item_id != item.id:
        raise HTTPException(status_code=404, detail="Not found")
    _not_committed(item, verb="deleting an option on")
    if item.plan_option_id == opt.id:
        item.plan_option_id = None
        db.flush()
    db.delete(opt)
    db.commit()
    return Response(status_code=204)


# ── Commit / uncommit ────────────────────────────────────────────────────────

@router.post("/items/{item_id}/commit", response_model=schemas.WishCommitOut)
def commit_item(item_id: int, account_id: int | None = Query(None), db: Session = Depends(get_db),
                user: models.User = Depends(get_current_user)):
    _own(db, models.WishItem, item_id, user)
    account_id = _resolve_account_id(db, user, account_id)
    try:
        return life.commit_wish(db, user, account_id, item_id, _today())
    except life.WishError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None


@router.post("/items/{item_id}/uncommit")
def uncommit_item(item_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    _own(db, models.WishItem, item_id, user)
    try:
        return life.uncommit_wish(db, user, item_id)
    except life.WishError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
