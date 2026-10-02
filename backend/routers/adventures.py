from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from backend import models, schemas
from backend.dependencies import get_db, get_current_user
from backend.services import adventures as adv
from backend.services import adventures_lifecycle as life

router = APIRouter(prefix="/adventures", tags=["adventures"])


def _today() -> date:
    # Indirection so tests can pin "today" without patching the date class.
    return date.today()


def _own(db: Session, model, obj_id: int, user: models.User):
    obj = db.get(model, obj_id)
    if obj is None or obj.user_id != user.id:
        raise HTTPException(status_code=404, detail="Not found")
    return obj


def _conflict(e: Exception):
    raise HTTPException(status_code=409, detail=str(e))


def _wallet_row(db, user, program_id):
    return next(r for r in adv.wallet(db, user.id, _today()) if r["id"] == program_id)


def _partner_out(p: models.TransferPartner) -> dict:
    return {"id": p.id, "from_program_id": p.from_program_id, "from_program_name": p.from_program.name,
            "to_program_id": p.to_program_id, "to_program_name": p.to_program.name,
            "ratio": p.ratio, "bonus_pct": p.bonus_pct, "bonus_ends_on": p.bonus_ends_on,
            "bonus_active": adv.bonus_active(p, _today())}


def _summary(db: Session, trip: models.Trip) -> dict:
    total = adv.trip_cash_total(trip)
    remaining = sum((adv.cash_owed(i, trip) for i in trip.items if not i.is_paid), Decimal("0"))
    pts: dict[int, int] = {}
    for i in trip.items:
        if adv.points_used(i) and i.points_program_id:
            pts[i.points_program_id] = pts.get(i.points_program_id, 0) + adv.points_used(i)
    goal = db.get(models.SavingsGoal, trip.fund_goal_id) if trip.fund_goal_id else None
    return {"id": trip.id, "name": trip.name, "destination": trip.destination,
            "start_date": trip.start_date, "end_date": trip.end_date, "travelers": trip.travelers,
            "status": trip.status, "cash_total": total, "cash_remaining": remaining,
            "points_by_program": pts, "fund_goal_id": trip.fund_goal_id,
            "fund_current": goal.current_amount if goal else None,
            "fund_target": goal.target_amount if goal else None}


def _detail(db: Session, trip: models.Trip) -> dict:
    today = _today()
    items = []
    for i in trip.items:
        items.append({
            **{k: getattr(i, k) for k in (
                "id", "category", "name", "pricing", "unit_cash", "payment", "points_program_id",
                "points_price", "cash_copay", "mix_cash", "charge_date", "card_id",
                "transfer_from_program_id", "transfer_points", "is_paid", "planned_expense_id",
                "sort_order")},
            "multiplier": adv.multiplier(i, trip), "is_auto_buffer": adv.is_auto_buffer(i),
            "cash_price": adv.cash_price(i, trip), "cash_owed": adv.cash_owed(i, trip),
            "points_used": adv.points_used(i), "value_cpp": adv.value_cpp(i, trip),
            "suggestion": adv.suggest_transfer(db, i, trip, today),
        })
    return {**_summary(db, trip), "default_card_id": trip.default_card_id, "notes": trip.notes,
            "items": items, "points_summary": list(adv.trip_points_summary(db, trip, today).values())}


def _not_done(trip: models.Trip):
    if trip.status == models.TripStatus.done:
        raise HTTPException(status_code=409, detail="Trip is done and read-only")


def _check_refs(db, user, *, program_ids=(), card_ids=()):
    for pid in program_ids:
        if pid is not None:
            p = db.get(models.LoyaltyProgram, pid)
            if p is None or p.user_id != user.id:
                raise HTTPException(status_code=422, detail="Unknown points program")
    for cid in card_ids:
        if cid is not None:
            c = db.get(models.CreditCard, cid)
            if c is None or c.user_id != user.id:
                raise HTTPException(status_code=422, detail="Unknown card")


def _reject_nulls(data: dict, required: set[str]):
    """422s an explicit JSON null on a field the model stores NOT NULL. Without
    this, the setattr loops write None straight through and the eventual
    commit surfaces as an IntegrityError (500) instead of a validation error."""
    for key in required:
        if key in data and data[key] is None:
            raise HTTPException(status_code=422, detail=f"{key} can't be empty")


# ── Wallet / programs ────────────────────────────────────────────────────────

@router.get("/wallet", response_model=list[schemas.WalletRow])
def get_wallet(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    adv.ensure_adventures_seeded(db, user.id)
    db.commit()
    return adv.wallet(db, user.id, _today())


@router.post("/programs", response_model=schemas.WalletRow, status_code=201)
def create_program(body: schemas.ProgramCreate, db: Session = Depends(get_db),
                   user: models.User = Depends(get_current_user)):
    p = models.LoyaltyProgram(user_id=user.id, name=body.name, kind=body.kind, balance=0,
                              sort_order=1000)
    db.add(p); db.commit()
    return _wallet_row(db, user, p.id)


@router.patch("/programs/{program_id}", response_model=schemas.WalletRow)
def update_program(program_id: int, body: schemas.ProgramUpdate, db: Session = Depends(get_db),
                   user: models.User = Depends(get_current_user)):
    p = _own(db, models.LoyaltyProgram, program_id, user)
    data = body.model_dump(exclude_unset=True)
    _reject_nulls(data, {"name", "balance", "is_active", "sort_order"})
    for k, v in data.items():
        setattr(p, k, v)
    if "balance" in data:
        # Local time, matching date.today() used for age_days (UTC would read
        # "-1 days ago" on US evenings).
        p.balance_updated_at = datetime.now()
    db.commit()
    return _wallet_row(db, user, p.id)


@router.delete("/programs/{program_id}", status_code=204)
def delete_program(program_id: int, db: Session = Depends(get_db),
                   user: models.User = Depends(get_current_user)):
    p = _own(db, models.LoyaltyProgram, program_id, user)
    used = db.query(models.TripItem).filter(
        models.TripItem.user_id == user.id,
        (models.TripItem.points_program_id == p.id) | (models.TripItem.transfer_from_program_id == p.id),
    ).first()
    if used:
        raise HTTPException(status_code=409, detail="Program is used by a trip item")
    db.query(models.TransferPartner).filter(
        models.TransferPartner.user_id == user.id,
        (models.TransferPartner.from_program_id == p.id) | (models.TransferPartner.to_program_id == p.id),
    ).delete(synchronize_session=False)
    db.delete(p); db.commit()
    return Response(status_code=204)


# ── Partners ─────────────────────────────────────────────────────────────────

@router.get("/partners", response_model=list[schemas.PartnerOut])
def list_partners(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    rows = db.query(models.TransferPartner).filter(models.TransferPartner.user_id == user.id).all()
    return [_partner_out(p) for p in sorted(rows, key=lambda p: (p.from_program.name, p.to_program.name))]


@router.post("/partners", response_model=schemas.PartnerOut, status_code=201)
def create_partner(body: schemas.PartnerIn, db: Session = Depends(get_db),
                   user: models.User = Depends(get_current_user)):
    if body.from_program_id == body.to_program_id:
        raise HTTPException(status_code=422, detail="A program can't transfer to itself")
    _check_refs(db, user, program_ids=(body.from_program_id, body.to_program_id))
    if adv._partner_for(db, user.id, body.from_program_id, body.to_program_id):
        raise HTTPException(status_code=409, detail="Partner already exists")
    p = models.TransferPartner(user_id=user.id, **body.model_dump())
    db.add(p); db.commit(); db.refresh(p)
    return _partner_out(p)


@router.patch("/partners/{partner_id}", response_model=schemas.PartnerOut)
def update_partner(partner_id: int, body: schemas.PartnerUpdate, db: Session = Depends(get_db),
                   user: models.User = Depends(get_current_user)):
    p = _own(db, models.TransferPartner, partner_id, user)
    data = body.model_dump(exclude_unset=True)
    _reject_nulls(data, {"ratio"})
    for k, v in data.items():
        setattr(p, k, v)
    db.commit(); db.refresh(p)
    return _partner_out(p)


@router.delete("/partners/{partner_id}", status_code=204)
def delete_partner(partner_id: int, db: Session = Depends(get_db),
                   user: models.User = Depends(get_current_user)):
    db.delete(_own(db, models.TransferPartner, partner_id, user)); db.commit()
    return Response(status_code=204)


# ── Template ─────────────────────────────────────────────────────────────────

def _template(db, user):
    return db.query(models.ChecklistTemplateItem).filter(
        models.ChecklistTemplateItem.user_id == user.id).order_by(
        models.ChecklistTemplateItem.sort_order, models.ChecklistTemplateItem.id).all()


@router.get("/template", response_model=list[schemas.TemplateItemOut])
def get_template(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return _template(db, user)


@router.post("/template", response_model=schemas.TemplateItemOut, status_code=201)
def add_template_item(body: schemas.TemplateItemIn, db: Session = Depends(get_db),
                      user: models.User = Depends(get_current_user)):
    t = models.ChecklistTemplateItem(user_id=user.id, sort_order=1000, **body.model_dump())
    db.add(t); db.commit(); db.refresh(t)
    return t


@router.delete("/template/{template_id}", status_code=204)
def delete_template_item(template_id: int, db: Session = Depends(get_db),
                         user: models.User = Depends(get_current_user)):
    db.delete(_own(db, models.ChecklistTemplateItem, template_id, user)); db.commit()
    return Response(status_code=204)


@router.post("/template/reset", response_model=list[schemas.TemplateItemOut])
def reset_template(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    db.query(models.ChecklistTemplateItem).filter(
        models.ChecklistTemplateItem.user_id == user.id).delete(synchronize_session=False)
    adv.ensure_adventures_seeded(db, user.id)
    db.commit()
    return _template(db, user)


# ── Trips ────────────────────────────────────────────────────────────────────

@router.get("/trips", response_model=list[schemas.TripSummary])
def list_trips(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    trips = db.query(models.Trip).filter(models.Trip.user_id == user.id).order_by(
        models.Trip.start_date).all()
    return [_summary(db, t) for t in trips]


@router.post("/trips", response_model=schemas.TripDetail, status_code=201)
def create_trip(body: schemas.TripCreate, db: Session = Depends(get_db),
                user: models.User = Depends(get_current_user)):
    _check_refs(db, user, card_ids=(body.default_card_id,))
    adv.ensure_adventures_seeded(db, user.id)
    try:
        trip = life.create_trip_from_template(db, user.id, **body.model_dump())
    except life.LifecycleError as e:
        raise HTTPException(status_code=422, detail=str(e))
    db.commit(); db.refresh(trip)
    return _detail(db, trip)


@router.get("/trips/{trip_id}", response_model=schemas.TripDetail)
def get_trip(trip_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return _detail(db, _own(db, models.Trip, trip_id, user))


@router.patch("/trips/{trip_id}", response_model=schemas.TripDetail)
def update_trip(trip_id: int, body: schemas.TripUpdate, db: Session = Depends(get_db),
                user: models.User = Depends(get_current_user)):
    trip = _own(db, models.Trip, trip_id, user)
    _not_done(trip)
    data = body.model_dump(exclude_unset=True)
    _reject_nulls(data, {"name", "start_date", "end_date", "travelers"})
    _check_refs(db, user, card_ids=(data.get("default_card_id"),))
    for k, v in data.items():
        setattr(trip, k, v)
    if trip.end_date < trip.start_date:
        db.rollback()
        raise HTTPException(status_code=422, detail="end date is before start date")
    life.sync_trip_planned_expenses(db, trip)
    db.commit(); db.refresh(trip)
    return _detail(db, trip)


@router.delete("/trips/{trip_id}", status_code=204)
def delete_trip(trip_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    life.delete_trip(db, _own(db, models.Trip, trip_id, user)); db.commit()
    return Response(status_code=204)


def _validate_item(db: Session, item: models.TripItem):
    """Rolls back before raising so a rejected edit never lingers in the session."""
    problem = None
    if item.payment in (models.TripPayment.points, models.TripPayment.mix):
        if not item.points_program_id or not item.points_price:
            problem = "Points items need a program and a points price"
    if item.transfer_points and not item.transfer_from_program_id:
        problem = "A transfer needs a source program"
    if problem:
        db.rollback()
        raise HTTPException(status_code=422, detail=problem)


@router.post("/trips/{trip_id}/items", response_model=schemas.TripDetail, status_code=201)
def add_item(trip_id: int, body: schemas.TripItemIn, db: Session = Depends(get_db),
             user: models.User = Depends(get_current_user)):
    trip = _own(db, models.Trip, trip_id, user)
    _not_done(trip)
    data = body.model_dump(exclude_unset=True, exclude={"is_paid"})
    if not data.get("category") or not data.get("name"):
        raise HTTPException(status_code=422, detail="category and name are required")
    _check_refs(db, user, program_ids=(data.get("points_program_id"), data.get("transfer_from_program_id")),
                card_ids=(data.get("card_id"),))
    data["cash_copay"] = data.get("cash_copay") or Decimal("0")
    item = models.TripItem(user_id=user.id, is_paid=False,
                           sort_order=len(trip.items), **data)
    _validate_item(db, item)
    trip.items.append(item)
    db.flush()
    life.sync_trip_planned_expenses(db, trip)
    db.commit(); db.refresh(trip)
    return _detail(db, trip)


@router.patch("/trips/{trip_id}/items/{item_id}", response_model=schemas.TripDetail)
def update_item(trip_id: int, item_id: int, body: schemas.TripItemIn, db: Session = Depends(get_db),
                user: models.User = Depends(get_current_user)):
    trip = _own(db, models.Trip, trip_id, user)
    item = _own(db, models.TripItem, item_id, user)
    if item.trip_id != trip.id:
        raise HTTPException(status_code=404, detail="Not found")
    _not_done(trip)
    data = body.model_dump(exclude_unset=True)
    paid = data.pop("is_paid", None)
    _reject_nulls(data, {"category", "name", "pricing", "payment"})
    _check_refs(db, user, program_ids=(data.get("points_program_id"), data.get("transfer_from_program_id")),
                card_ids=(data.get("card_id"),))
    for k, v in data.items():
        setattr(item, k, v if k != "cash_copay" or v is not None else Decimal("0"))
    _validate_item(db, item)
    db.flush()
    if paid is not None:
        life.set_item_paid(db, trip, item, paid, _today())
    life.sync_trip_planned_expenses(db, trip)
    db.commit(); db.refresh(trip)
    return _detail(db, trip)


@router.delete("/trips/{trip_id}/items/{item_id}", response_model=schemas.TripDetail)
def remove_item(trip_id: int, item_id: int, remove_from_template: bool = Query(False),
                db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    trip = _own(db, models.Trip, trip_id, user)
    item = _own(db, models.TripItem, item_id, user)
    if item.trip_id != trip.id:
        raise HTTPException(status_code=404, detail="Not found")
    _not_done(trip)
    if remove_from_template:
        db.query(models.ChecklistTemplateItem).filter(
            models.ChecklistTemplateItem.user_id == user.id,
            models.ChecklistTemplateItem.category == item.category,
            models.ChecklistTemplateItem.name == item.name,
        ).delete(synchronize_session=False)
    life.delete_item(db, trip, item)
    db.commit(); db.refresh(trip)
    return _detail(db, trip)


@router.post("/trips/{trip_id}/commit", response_model=schemas.TripDetail)
def commit(trip_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    trip = _own(db, models.Trip, trip_id, user)
    try:
        life.commit_trip(db, trip)
    except life.LifecycleError as e:
        _conflict(e)
    db.commit(); db.refresh(trip)
    return _detail(db, trip)


@router.post("/trips/{trip_id}/uncommit", response_model=schemas.TripDetail)
def uncommit(trip_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    trip = _own(db, models.Trip, trip_id, user)
    try:
        life.uncommit_trip(db, trip)
    except life.LifecycleError as e:
        _conflict(e)
    db.commit(); db.refresh(trip)
    return _detail(db, trip)


@router.get("/trips/{trip_id}/finish-plan", response_model=dict[int, int])
def finish_plan(trip_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return life.finish_plan(db, _own(db, models.Trip, trip_id, user), _today())


@router.post("/trips/{trip_id}/finish", response_model=schemas.TripDetail)
def finish(trip_id: int, body: schemas.FinishRequest, db: Session = Depends(get_db),
           user: models.User = Depends(get_current_user)):
    trip = _own(db, models.Trip, trip_id, user)
    try:
        life.finish_trip(db, trip, body.points_used_by_program, body.force, _today())
    except life.LifecycleError as e:
        db.rollback()
        _conflict(e)
    db.commit(); db.refresh(trip)
    return _detail(db, trip)


@router.post("/trips/{trip_id}/fund", response_model=schemas.TripDetail)
def create_fund(trip_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    trip = _own(db, models.Trip, trip_id, user)
    _not_done(trip)
    try:
        life.create_trip_fund(db, trip)
    except life.LifecycleError as e:
        _conflict(e)
    db.commit(); db.refresh(trip)
    return _detail(db, trip)


@router.post("/trips/{trip_id}/fund/update", response_model=schemas.TripDetail)
def update_fund(trip_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    trip = _own(db, models.Trip, trip_id, user)
    _not_done(trip)
    try:
        life.update_trip_fund_target(db, trip)
    except life.LifecycleError as e:
        _conflict(e)
    db.commit(); db.refresh(trip)
    return _detail(db, trip)


@router.delete("/trips/{trip_id}/fund", response_model=schemas.TripDetail)
def delete_fund(trip_id: int, delete_goal: bool = Query(False), db: Session = Depends(get_db),
                user: models.User = Depends(get_current_user)):
    trip = _own(db, models.Trip, trip_id, user)
    _not_done(trip)
    life.remove_trip_fund(db, trip, delete_goal)
    db.commit(); db.refresh(trip)
    return _detail(db, trip)
