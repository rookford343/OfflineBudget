from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.dependencies import get_db, get_current_user
from backend.routers import forecast as forecast_router_module
from backend.schemas import ForecastEntry

ENGINE = "backend.services.forecast_baseline.build_forecast"
TODAY = "backend.routers.forecast._today"


def _client(db, user):
    app = FastAPI()
    app.include_router(forecast_router_module.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _seed(db, username="ep"):
    user = models.User(username=username, hashed_password="x", display_name="EP")
    db.add(user); db.flush()
    acct = models.Account(user_id=user.id, name="Chk", type=models.AccountType.checking,
                          current_balance=Decimal("500.00"))
    db.add(acct); db.commit()
    return user, acct


def _fake(db, u, a, s, e, **kw):
    out, d = [], s
    while d <= e:
        out.append(ForecastEntry(date=d, projected_balance=Decimal("500.00"), transactions=[]))
        d += timedelta(days=1)
    return out


def test_current_month_creates_and_returns_points(db_session):
    user, acct = _seed(db_session)
    with patch(TODAY, return_value=date(2026, 10, 2)), patch(ENGINE, side_effect=_fake):
        r = _client(db_session, user).get("/forecast/baseline", params={"account_id": acct.id, "year": 2026, "month": 10})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["taken_on"] == "2026-10-02"
    assert len(body["points"]) == 31
    assert body["points"][0] == {"date": "2026-10-01", "projected_balance": "500.00"}


def test_current_month_after_the_window_is_404(db_session):
    user, acct = _seed(db_session)
    with patch(TODAY, return_value=date(2026, 9, 28)), patch(ENGINE, side_effect=_fake) as eng:
        r = _client(db_session, user).get("/forecast/baseline", params={"account_id": acct.id, "year": 2026, "month": 9})
    assert r.status_code == 404
    assert eng.call_count == 0


def test_past_month_without_a_row_is_404_and_never_created(db_session):
    user, acct = _seed(db_session)
    with patch(TODAY, return_value=date(2026, 10, 2)), patch(ENGINE, side_effect=_fake) as eng:
        r = _client(db_session, user).get("/forecast/baseline", params={"account_id": acct.id, "year": 2026, "month": 9})
    assert r.status_code == 404
    assert eng.call_count == 0


def test_other_users_account_is_404(db_session):
    user, _ = _seed(db_session)
    _, theirs = _seed(db_session, username="other")
    with patch(TODAY, return_value=date(2026, 10, 2)), patch(ENGINE, side_effect=_fake):
        r = _client(db_session, user).get("/forecast/baseline", params={"account_id": theirs.id, "year": 2026, "month": 10})
    assert r.status_code == 404


def test_engine_failure_is_503(db_session, caplog):
    user, acct = _seed(db_session)
    with patch(TODAY, return_value=date(2026, 10, 2)), patch(ENGINE, side_effect=RuntimeError("boom")):
        r = _client(db_session, user).get("/forecast/baseline", params={"account_id": acct.id, "year": 2026, "month": 10})
    assert r.status_code == 503
    assert any("forecast baseline" in record.message for record in caplog.records if record.levelname == "ERROR")
