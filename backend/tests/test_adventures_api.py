from datetime import date
from decimal import Decimal
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.routers import adventures as adventures_router
from backend.dependencies import get_db, get_current_user


def _client(db, user):
    app = FastAPI()
    app.include_router(adventures_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _user(db, name="api"):
    u = models.User(username=name, hashed_password="x", display_name=name)
    db.add(u); db.commit(); db.refresh(u); return u


def _new_trip(c):
    r = c.post("/adventures/trips", json={"name": "Lake", "start_date": "2027-06-01",
                                          "end_date": "2027-06-04", "travelers": 2})
    assert r.status_code == 201, r.text
    return r.json()


def test_wallet_seeds_and_balance_patch_stamps_time(db_session):
    c = _client(db_session, _user(db_session))
    rows = c.get("/adventures/wallet").json()
    assert any(r["name"] == "Chase Ultimate Rewards" for r in rows)
    pid = rows[0]["id"]
    r = c.patch(f"/adventures/programs/{pid}", json={"balance": 12345}).json()
    assert r["balance"] == 12345 and r["balance_updated_at"] is not None and r["age_days"] == 0


def test_trip_create_copies_template_and_reports_derived_fields(db_session):
    c = _client(db_session, _user(db_session))
    c.get("/adventures/wallet")
    t = _new_trip(c)
    assert t["status"] == "planning" and len(t["items"]) == 18
    food = next(i for i in t["items"] if i["name"] == "Food")
    r = c.patch(f"/adventures/trips/{t['id']}/items/{food['id']}", json={"unit_cash": "20.00"}).json()
    food = next(i for i in r["items"] if i["name"] == "Food")
    assert food["multiplier"] == 8 and Decimal(food["cash_owed"]) == Decimal("160.00")
    assert Decimal(r["cash_total"]) == Decimal("176.00")   # + 10% buffer


def test_points_item_validation_and_commit_flow(db_session):
    u = _user(db_session)
    c = _client(db_session, u)
    wallet = c.get("/adventures/wallet").json()
    virgin = next(r for r in wallet if r["name"] == "Virgin Atlantic Flying Club")
    t = _new_trip(c)
    flights = next(i for i in t["items"] if i["name"] == "Flights")
    bad = c.patch(f"/adventures/trips/{t['id']}/items/{flights['id']}", json={"payment": "points"})
    assert bad.status_code == 422
    r = c.patch(f"/adventures/trips/{t['id']}/items/{flights['id']}",
                json={"payment": "points", "points_program_id": virgin["id"], "points_price": 70000,
                      "cash_copay": "50.00", "unit_cash": "600.00"}).json()
    f = next(i for i in r["items"] if i["name"] == "Flights")
    assert Decimal(f["value_cpp"]) == Decimal("1.64") and f["suggestion"] is None  # no Chase balance
    assert c.post(f"/adventures/trips/{t['id']}/commit").json()["status"] == "committed"
    assert c.post(f"/adventures/trips/{t['id']}/commit").status_code == 409
    pes = db_session.query(models.PlannedExpense).filter_by(user_id=u.id).all()
    assert {pe.name for pe in pes} == {"Lake: Flights", "Lake: Buffer"}


def test_suggestion_appears_and_can_be_attached(db_session):
    c = _client(db_session, _user(db_session))
    wallet = c.get("/adventures/wallet").json()
    chase = next(r for r in wallet if r["name"] == "Chase Ultimate Rewards")
    virgin = next(r for r in wallet if r["name"] == "Virgin Atlantic Flying Club")
    c.patch(f"/adventures/programs/{chase['id']}", json={"balance": 100000})
    partner = next(p for p in c.get("/adventures/partners").json() if p["to_program_id"] == virgin["id"])
    c.patch(f"/adventures/partners/{partner['id']}", json={"bonus_pct": "30"})
    t = _new_trip(c)
    flights = next(i for i in t["items"] if i["name"] == "Flights")
    r = c.patch(f"/adventures/trips/{t['id']}/items/{flights['id']}",
                json={"payment": "points", "points_program_id": virgin["id"], "points_price": 70000,
                      "unit_cash": "600.00"}).json()
    s = next(i for i in r["items"] if i["name"] == "Flights")["suggestion"]
    assert s["from_program_id"] == chase["id"] and s["source_points"] == 53847
    r = c.patch(f"/adventures/trips/{t['id']}/items/{flights['id']}",
                json={"transfer_from_program_id": chase["id"], "transfer_points": 53847}).json()
    summary = {row["program_id"]: row for row in r["points_summary"]}
    assert summary[virgin["id"]]["shortfall"] == 0


def test_remove_item_from_template_too(db_session):
    c = _client(db_session, _user(db_session))
    c.get("/adventures/wallet")
    t = _new_trip(c)
    dog = next(i for i in t["items"] if i["name"] == "Dog boarding")
    r = c.delete(f"/adventures/trips/{t['id']}/items/{dog['id']}", params={"remove_from_template": "true"})
    assert all(i["name"] != "Dog boarding" for i in r.json()["items"])
    assert all(x["name"] != "Dog boarding" for x in c.get("/adventures/template").json())
    assert len(c.post("/adventures/template/reset").json()) == 18


def test_finish_and_done_is_read_only(db_session):
    c = _client(db_session, _user(db_session))
    c.get("/adventures/wallet")
    t = _new_trip(c)
    c.post(f"/adventures/trips/{t['id']}/commit")
    assert c.post(f"/adventures/trips/{t['id']}/finish", json={}).json()["status"] == "done"
    item = t["items"][0]
    assert c.patch(f"/adventures/trips/{t['id']}/items/{item['id']}", json={"unit_cash": "1"}).status_code == 409


def test_fund_endpoints(db_session):
    c = _client(db_session, _user(db_session))
    c.get("/adventures/wallet")
    t = _new_trip(c)
    r = c.post(f"/adventures/trips/{t['id']}/fund").json()
    assert r["fund_goal_id"] is not None and Decimal(r["fund_target"]) == Decimal("0.00")
    assert c.delete(f"/adventures/trips/{t['id']}/fund", params={"delete_goal": "true"}).json()["fund_goal_id"] is None


def test_everything_is_user_scoped(db_session):
    a, b = _user(db_session, "a"), _user(db_session, "b")
    ca, cb = _client(db_session, a), _client(db_session, b)
    ca.get("/adventures/wallet")
    t = _new_trip(ca)
    pid = ca.get("/adventures/wallet").json()[0]["id"]
    assert cb.get(f"/adventures/trips/{t['id']}").status_code == 404
    assert cb.patch(f"/adventures/programs/{pid}", json={"balance": 1}).status_code == 404
    assert cb.get("/adventures/trips").json() == []
    item = t["items"][0]
    assert cb.delete(f"/adventures/trips/{t['id']}/items/{item['id']}").status_code == 404


def test_finish_rejects_negative_confirmed_points(db_session):
    c = _client(db_session, _user(db_session))
    c.get("/adventures/wallet")
    t = _new_trip(c)
    r = c.post(f"/adventures/trips/{t['id']}/commit")
    assert r.status_code == 200, r.text
    pid = c.get("/adventures/wallet").json()[0]["id"]
    r = c.post(f"/adventures/trips/{t['id']}/finish", json={"points_used_by_program": {str(pid): -1}})
    assert r.status_code == 422, r.text


# ── Fix round 1 ──────────────────────────────────────────────────────────────

def test_add_item_with_cash_copay_does_not_500(db_session):
    """I1: TripItem(..., cash_copay=Decimal('0'), **data) used to blow up with
    'multiple values for keyword argument cash_copay' whenever the POST body
    included cash_copay -- a 500, not a validation error."""
    c = _client(db_session, _user(db_session))
    wallet = c.get("/adventures/wallet").json()
    virgin = next(r for r in wallet if r["name"] == "Virgin Atlantic Flying Club")
    t = _new_trip(c)

    r = c.post(f"/adventures/trips/{t['id']}/items", json={
        "category": "while_there", "name": "Extra flight", "payment": "points",
        "points_program_id": virgin["id"], "points_price": 10000, "cash_copay": "12.50",
    })
    assert r.status_code == 201, r.text
    item = next(i for i in r.json()["items"] if i["name"] == "Extra flight")
    assert Decimal(item["cash_owed"]) == Decimal("12.50")

    r2 = c.post(f"/adventures/trips/{t['id']}/items", json={
        "category": "while_there", "name": "Snacks", "unit_cash": "5.00",
    })
    assert r2.status_code == 201, r2.text
    assert any(i["name"] == "Snacks" for i in r2.json()["items"])


def test_delete_partner_used_by_an_attached_transfer_is_409(db_session):
    """I3: mirrors delete_program -- a partner an item's attached transfer
    points at (transfer_from_program_id -> points_program_id) can't be
    deleted out from under that item. An unused partner still deletes fine."""
    c = _client(db_session, _user(db_session))
    wallet = c.get("/adventures/wallet").json()
    chase = next(r for r in wallet if r["name"] == "Chase Ultimate Rewards")
    virgin = next(r for r in wallet if r["name"] == "Virgin Atlantic Flying Club")
    hyatt = next(r for r in wallet if r["name"] == "World of Hyatt")
    partners = c.get("/adventures/partners").json()
    used_partner = next(p for p in partners if p["from_program_id"] == chase["id"] and p["to_program_id"] == virgin["id"])
    unused_partner = next(p for p in partners if p["from_program_id"] == chase["id"] and p["to_program_id"] == hyatt["id"])

    t = _new_trip(c)
    flights = next(i for i in t["items"] if i["name"] == "Flights")
    r = c.patch(f"/adventures/trips/{t['id']}/items/{flights['id']}",
                json={"payment": "points", "points_program_id": virgin["id"], "points_price": 70000,
                      "unit_cash": "600.00", "transfer_from_program_id": chase["id"], "transfer_points": 70000})
    assert r.status_code == 200, r.text

    bad = c.delete(f"/adventures/partners/{used_partner['id']}")
    assert bad.status_code == 409, bad.text
    assert bad.json()["detail"] == "Partner is used by a trip item's transfer"

    ok = c.delete(f"/adventures/partners/{unused_partner['id']}")
    assert ok.status_code == 204, ok.text


def test_patch_rejects_explicit_null_on_required_fields(db_session):
    """I2: an explicit JSON null on a NOT NULL field used to sail through the
    setattr loop and blow up as a 500 at commit (IntegrityError) instead of a
    422. Checks trip/item/program, then proves nothing lingered in the
    session by making a valid patch on the same trip right after."""
    c = _client(db_session, _user(db_session))
    wallet = c.get("/adventures/wallet").json()
    t = _new_trip(c)

    r = c.patch(f"/adventures/trips/{t['id']}", json={"start_date": None})
    assert r.status_code == 422, r.text

    item = t["items"][0]
    r = c.patch(f"/adventures/trips/{t['id']}/items/{item['id']}", json={"name": None})
    assert r.status_code == 422, r.text

    pid = wallet[0]["id"]
    r = c.patch(f"/adventures/programs/{pid}", json={"balance": None})
    assert r.status_code == 422, r.text

    r = c.patch(f"/adventures/trips/{t['id']}", json={"name": "Lake House"})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Lake House"
