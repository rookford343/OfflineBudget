"""API tests for /wish-list. Spec: docs/superpowers/specs/2026-10-07-wish-list-design.md
Mirrors the TestClient + dependency_overrides pattern from test_adventures_api.py.
"""
from datetime import date
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import models
from backend.dependencies import get_db, get_current_user
from backend.routers import wish_list as wish_list_router
from backend.services import scenario_service


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


# ── Fix round 1 ──────────────────────────────────────────────────────────────

def test_commit_route_returns_409_not_500_on_scenario_commit_conflict(db_session):
    """Bug: commit_wish calls scenario_service.commit_scenario, which can raise
    ScenarioCommitConflict/ScenarioDuplicateOverride/ScenarioAlreadyCommitted --
    none of which are WishError, so they fell through the route's only except
    clause and 500'd. Built here via ScenarioCommitConflict: another,
    already-committed scenario has already tweaked the same recurring item
    this wish's own scenario also tweaks."""
    db = db_session
    user = _user(db, "conflicted")
    account = _account(db, user, "10000.00")
    dining = models.RecurringItem(
        user_id=user.id, account_id=account.id, name="Dining", amount=Decimal("400.00"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=1, start_date=date(2026, 1, 1),
    )
    db.add(dining)
    db.flush()

    first = models.ForecastScenario(user_id=user.id, name="First cut")
    db.add(first)
    db.flush()
    db.add(models.ScenarioOverride(
        scenario_id=first.id, recurring_item_id=dining.id, amount_delta=Decimal("-100.00"),
    ))
    db.commit()
    scenario_service.commit_scenario(db, user.id, first.id)

    c = _client(db, user)
    item = c.post("/wish-list/items", json={"name": "Grill", "price": "200.00"}).json()
    c.post(f"/wish-list/items/{item['id']}/options", json={"label": "Full", "method": "full_checking"})
    wish_scenario_id = db.query(models.WishItem).filter_by(id=item["id"]).one().scenario_id
    db.add(models.ScenarioOverride(
        scenario_id=wish_scenario_id, recurring_item_id=dining.id, amount_delta=Decimal("-20.00"),
    ))
    db.commit()

    response = c.post(f"/wish-list/items/{item['id']}/commit")

    assert response.status_code == 409
    assert "First cut" in response.json()["detail"]
    db.refresh(dining)
    assert dining.amount == Decimal("300.00")  # untouched by the refused commit
    item_row = db.query(models.WishItem).filter_by(id=item["id"]).one()
    assert item_row.scenario.status == "draft"


def test_uncommit_route_returns_409_not_500_when_scenario_proposed_item_has_posted_payments(db_session):
    """Bug: uncommit_wish calls scenario_service.uncommit_scenario, which can
    raise ScenarioPaymentsPosted/ScenarioUncommitBlocked for a committed
    PROPOSED item on the scenario (independent of the wish's own commit
    rows) -- neither is a WishError, so this 500'd too."""
    db = db_session
    user = _user(db, "poster")
    account = _account(db, user, "10000.00")
    c = _client(db, user)

    item = c.post("/wish-list/items", json={"name": "Grill", "price": "300.00"}).json()
    c.post(f"/wish-list/items/{item['id']}/options", json={"label": "Full", "method": "full_checking"})
    wish_scenario_id = db.query(models.WishItem).filter_by(id=item["id"]).one().scenario_id
    proposed = models.ScenarioProposedItem(
        scenario_id=wish_scenario_id, name="Side burner", amount=Decimal("25.00"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=5, start_date=date(2026, 11, 5), account_id=account.id,
    )
    db.add(proposed)
    db.commit()

    r = c.post(f"/wish-list/items/{item['id']}/commit")
    assert r.status_code == 200

    side_burner = db.query(models.RecurringItem).filter_by(name="Side burner").one()
    planned_expense_count_before = db.query(models.PlannedExpense).filter_by(user_id=user.id).count()
    commit_row_count_before = db.query(models.WishCommitRow).filter_by(wish_item_id=item["id"]).count()
    db.add(models.Transaction(
        user_id=user.id, account_id=account.id, recurring_item_id=side_burner.id,
        date=date.today(), amount=Decimal("-25.00"), description="side burner payment",
    ))
    db.commit()

    response = c.post(f"/wish-list/items/{item['id']}/uncommit")

    assert response.status_code == 409
    # Nothing the wish itself created was removed either -- uncommit_wish must
    # not leave its own deletes applied once the scenario-level uncommit
    # refuses.
    assert db.query(models.RecurringItem).filter_by(name="Side burner").count() == 1
    assert db.query(models.PlannedExpense).filter_by(user_id=user.id).count() == planned_expense_count_before
    assert db.query(models.WishCommitRow).filter_by(wish_item_id=item["id"]).count() == commit_row_count_before
    item_row = db.query(models.WishItem).filter_by(id=item["id"]).one()
    assert item_row.scenario.status == "committed"


# ── Fix round 1: cross-user test gaps ────────────────────────────────────────

def test_uncommit_on_another_users_item_is_404(db_session):
    db = db_session
    owner = _user(db, "owner2")
    _account(db, owner)
    other = _user(db, "other2")
    _account(db, other)
    c_owner = _client(db, owner)
    item = c_owner.post("/wish-list/items", json={"name": "Grill", "price": "500.00"}).json()

    c_other = _client(db, other)
    assert c_other.post(f"/wish-list/items/{item['id']}/uncommit").status_code == 404


def test_reorder_with_another_users_ids_is_422(db_session):
    db = db_session
    owner = _user(db, "owner3")
    _account(db, owner)
    other = _user(db, "other3")
    _account(db, other)
    c_owner = _client(db, owner)
    owner_item = c_owner.post("/wish-list/items", json={"name": "Grill"}).json()

    c_other = _client(db, other)
    other_item = c_other.post("/wish-list/items", json={"name": "Drone"}).json()

    r = c_other.post("/wish-list/items/reorder", json={"ids": [owner_item["id"]]})
    assert r.status_code == 422
    r2 = c_other.post("/wish-list/items/reorder", json={"ids": [owner_item["id"], other_item["id"]]})
    assert r2.status_code == 422
    row = db.query(models.WishItem).filter_by(id=other_item["id"]).one()
    assert row.rank == 0  # untouched by the refused reorder


def test_create_option_with_another_users_card_is_422(db_session):
    db = db_session
    owner = _user(db, "owner4")
    _account(db, owner)
    other = _user(db, "other4")
    _account(db, other)
    other_card = models.CreditCard(
        user_id=other.id, name="Other's card", credit_limit=Decimal("5000.00"),
        statement_day=1, due_day=20,
    )
    db.add(other_card)
    db.commit()

    c_owner = _client(db, owner)
    item = c_owner.post("/wish-list/items", json={"name": "Grill", "price": "200.00"}).json()

    r = c_owner.post(f"/wish-list/items/{item['id']}/options",
                     json={"label": "Card", "method": "full_card", "card_id": other_card.id})
    assert r.status_code == 422
    assert db.query(models.WishOption).filter_by(wish_item_id=item["id"]).count() == 0


def test_patch_plan_option_id_to_another_items_option_is_422(db_session):
    db = db_session
    owner = _user(db, "owner5")
    _account(db, owner)
    other = _user(db, "other5")
    _account(db, other)

    c_owner = _client(db, owner)
    owner_item = c_owner.post("/wish-list/items", json={"name": "Grill", "price": "200.00"}).json()
    owner_opt = c_owner.post(f"/wish-list/items/{owner_item['id']}/options",
                             json={"label": "Full", "method": "full_checking"}).json()

    c_other = _client(db, other)
    other_item = c_other.post("/wish-list/items", json={"name": "Drone", "price": "100.00"}).json()

    r = c_other.patch(f"/wish-list/items/{other_item['id']}", json={"plan_option_id": owner_opt["id"]})
    assert r.status_code == 422
    row = db.query(models.WishItem).filter_by(id=other_item["id"]).one()
    assert row.plan_option_id is None


# ── I1: inactive cards must not be usable by a wish option ──────────────────

def test_create_option_on_an_inactive_card_is_422(db_session):
    user = _user(db_session)
    _account(db_session, user)
    card = models.CreditCard(
        user_id=user.id, name="Closed card", credit_limit=Decimal("1000.00"),
        statement_day=1, due_day=20, is_active=False,
    )
    db_session.add(card)
    db_session.commit()
    c = _client(db_session, user)
    item = c.post("/wish-list/items", json={"name": "Grill", "price": "200.00"}).json()

    r = c.post(f"/wish-list/items/{item['id']}/options",
               json={"label": "Card", "method": "full_card", "card_id": card.id})

    assert r.status_code == 422
    assert "closed" in r.json()["detail"].lower()
    assert db_session.query(models.WishOption).filter_by(wish_item_id=item["id"]).count() == 0


def test_update_option_to_an_inactive_card_is_422(db_session):
    user = _user(db_session)
    _account(db_session, user)
    active_card = models.CreditCard(
        user_id=user.id, name="Open card", credit_limit=Decimal("1000.00"), statement_day=1, due_day=20,
    )
    closed_card = models.CreditCard(
        user_id=user.id, name="Closed card", credit_limit=Decimal("1000.00"),
        statement_day=1, due_day=20, is_active=False,
    )
    db_session.add_all([active_card, closed_card])
    db_session.commit()
    c = _client(db_session, user)
    item = c.post("/wish-list/items", json={"name": "Grill", "price": "200.00"}).json()
    opt = c.post(f"/wish-list/items/{item['id']}/options",
                json={"label": "Card", "method": "full_card", "card_id": active_card.id}).json()

    r = c.patch(f"/wish-list/items/{item['id']}/options/{opt['id']}", json={"card_id": closed_card.id})

    assert r.status_code == 422
    assert "closed" in r.json()["detail"].lower()
    db_session.refresh(db_session.get(models.WishOption, opt["id"]))
    assert db_session.get(models.WishOption, opt["id"]).card_id == active_card.id


def test_cushion_is_isolated_per_user(db_session):
    db = db_session
    a = _user(db, "cushion_a")
    _account(db, a)
    b = _user(db, "cushion_b")
    _account(db, b)

    c_a = _client(db, a)
    c_b = _client(db, b)

    r = c_a.put("/wish-list/cushion", json={"cushion": "500.00"})
    assert Decimal(r.json()["cushion"]) == Decimal("500.00")

    r_b = c_b.get("/wish-list/cushion")
    assert Decimal(r_b.json()["cushion"]) == Decimal("1000")  # unaffected by A's setting
    assert db.query(models.WishSettings).filter_by(user_id=b.id).count() == 0
