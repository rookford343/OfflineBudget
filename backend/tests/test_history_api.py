"""The /history API and `changes_for` (routers/history.py, services/metric_diff.py).

Snapshots are built by hand with invented figures; no live data.
"""
import json
import time
from datetime import datetime
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import models, schemas
from backend.dependencies import get_current_user, get_db
from backend.routers import history as history_router
from backend.services import metric_history
from backend.services.metric_diff import changes_for

D = Decimal


@pytest.fixture(autouse=True)
def _pinned_zone(monkeypatch):
    monkeypatch.setenv("TZ", "America/Indiana/Indianapolis")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def _user(db, name="hist-user"):
    user = models.User(username=name, hashed_password="x", display_name=name)
    db.add(user)
    db.commit()
    return user


def _client(db, user):
    app = FastAPI()
    app.include_router(history_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _sources():
    return json.dumps({"card_pending": [], "checking_pending": [], "max_txn_id": 0, "max_card_txn_id": 0})


def _explain(amount):
    row = schemas.ExplainRow(op="start", label="Base", amount=D(amount), children=[], informational_children=[])
    return schemas.Explanation(title="T", result=D(amount), rows=[row]).model_dump_json()


def _snap(db, user, taken_at, value, key="leftover", *, explain_json=None, sources_json=None,
          calc_version=12):
    snap = models.MetricSnapshot(
        user_id=user.id, taken_at=taken_at, trigger="sync", calc_version=calc_version,
        as_of=taken_at.date(), sources_json=sources_json or _sources(),
    )
    snap.readings = [models.MetricReading(
        metric_key=key, label="Leftover", value=D(value),
        explain_json=explain_json or _explain(value),
    )]
    db.add(snap)
    db.commit()
    return snap


# 7:00 AM Eastern on Nov 2, 2026 is 12:00 UTC (EST).
T1 = datetime(2026, 11, 2, 12, 0)
T2 = datetime(2026, 11, 2, 18, 30)
T3 = datetime(2026, 11, 3, 18, 30)


def test_history_lists_changes_newest_first(db_session):
    user = _user(db_session)
    _snap(db_session, user, T1, "100.00")
    _snap(db_session, user, T2, "150.00")
    _snap(db_session, user, T3, "120.00")
    body = _client(db_session, user).get("/history/leftover").json()
    assert body["metric_key"] == "leftover"
    assert body["label"] == "Leftover"
    assert D(body["current_value"]) == D("120.00")
    assert [(D(c["old_value"]), D(c["new_value"]), D(c["delta"])) for c in body["changes"]] == [
        (D("150.00"), D("120.00"), D("-30.00")),
        (D("100.00"), D("150.00"), D("50.00")),
    ]
    newest, older = body["changes"]
    assert newest["taken_at"].startswith("2026-11-03T18:30")
    assert newest["previous_taken_at"].startswith("2026-11-02T18:30")
    assert newest["trigger"] == "sync"
    assert newest["calc_changed"] is False
    assert newest["headline"] == "Base changed" and older["headline"] == "Base changed"
    # previous snapshot is a different local day -> weekday shown
    assert newest["summary"].startswith("Leftover −$30.00 since Mon 1:30 PM")
    # same local day -> time only (7:00 AM Eastern)
    assert older["summary"].startswith("Leftover +$50.00 since 7:00 AM")
    for c in (newest, older):  # the collapsed-row label has no figure, amount or time
        assert "Leftover" not in c["headline"] and "since" not in c["headline"]
        assert all(k["head"] is None and k["items"] == [] for k in c["causes"])


def test_limit_caps_changes(db_session):
    user = _user(db_session)
    _snap(db_session, user, T1, "100.00")
    _snap(db_session, user, T2, "150.00")
    _snap(db_session, user, T3, "120.00")
    body = _client(db_session, user).get("/history/leftover?limit=1").json()
    assert len(body["changes"]) == 1
    assert _client(db_session, user).get("/history/leftover?limit=0").status_code == 422
    assert _client(db_session, user).get("/history/leftover?limit=201").status_code == 422


def test_unchanged_readings_are_not_changes(db_session):
    user = _user(db_session)
    _snap(db_session, user, T1, "100.00")
    _snap(db_session, user, T2, "100.004")
    _snap(db_session, user, T3, "100.00")
    assert changes_for(db_session, user.id, "leftover", 30) == []


def test_first_reading_has_no_change(db_session):
    user = _user(db_session)
    _snap(db_session, user, T1, "100.00")
    assert changes_for(db_session, user.id, "leftover", 30) == []
    body = _client(db_session, user).get("/history/leftover").json()
    assert body["changes"] == []
    assert D(body["current_value"]) == D("100.00")


def test_unknown_key_is_404(db_session):
    user = _user(db_session)
    _snap(db_session, user, T1, "100.00")
    assert _client(db_session, user).get("/history/safety_margin").status_code == 404


@pytest.mark.parametrize("key", ["leftover;drop", "Leftover", "card_payment:", "a" * 41, "x:1234567890"])
def test_bad_key_is_422(db_session, key):
    user = _user(db_session)
    assert _client(db_session, user).get(f"/history/{key}").status_code == 422


def test_path_traversal_key_never_reaches_the_query(db_session):
    user = _user(db_session)
    assert _client(db_session, user).get("/history/..%2Fx").status_code in (404, 422)
    assert _client(db_session, user).get("/history/%2E%2E%2Fx").status_code in (404, 422)


def test_manual_snapshot_records(db_session, monkeypatch):
    user = _user(db_session)
    calls = []

    def fake_record(db, u, trigger, **kw):
        calls.append((u.id, trigger))
        return object() if len(calls) == 1 else None

    monkeypatch.setattr(metric_history, "record_snapshot", fake_record)
    client = _client(db_session, user)
    assert client.post("/history/snapshot").json() == {"recorded": True}
    assert client.post("/history/snapshot").json() == {"recorded": False}
    assert calls == [(user.id, "manual"), (user.id, "manual")]


def test_delete_clears_only_my_history(db_session):
    mine, theirs = _user(db_session, "mine"), _user(db_session, "theirs")
    _snap(db_session, mine, T1, "100.00")
    _snap(db_session, mine, T2, "150.00")
    _snap(db_session, theirs, T1, "100.00")
    assert _client(db_session, mine).delete("/history").json() == {"deleted": 2}
    assert db_session.query(models.MetricSnapshot).filter_by(user_id=mine.id).count() == 0
    assert db_session.query(models.MetricSnapshot).filter_by(user_id=theirs.id).count() == 1
    assert db_session.query(models.MetricReading).count() == 1


def test_malformed_readings_degrade_to_inputs_changed(db_session):
    user = _user(db_session)
    _snap(db_session, user, T1, "100.00")
    _snap(db_session, user, T2, "150.00", explain_json="not json")
    _snap(db_session, user, T3, "120.00", sources_json='{"card_pending": []}')
    changes = changes_for(db_session, user.id, "leftover", 30)
    assert [(c.delta, [x.text for x in c.causes]) for c in changes] == [
        (D("-30.00"), ["inputs changed"]),
        (D("50.00"), ["inputs changed"]),
    ]
    assert "inputs changed" in changes[0].summary
    assert changes[0].headline == "Inputs changed"
    assert _client(db_session, user).get("/history/leftover").status_code == 200


@pytest.mark.parametrize("method, path", [
    ("GET", "/history/leftover"),
    ("GET", "/history/leftover/statement"),
    ("POST", "/history/snapshot"),
    ("DELETE", "/history"),
])
def test_history_routes_require_a_login(db_session, method, path):
    app = FastAPI()
    app.include_router(history_router.router)
    app.dependency_overrides[get_db] = lambda: db_session  # no auth override
    assert TestClient(app).request(method, path).status_code == 401


def test_grouped_cause_serializes_head_and_items(db_session):
    user = _user(db_session)
    card = models.CreditCard(user_id=user.id, name="Visa", credit_limit=D("5000"),
                             statement_day=20, due_day=10)
    db_session.add(card)
    db_session.commit()
    pending = [{"card_id": card.id, "card": "Visa", "external_id": f"p{n}", "merchant": m, "amount": a}
               for n, (m, a) in enumerate([("Example Insurance Co.", "250.00"), ("Grocery Store", "100.00")])]
    _snap(db_session, user, T1, "500.00", key="safety_margin", explain_json=_explain("1"))
    _snap(db_session, user, T2, "150.00", key="safety_margin", explain_json=_explain("1"), sources_json=json.dumps({
        "card_pending": pending, "checking_pending": [], "max_txn_id": 0, "max_card_txn_id": 0}))
    change = _client(db_session, user).get("/history/safety_margin").json()["changes"][0]
    assert change["headline"] == "New pending Visa charges"
    grouped = change["causes"][0]
    assert grouped["head"] == "new pending Visa charges"
    assert [(i["name"], D(i["amount"])) for i in grouped["items"]] == [
        ("Example Insurance Co.", D("250.00")), ("Grocery Store", D("100.00"))]
