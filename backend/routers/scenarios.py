from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend import models, schemas
from backend.dependencies import get_db, get_current_user

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


@router.post("", response_model=schemas.ScenarioOut)
def create_scenario(body: schemas.ScenarioCreate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    scenario = models.ForecastScenario(user_id=user.id, name=body.name)
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
    override = db.query(models.ScenarioOverride).filter(
        models.ScenarioOverride.id == override_id,
        models.ScenarioOverride.scenario_id == scenario_id,
    ).first()
    if not override:
        raise HTTPException(404, "Override not found")
    db.delete(override)
    db.commit()
    return {"ok": True}
