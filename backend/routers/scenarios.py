from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from backend import models, schemas
from backend.dependencies import get_db, get_current_user
from backend.services import scenario_service

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


@router.post("", response_model=schemas.ScenarioOut)
def create_scenario(body: schemas.ScenarioCreate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    scenario = models.ForecastScenario(user_id=user.id, name=body.name, notes=body.notes)
    db.add(scenario)
    db.commit()
    db.refresh(scenario)
    return scenario


@router.get("", response_model=list[schemas.ScenarioOut])
def list_scenarios(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return db.query(models.ForecastScenario).filter(
        models.ForecastScenario.user_id == user.id
    ).order_by(models.ForecastScenario.created_at.asc()).all()


@router.patch("/{scenario_id}", response_model=schemas.ScenarioOut)
def update_scenario(scenario_id: int, body: schemas.ScenarioUpdate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    scenario = db.query(models.ForecastScenario).filter(
        models.ForecastScenario.id == scenario_id,
        models.ForecastScenario.user_id == user.id,
    ).first()
    if not scenario:
        raise HTTPException(404, "Scenario not found")
    if body.name is not None:
        scenario.name = body.name
    if body.notes is not None:
        scenario.notes = body.notes
    db.commit()
    db.refresh(scenario)
    return scenario


@router.delete("/{scenario_id}")
def delete_scenario(scenario_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    scenario = db.query(models.ForecastScenario).filter(
        models.ForecastScenario.id == scenario_id,
        models.ForecastScenario.user_id == user.id,
    ).first()
    if not scenario:
        raise HTTPException(404, "Scenario not found")
    if scenario.status == "committed":
        raise HTTPException(409, "Uncommit this scenario before deleting it")
    db.delete(scenario)
    db.commit()
    return {"ok": True}


@router.post("/{scenario_id}/overrides", response_model=schemas.ScenarioOverrideOut)
def create_override(scenario_id: int, body: schemas.ScenarioOverrideCreate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    scenario = db.query(models.ForecastScenario).filter(
        models.ForecastScenario.id == scenario_id,
        models.ForecastScenario.user_id == user.id,
    ).first()
    if not scenario:
        raise HTTPException(404, "Scenario not found")
    duplicate = db.query(models.ScenarioOverride).filter(
        models.ScenarioOverride.scenario_id == scenario_id,
        models.ScenarioOverride.recurring_item_id == body.recurring_item_id,
    ).first()
    if duplicate is not None:
        raise HTTPException(409, "This scenario already has an amount tweak on that item")
    override = models.ScenarioOverride(
        scenario_id=scenario_id,
        recurring_item_id=body.recurring_item_id,
        amount_delta=body.amount_delta,
    )
    db.add(override)
    db.commit()
    db.refresh(override)
    return override


@router.delete("/{scenario_id}/overrides/{override_id}")
def delete_override(scenario_id: int, override_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    scenario = db.query(models.ForecastScenario).filter(
        models.ForecastScenario.id == scenario_id,
        models.ForecastScenario.user_id == user.id,
    ).first()
    if not scenario:
        raise HTTPException(404, "Scenario not found")
    if scenario.status == "committed":
        raise HTTPException(409, "Uncommit this scenario before deleting an override")
    override = db.query(models.ScenarioOverride).filter(
        models.ScenarioOverride.id == override_id,
        models.ScenarioOverride.scenario_id == scenario_id,
    ).first()
    if not override:
        raise HTTPException(404, "Override not found")
    db.delete(override)
    db.commit()
    return {"ok": True}


def _owned_scenario(db: Session, user_id: int, scenario_id: int) -> models.ForecastScenario:
    scenario = scenario_service.get_scenario(db, user_id, scenario_id)
    if not scenario:
        raise HTTPException(404, "Scenario not found")
    return scenario


@router.post(
    "/{scenario_id}/items",
    response_model=schemas.ScenarioProposedItemOut,
    status_code=status.HTTP_201_CREATED,
)
def create_proposed_item(
    scenario_id: int,
    body: schemas.ScenarioProposedItemCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    _owned_scenario(db, user.id, scenario_id)
    item = models.ScenarioProposedItem(scenario_id=scenario_id, **body.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{scenario_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_proposed_item(
    scenario_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    scenario = _owned_scenario(db, user.id, scenario_id)
    if scenario.status == "committed":
        raise HTTPException(409, "Uncommit this scenario before deleting it")
    item = db.query(models.ScenarioProposedItem).filter(
        models.ScenarioProposedItem.id == item_id,
        models.ScenarioProposedItem.scenario_id == scenario_id,
    ).first()
    if not item:
        raise HTTPException(404, "Proposed item not found")
    db.delete(item)
    db.commit()


@router.post(
    "/{scenario_id}/expenses",
    response_model=schemas.ScenarioProposedExpenseOut,
    status_code=status.HTTP_201_CREATED,
)
def create_proposed_expense(
    scenario_id: int,
    body: schemas.ScenarioProposedExpenseCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    _owned_scenario(db, user.id, scenario_id)
    expense = models.ScenarioProposedExpense(scenario_id=scenario_id, **body.model_dump())
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return expense


@router.delete("/{scenario_id}/expenses/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_proposed_expense(
    scenario_id: int,
    expense_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    scenario = _owned_scenario(db, user.id, scenario_id)
    if scenario.status == "committed":
        raise HTTPException(409, "Uncommit this scenario before deleting it")
    expense = db.query(models.ScenarioProposedExpense).filter(
        models.ScenarioProposedExpense.id == expense_id,
        models.ScenarioProposedExpense.scenario_id == scenario_id,
    ).first()
    if not expense:
        raise HTTPException(404, "Proposed expense not found")
    db.delete(expense)
    db.commit()


@router.post("/{scenario_id}/commit", response_model=schemas.ScenarioCommitResult)
def commit_scenario(
    scenario_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    _owned_scenario(db, user.id, scenario_id)
    try:
        return scenario_service.commit_scenario(db, user.id, scenario_id)
    except scenario_service.ScenarioAlreadyCommitted:
        raise HTTPException(409, "Scenario is already committed") from None
    except scenario_service.ScenarioAccountNotOwned:
        raise HTTPException(404, "Account not found") from None
    except scenario_service.ScenarioCommitConflict as e:
        raise HTTPException(
            409,
            f"Cannot commit: item '{e.item_name}' is already tweaked by committed "
            f"scenario '{e.conflicting_scenario_name}'.",
        ) from None
    except scenario_service.ScenarioDuplicateOverride as e:
        raise HTTPException(
            409,
            f"Cannot commit: this scenario has more than one amount tweak on "
            f"item '{e.item_name}'.",
        ) from None


@router.post("/{scenario_id}/uncommit", response_model=schemas.ScenarioCommitResult)
def uncommit_scenario(
    scenario_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    _owned_scenario(db, user.id, scenario_id)
    try:
        return scenario_service.uncommit_scenario(db, user.id, scenario_id)
    except scenario_service.ScenarioNotCommitted:
        raise HTTPException(409, "Scenario is not committed") from None
    except scenario_service.ScenarioUncommitBlocked as e:
        if e.is_self:
            raise HTTPException(
                409,
                "Cannot uncommit: this scenario has an amount tweak on an item "
                "it created. Remove that tweak first.",
            ) from None
        raise HTTPException(
            409,
            f"Cannot uncommit: scenario '{e.blocking_scenario_name}' has an amount "
            f"tweak on an item this scenario created. Remove that tweak first.",
        ) from None
