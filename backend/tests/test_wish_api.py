"""API tests for /wish-list. Spec: docs/superpowers/specs/2026-10-07-wish-list-design.md
Mirrors the TestClient + dependency_overrides pattern from test_adventures_api.py.
"""
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import models
from backend.dependencies import get_db, get_current_user
from backend.routers import wish_list as wish_list_router


def _client(db, user):
    app = FastAPI()
    app.include_router(wish_list_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _user(db, name="wisher"):
    u = models.User(username=name, hashed_password="x", display_name=name)
    db.add(u); db.flush()
    return u


def _account(db, user, balance="5000.00"):
    acct = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking,
                          current_balance=Decimal(balance))
    db.add(acct); db.commit(); db.refresh(acct)
    return acct


# (a) GET /plan turns existing scenarios into items.
def test_plan_turns_existing_scenarios_into_items(db_session):
    user = _user(db_session)
    _account(db_session, user)
    sc = models.ForecastScenario(user_id=user.id, name="Drone")
    db_session.add(sc)
    db_session.commit()

    r = _client(db_session, user).get("/wish-list/plan")

    assert r.status_code == 200
    body = r.json()
    assert "cushion" in body
    item = next(i for i in body["items"] if i["name"] == "Drone")
    assert item["scenario_id"] == sc.id
    assert item["status"] == "draft"
    assert db_session.query(models.WishItem).filter_by(scenario_id=sc.id).count() == 1


# (b) Create an item with two options -> plan shows both with total_cost, and
# the financed option also reports monthly_payment.
def test_create_item_with_two_options_shows_total_cost_and_monthly_payment(db_session):
    user = _user(db_session)
    _account(db_session, user)
    c = _client(db_session, user)

    item = c.post("/wish-list/items", json={"name": "Laptop", "price": "1200.00"}).json()
    assert item["name"] == "Laptop"
    assert Decimal(item["price"]) == Decimal("1200.00")

    c.post(f"/wish-list/items/{item['id']}/options",
           json={"label": "Pay in full", "method": "full_checking"})
    c.post(f"/wish-list/items/{item['id']}/options",
           json={"label": "0% for 12mo", "method": "financed", "months": 12, "apr": "0"})

    plan = c.get("/wish-list/plan").json()
    plan_item = next(i for i in plan["items"] if i["id"] == item["id"])
    options_by_label = {o["label"]: o for o in plan_item["options"]}

    assert Decimal(options_by_label["Pay in full"]["total_cost"]) == Decimal("1200.00")
    assert options_by_label["Pay in full"]["monthly_payment"] is None

    assert Decimal(options_by_label["0% for 12mo"]["total_cost"]) == Decimal("1200.00")
    assert Decimal(options_by_label["0% for 12mo"]["monthly_payment"]) == Decimal("100.00")


# (c) Reorder changes rank and the plan order.
def test_reorder_changes_rank_and_plan_order(db_session):
    user = _user(db_session)
    _account(db_session, user)
    c = _client(db_session, user)
    first = c.post("/wish-list/items", json={"name": "A"}).json()
    second = c.post("/wish-list/items", json={"name": "B"}).json()
    assert [first["rank"], second["rank"]] == [0, 1]

    r = c.post("/wish-list/items/reorder", json={"ids": [second["id"], first["id"]]})
    assert r.status_code == 204

    plan = c.get("/wish-list/plan").json()
    ordered_names = [i["name"] for i in plan["items"]]
    assert ordered_names.index("B") < ordered_names.index("A")
    rows = {row.id: row.rank for row in db_session.query(models.WishItem).filter_by(user_id=user.id).all()}
    assert rows[second["id"]] == 0 and rows[first["id"]] == 1


# (d) financed without months -> 422, full_card without card -> 422.
def test_financed_without_months_422_and_full_card_without_card_422(db_session):
    user = _user(db_session)
    _account(db_session, user)
    c = _client(db_session, user)
    item = c.post("/wish-list/items", json={"name": "Grill"}).json()

    r1 = c.post(f"/wish-list/items/{item['id']}/options",
               json={"label": "Financed", "method": "financed"})
    assert r1.status_code == 422

    r2 = c.post(f"/wish-list/items/{item['id']}/options",
               json={"label": "Card", "method": "full_card"})
    assert r2.status_code == 422

    assert db_session.query(models.WishOption).filter_by(wish_item_id=item["id"]).count() == 0


# (e) commit -> 200 and planned expenses exist; uncommit -> removed.
def test_commit_creates_planned_expense_and_uncommit_removes_it(db_session):
    user = _user(db_session)
    _account(db_session, user, "5000.00")
    c = _client(db_session, user)
    item = c.post("/wish-list/items", json={"name": "Grill", "price": "500.00"}).json()
    c.post(f"/wish-list/items/{item['id']}/options", json={"label": "Full", "method": "full_checking"})

    r = c.post(f"/wish-list/items/{item['id']}/commit")
    assert r.status_code == 200
    body = r.json()
    assert body["placement_date"] is not None
    assert db_session.query(models.PlannedExpense).filter_by(user_id=user.id).count() == 1

    r2 = c.post(f"/wish-list/items/{item['id']}/uncommit")
    assert r2.status_code == 200
    assert db_session.query(models.PlannedExpense).filter_by(user_id=user.id).count() == 0


# (f) another user gets 404 on items/options/commit and an empty plan.
def test_other_user_gets_404_on_items_options_commit_and_empty_plan(db_session):
    owner = _user(db_session, "owner")
    _account(db_session, owner)
    other = _user(db_session, "other")
    _account(db_session, other)
    c_owner = _client(db_session, owner)
    item = c_owner.post("/wish-list/items", json={"name": "Grill", "price": "500.00"}).json()
    opt = c_owner.post(f"/wish-list/items/{item['id']}/options",
                       json={"label": "Full", "method": "full_checking"}).json()

    c_other = _client(db_session, other)
    assert c_other.get("/wish-list/plan").json()["items"] == []
    assert c_other.patch(f"/wish-list/items/{item['id']}", json={"name": "x"}).status_code == 404
    assert c_other.delete(f"/wish-list/items/{item['id']}").status_code == 404
    assert c_other.post(f"/wish-list/items/{item['id']}/options",
                        json={"label": "x", "method": "full_checking"}).status_code == 404
    assert c_other.patch(f"/wish-list/items/{item['id']}/options/{opt['id']}",
                         json={"label": "y"}).status_code == 404
    assert c_other.delete(f"/wish-list/items/{item['id']}/options/{opt['id']}").status_code == 404
    assert c_other.post(f"/wish-list/items/{item['id']}/commit").status_code == 404


# (g) PUT cushion 0 -> plan cushion 0, and PUT null -> falls back to 1000 with no threshold.
def test_put_cushion_zero_then_null_falls_back_to_default(db_session):
    user = _user(db_session)
    _account(db_session, user)
    c = _client(db_session, user)

    r = c.put("/wish-list/cushion", json={"cushion": "0"})
    assert r.status_code == 200
    assert Decimal(r.json()["cushion"]) == Decimal("0")
    plan = c.get("/wish-list/plan").json()
    assert Decimal(plan["cushion"]) == Decimal("0")

    r2 = c.put("/wish-list/cushion", json={"cushion": None})
    assert r2.status_code == 200
    assert Decimal(r2.json()["cushion"]) == Decimal("1000")


# Extra requirement: ScenarioPaymentsPosted wired into the scenarios uncommit
# route as a 409. Covered in tests/test_scenario_commit.py
# (test_uncommit_blocked_by_a_posted_transaction).
