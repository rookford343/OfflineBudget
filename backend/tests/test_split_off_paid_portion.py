"""Task 1 (Split Off Paid Portion): splitting an existing, ordinary
(ungrouped) one-off into a settled already-paid leg and a shrunk
remaining-balance leg -- see
.superpowers/sdd/2026-11-25-split-off-paid-portion-plan/task-1-brief.md.

Distinct from the bulk 2-6-leg split-creation flow in test_installment_plan.py:
this starts from a single already-existing `PlannedExpense` row and records
that *part* of it has already happened in real life, rather than creating a
whole new group from scratch. The two legs this produces share the same
self-referencing `installment_group_id` FK as a bulk-created group, so the
already-shipped cancellation cascade (`cancel_installment_group`) composes
with this for free -- test_deleting_the_paid_leg_afterward_opens_a_refund_watch
below proves that composition, not new logic of this task's own.

All figures are invented; the repo is public."""
from datetime import date, timedelta
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import models, schemas
from backend.dependencies import get_current_user, get_db
from backend.routers import planned_expenses as pe_router
from backend.services.installment_plan import (
    cancel_installment_group, create_installment_group, split_off_paid_portion,
)


def _seed(db):
    user = models.User(username="splitpaid", hashed_password="x", display_name="SplitPaid")
    db.add(user)
    db.flush()
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("1000.00"),
    )
    db.add(account)
    db.commit()
    return user, account


def _client(db, user):
    app = FastAPI()
    app.include_router(pe_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _expense(db, user, account, amount="620.00", name="Roof repair", days_out=30, **extra):
    expense = models.PlannedExpense(
        user_id=user.id,
        name=name,
        amount=Decimal(amount),
        expected_date=date.today() + timedelta(days=days_out),
        direction=models.PlannedDirection.outflow,
        account_id=account.id,
        **extra,
    )
    db.add(expense)
    db.commit()
    return expense


def test_splits_a_simple_case_into_a_settled_leg_and_a_remaining_leg(db_session):
    user, account = _seed(db_session)
    expense = _expense(db_session, user, account, amount="620.00", name="Roof repair")
    orig_name = expense.name
    orig_expected_date = expense.expected_date

    legs = split_off_paid_portion(
        db_session, user, expense, Decimal("292.00"), date(2026, 11, 22),
    )
    db_session.commit()

    assert len(legs) == 2
    paid_leg, remaining_leg = legs

    assert paid_leg.settled_on == date(2026, 11, 22)
    assert paid_leg.actual_amount == Decimal("292.00")
    assert paid_leg.amount == Decimal("292.00")
    assert paid_leg.expected_date == date(2026, 11, 22)
    assert paid_leg.name == f"{orig_name} (1 of 2)"

    # The remaining leg is the same row as the original expense.
    assert remaining_leg.id == expense.id
    assert remaining_leg.amount == Decimal("328.00")
    assert remaining_leg.expected_date == orig_expected_date
    assert remaining_leg.name == f"{orig_name} (2 of 2)"
    assert remaining_leg.settled_on is None

    assert paid_leg.installment_group_id == expense.id
    assert remaining_leg.installment_group_id == expense.id

    # Decimal equality, not float -- $292.00 + $328.00 must equal the
    # original $620.00 exactly, with no rounding drift.
    assert paid_leg.amount + remaining_leg.amount == Decimal("620.00")


def test_remaining_leg_clears_pre_existing_funding_fields(db_session):
    user, account = _seed(db_session)
    funding_account = models.Account(
        user_id=user.id, name="Savings", type=models.AccountType.savings,
        current_balance=Decimal("5000.00"),
    )
    db_session.add(funding_account)
    db_session.commit()

    expense = _expense(
        db_session, user, account, amount="620.00",
        funding_account_id=funding_account.id,
        funding_amount=Decimal("620.00"),
        funding_lead_days=5,
    )

    legs = split_off_paid_portion(
        db_session, user, expense, Decimal("292.00"), date(2026, 11, 22),
    )
    db_session.commit()
    paid_leg, remaining_leg = legs

    assert remaining_leg.funding_account_id is None
    assert remaining_leg.funding_amount is None
    assert remaining_leg.funding_lead_days == 0

    # The paid leg never had funding fields set in the first place --
    # split_off_paid_portion doesn't copy them onto the new row at all.
    assert paid_leg.funding_account_id is None
    assert paid_leg.funding_amount is None
    assert paid_leg.funding_lead_days == 0


def test_deleting_the_paid_leg_afterward_opens_a_refund_watch(db_session):
    """Proves composition with the already-shipped cascade, not new logic of
    this task's own. `remaining_leg` (the shrunk, still-forecasted balance)
    is always the anchor -- its id predates `paid_leg`'s, per
    split_off_paid_portion's docstring -- and it's always uncleared, so by
    cancel_installment_group's existing, unmodified rules for a
    mixed-cleared group (see test_installment_cancellation.py's
    "sweeps the unpaid sibling" case) deleting either leg of this pair
    sweeps the uncleared anchor and keeps the cleared leg as history with a
    refund-watch opened against it -- exactly what you'd want: cancelling
    the plan after $292.00 of it already happened in real life should both
    drop the still-forecasted $328.00 and flag the $292.00 for a refund."""
    user, account = _seed(db_session)
    expense = _expense(db_session, user, account, amount="620.00")

    legs = split_off_paid_portion(
        db_session, user, expense, Decimal("292.00"), date(2026, 11, 22),
    )
    db_session.commit()
    paid_leg, remaining_leg = legs
    paid_leg_id = paid_leg.id
    remaining_id = remaining_leg.id

    # Same call the delete endpoint makes against a grouped leg.
    cancel_installment_group(db_session, user, paid_leg)
    db_session.commit()

    # The uncleared anchor (the remaining balance) is swept by the cascade.
    assert db_session.query(models.PlannedExpense).filter(
        models.PlannedExpense.id == remaining_id,
    ).first() is None

    # The cleared leg survives as history, untouched, and becomes the new
    # anchor for whatever still points at the group (here, just the new
    # refund-watch row created below it).
    survivor = db_session.query(models.PlannedExpense).filter(
        models.PlannedExpense.id == paid_leg_id,
    ).first()
    assert survivor is not None
    assert survivor.settled_on == date(2026, 11, 22)
    assert survivor.actual_amount == Decimal("292.00")

    group_rows = db_session.query(models.PlannedExpense).filter(
        models.PlannedExpense.installment_group_id == survivor.installment_group_id,
    ).all()
    refund = next((pe for pe in group_rows if pe.is_refund_watch), None)
    assert refund is not None
    assert refund.direction == models.PlannedDirection.inflow
    assert refund.amount == Decimal("292.00")


def test_rejects_amount_paid_greater_than_or_equal_to_total(db_session):
    user, account = _seed(db_session)
    expense = _expense(db_session, user, account, amount="620.00")
    client = _client(db_session, user)
    r = client.post(
        f"/planned-expenses/{expense.id}/already-paid",
        json={"amount_paid": "620.00", "date_paid": date.today().isoformat()},
    )
    assert r.status_code == 422
    assert "settle" in r.json()["detail"].lower()


def test_rejects_an_expense_already_in_a_group(db_session):
    user, account = _seed(db_session)
    legs = create_installment_group(db_session, user, schemas.PlannedExpenseInstallmentsCreate(
        name="Dental", account_id=account.id, legs=[
            {"amount": "50.00", "expected_date": date.today().isoformat()},
            {"amount": "75.00", "expected_date": (date.today() + timedelta(days=30)).isoformat()},
        ],
    ))
    db_session.commit()
    client = _client(db_session, user)
    r = client.post(
        f"/planned-expenses/{legs[0].id}/already-paid",
        json={"amount_paid": "10.00", "date_paid": date.today().isoformat()},
    )
    assert r.status_code == 422


def test_rejects_an_already_settled_expense(db_session):
    """Guards Review Focus #2: a settled original has no "unpaid remainder"
    to split off -- amount_paid would stack on top of the existing
    actual_amount with nothing cancelling it out."""
    user, account = _seed(db_session)
    expense = _expense(db_session, user, account, amount="620.00")
    expense.settled_on = date.today()
    expense.actual_amount = Decimal("620.00")
    db_session.commit()
    before = db_session.query(models.PlannedExpense).count()
    client = _client(db_session, user)
    r = client.post(
        f"/planned-expenses/{expense.id}/already-paid",
        json={"amount_paid": "292.00", "date_paid": date.today().isoformat()},
    )
    assert r.status_code == 422
    assert db_session.query(models.PlannedExpense).count() == before
    db_session.refresh(expense)
    assert expense.amount == Decimal("620.00")


def test_rejects_an_expense_linked_to_a_trip_item(db_session):
    """Guards the Critical bug: a trip-linked one-off can't be split off,
    because any later trip edit re-runs sync_trip_planned_expenses
    (adventures_lifecycle.py), which resets the remaining leg back to the
    trip item's full original amount -- double-counting against the
    now-separate settled leg."""
    user, account = _seed(db_session)
    expense = _expense(db_session, user, account, amount="620.00")
    trip = models.Trip(
        user_id=user.id, name="Trip", start_date=date.today(),
        end_date=date.today() + timedelta(days=5), travelers=1,
    )
    db_session.add(trip)
    db_session.flush()
    db_session.add(models.TripItem(
        trip_id=trip.id, user_id=user.id, category=models.TripCategory.getting_there,
        name="Flight", planned_expense_id=expense.id,
    ))
    db_session.commit()
    before = db_session.query(models.PlannedExpense).count()
    client = _client(db_session, user)
    r = client.post(
        f"/planned-expenses/{expense.id}/already-paid",
        json={"amount_paid": "292.00", "date_paid": date.today().isoformat()},
    )
    assert r.status_code == 422
    assert "trip" in r.json()["detail"].lower()
    assert db_session.query(models.PlannedExpense).count() == before
    db_session.refresh(expense)
    assert expense.amount == Decimal("620.00")


def test_rejects_an_expense_linked_to_a_committed_scenario_expense(db_session):
    """Guards the Critical bug: uncommit_scenario (scenario_service.py)
    tries to delete the anchor row while the paid leg still FK-references
    it, raising an IntegrityError -> 500 if this were allowed through."""
    user, account = _seed(db_session)
    expense = _expense(db_session, user, account, amount="620.00")
    scenario = models.ForecastScenario(user_id=user.id, name="One-offs")
    db_session.add(scenario)
    db_session.flush()
    db_session.add(models.ScenarioProposedExpense(
        scenario_id=scenario.id, name="Roof repair", amount=Decimal("620.00"),
        expected_date=expense.expected_date, account_id=account.id,
        committed_planned_expense_id=expense.id,
    ))
    db_session.commit()
    before = db_session.query(models.PlannedExpense).count()
    client = _client(db_session, user)
    r = client.post(
        f"/planned-expenses/{expense.id}/already-paid",
        json={"amount_paid": "292.00", "date_paid": date.today().isoformat()},
    )
    assert r.status_code == 422
    assert "scenario" in r.json()["detail"].lower()
    assert db_session.query(models.PlannedExpense).count() == before
    db_session.refresh(expense)
    assert expense.amount == Decimal("620.00")


def test_happy_path_through_the_http_endpoint(db_session):
    user, account = _seed(db_session)
    client = _client(db_session, user)
    create_body = {
        "name": "Roof repair", "account_id": account.id, "amount": "620.00",
        "expected_date": (date.today() + timedelta(days=30)).isoformat(),
    }
    created = client.post("/planned-expenses", json=create_body)
    assert created.status_code == 201, created.text
    expense_id = created.json()["id"]

    r = client.post(
        f"/planned-expenses/{expense_id}/already-paid",
        json={"amount_paid": "292.00", "date_paid": "2026-11-22"},
    )
    assert r.status_code == 200, r.text
    out = r.json()
    legs = out["legs"]
    assert len(legs) == 2
    paid_leg, remaining_leg = legs

    assert paid_leg["settled_on"] == "2026-11-22"
    assert Decimal(paid_leg["actual_amount"]) == Decimal("292.00")
    assert Decimal(paid_leg["amount"]) == Decimal("292.00")
    assert paid_leg["expected_date"] == "2026-11-22"
    assert paid_leg["name"] == "Roof repair (1 of 2)"

    assert remaining_leg["id"] == expense_id
    assert Decimal(remaining_leg["amount"]) == Decimal("328.00")
    assert remaining_leg["expected_date"] == create_body["expected_date"]
    assert remaining_leg["name"] == "Roof repair (2 of 2)"
    assert remaining_leg["settled_on"] is None
