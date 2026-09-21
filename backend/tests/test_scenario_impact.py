"""Baseline vs scenario, in the figures Dan uses to decide.

Two independent threading paths meet here, and they cover different figures.
`_lookahead_minimum` threads the proposal into `build_forecast`'s day-by-day
walk, so `quarter_min` -- and therefore `safety_margin` -- responds to a
scenario's items. Separately, `_monthly_income`/`_monthly_expenses` thread
the proposal into the flat monthly aggregates that feed `leftover`, and
everything derived from it (`left_to_spend`, `weekly_spendable`,
`reserve_needed`). `safety_margin` does NOT read those flat aggregates --
`budget_snapshot.py` computes it as
`quarter_min - cc_budget_total + charged_so_far`, none of which derives from
`_monthly_income`/`_monthly_expenses` -- so proving `safety_margin` changes
says nothing about that second path. Both paths are threaded; both are
exercised below, separately, so each has its own coverage.

A THIRD input reaches these figures and for a while reached none of them: a
scenario's amount tweaks (`overrides`) on items that already exist. A
tweak-only scenario is a perfectly ordinary shape -- "what if the rent went
up?" proposes nothing at all -- and every figure in the strip read identical
to baseline for it, while the chart directly beside it drew the two lines
apart. Nothing caught it because this file's fixture held only a proposal, so
no test ever put an override through `/impact`. It now holds both, and the
override path has its own tests below.
"""
from datetime import date
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import models
from backend.dependencies import get_db, get_current_user
from backend.routers import recurring as recurring_router
from backend.routers import scenarios as scenarios_router
from backend.services import scenario_service
from backend.services.budget_snapshot import compute_budget_snapshot
from backend.services.forecast_engine import build_quarters

# The tweak the override-only scenario applies, and the item it lands on.
# Large enough that a dropped override cannot hide inside rounding.
OVERRIDE_DELTA = Decimal("500.00")
ONGOING_MONTHLY = Decimal("1000.00")
ENDING_MONTHLY = Decimal("40.00")


@pytest.fixture()
def seeded(db_session):
    user = models.User(username="impact", hashed_password="x", display_name="Impact")
    db_session.add(user)
    db_session.flush()
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("5000.00"),
    )
    db_session.add(account)
    db_session.flush()

    # Two REAL commitments, so the commitments oracle below compares two
    # non-zero aggregations rather than agreeing that zero equals zero, and
    # so an override has an existing item to land on. One never ends and one
    # does, which is the distinction /recurring/breakdown splits on -- this
    # helper deliberately counts both.
    year = date.today().year
    ongoing = models.RecurringItem(
        user_id=user.id, name="Housing", amount=ONGOING_MONTHLY,
        type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=1,
        start_date=date(year, 1, 1), account_id=account.id,
        is_active=True, include_in_forecast=True,
    )
    db_session.add(ongoing)
    db_session.add(models.RecurringItem(
        user_id=user.id, name="Device Plan", amount=ENDING_MONTHLY,
        type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=8,
        start_date=date(year, 1, 8), end_date=date(year + 1, 6, 8),
        account_id=account.id, is_active=True, include_in_forecast=True,
    ))
    db_session.flush()

    scenario = models.ForecastScenario(user_id=user.id, name="iPhone Duo")
    db_session.add(scenario)
    db_session.flush()
    db_session.add(models.ScenarioProposedItem(
        scenario_id=scenario.id, name="iPhone Trade-In", amount=Decimal("57.87"),
        type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=15,
        start_date=date(2026, 1, 15), account_id=account.id,
    ))

    db_session.commit()
    return db_session, user, account, scenario


@pytest.fixture()
def tweak_only(seeded):
    """A scenario that proposes NOTHING and only raises an existing bill.

    This is the shape the impact strip was blind to: with no proposed items
    there is no second threading path to accidentally carry the change, so
    every figure is answered by the override path or by nothing.
    """
    db, user, account, _proposal_scenario = seeded
    item = db.query(models.RecurringItem).filter(
        models.RecurringItem.user_id == user.id,
        models.RecurringItem.name == "Housing",
    ).one()
    scenario = models.ForecastScenario(user_id=user.id, name="Rent Goes Up")
    db.add(scenario)
    db.flush()
    db.add(models.ScenarioOverride(
        scenario_id=scenario.id, recurring_item_id=item.id,
        amount_delta=OVERRIDE_DELTA,
    ))
    db.commit()
    return db, user, account, scenario, item


def test_impact_reports_a_lower_low_and_higher_commitments_for_the_scenario(seeded):
    db, user, account, scenario = seeded
    result = scenario_service.scenario_impact(db, user, account.id, scenario.id)

    assert result["scenario"]["low"] < result["baseline"]["low"]
    assert result["scenario"]["total_monthly_commitments"] \
        - result["baseline"]["total_monthly_commitments"] == Decimal("57.87")


def test_the_baseline_half_matches_compute_budget_snapshot_exactly(seeded):
    """No second derivation of any of these four figures: the baseline column
    reads the same snapshot fields the Dashboard shows for three of them, and
    for the fourth it has to land on the same money /recurring/breakdown
    reports -- or the screens silently disagree.

    The commitments assertion deliberately does NOT call
    `_total_monthly_commitments` again. It used to, which made it a tautology:
    the helper compared against itself with the same arguments and could not
    fail no matter what the helper did. `/recurring/breakdown` is a materially
    different aggregation -- it walks the items itself, splits them on whether
    they ever end, and reports two subtotals -- so the two only agree if both
    are right. They are expected to agree exactly, not approximately: the
    strip's total is that endpoint's ongoing plus ending, because both halves
    are money going out every month right now.
    """
    db, user, account, scenario = seeded
    result = scenario_service.scenario_impact(db, user, account.id, scenario.id)
    snapshot = compute_budget_snapshot(db, user, account.id)

    assert result["baseline"]["low"] == snapshot.lookahead_minimum
    assert result["baseline"]["low_date"] == snapshot.lookahead_minimum_date
    assert result["baseline"]["safety_margin_weekly"] == snapshot.safety_margin_weekly

    app = FastAPI()
    app.include_router(recurring_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    breakdown = TestClient(app).get("/recurring/breakdown").json()
    from_the_recurring_page = (
        Decimal(str(breakdown["ongoing_monthly"]))
        + Decimal(str(breakdown["ending_monthly"]))
    )

    # Guard the oracle itself: if the fixture ever stopped carrying real
    # commitments this would quietly become 0 == 0 again.
    assert from_the_recurring_page == ONGOING_MONTHLY + ENDING_MONTHLY
    assert result["baseline"]["total_monthly_commitments"] == from_the_recurring_page


def test_a_proposal_changes_the_snapshots_safety_margin(seeded):
    """Exercises the quarter_min path only: `_lookahead_minimum`'s proposal
    kwarg into `build_forecast`. `safety_margin` never reads
    `_monthly_income`/`_monthly_expenses`, so this test says nothing about
    that separate flat-aggregate path -- see
    test_a_proposal_changes_the_snapshots_leftover below for that one."""
    db, user, account, scenario = seeded
    _overrides, proposal = scenario_service.resolve_scenario(db, user.id, scenario.id)

    baseline = compute_budget_snapshot(db, user, account.id)
    with_proposal = compute_budget_snapshot(db, user, account.id, proposal=proposal)

    assert with_proposal.safety_margin < baseline.safety_margin


def test_a_proposal_changes_the_snapshots_leftover(seeded):
    """Exercises the flat-aggregate path: `_monthly_expenses`'s proposal
    kwarg. `left_to_spend` derives from `leftover`, which derives from
    `_monthly_income`/`_monthly_expenses` -- the path `safety_margin` does
    not touch (see the test above). The scenario adds a $57.87/mo expense
    with no card attached, so nothing else in the formula moves and
    left_to_spend should drop by exactly that amount."""
    db, user, account, scenario = seeded
    _overrides, proposal = scenario_service.resolve_scenario(db, user.id, scenario.id)

    baseline = compute_budget_snapshot(db, user, account.id)
    with_proposal = compute_budget_snapshot(db, user, account.id, proposal=proposal)

    assert baseline.left_to_spend - with_proposal.left_to_spend == Decimal("57.87")


def test_impact_moves_all_three_figures_for_a_tweak_only_scenario(tweak_only):
    """The regression this file exists to prevent, at the route.

    A scenario holding one amount tweak and nothing else used to come back
    with `low`, `safety_margin_weekly` and `total_monthly_commitments` all
    byte-identical between the two columns: the resolver returned the tweaks
    and `scenario_impact` dropped them on the floor. Every figure is asserted,
    not just one, because they arrive by two different routes -- the first two
    through the day-by-day forecast walk, the third through the flat
    monthly-equivalent sum -- and threading only one of them would leave the
    strip half wrong in a way a single assertion would call fixed.
    """
    db, user, account, scenario, _item = tweak_only
    app = FastAPI()
    app.include_router(scenarios_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user

    r = TestClient(app).get(
        f"/scenarios/{scenario.id}/impact", params={"account_id": account.id},
    )
    assert r.status_code == 200, r.text
    base, scen = r.json()["baseline"], r.json()["scenario"]

    assert Decimal(str(scen["low"])) < Decimal(str(base["low"]))
    assert Decimal(str(scen["safety_margin_weekly"])) \
        < Decimal(str(base["safety_margin_weekly"]))
    assert Decimal(str(scen["total_monthly_commitments"])) \
        - Decimal(str(base["total_monthly_commitments"])) == OVERRIDE_DELTA


def test_the_strip_and_the_comparison_chart_agree_about_a_tweak(tweak_only):
    """The strip and the chart sit on the same page and must tell the same
    story about the same scenario.

    They cannot be compared day for day -- the strip's floor comes from a
    rolling three-month window opened 45 days back, the chart from a calendar
    year opened on January 1, so the two walks reconstruct different opening
    balances and their raw balances are not the same numbers. What IS
    comparable is the SIZE of the change each attributes to the scenario: a
    monthly bill raised by D costs D more every month, so a year's chart must
    end twelve times D lower while the strip's monthly commitments rise by
    exactly D. That is the arithmetic that was silently violated -- the chart
    moved by a year's worth and the strip did not move at all.
    """
    db, user, account, scenario, _item = tweak_only
    year = date.today().year
    overrides, proposal = scenario_service.resolve_scenario(db, user.id, scenario.id)
    assert overrides, "fixture must actually carry a tweak for this to mean anything"

    baseline_chart = build_quarters(db, user.id, account.id, year)
    scenario_chart = build_quarters(
        db, user.id, account.id, year, overrides=overrides, proposal=proposal,
    )
    chart_year_end_delta = (
        Decimal(str(baseline_chart[-1].close_balance))
        - Decimal(str(scenario_chart[-1].close_balance))
    )

    impact = scenario_service.scenario_impact(db, user, account.id, scenario.id)
    strip_monthly_delta = (
        impact["scenario"]["total_monthly_commitments"]
        - impact["baseline"]["total_monthly_commitments"]
    )

    assert strip_monthly_delta == OVERRIDE_DELTA
    # Twelve occurrences in the year: the tweaked bill falls on the 1st and
    # starts on January 1, so it fires in every month of the walk.
    assert chart_year_end_delta == strip_monthly_delta * 12


def test_a_tweak_changes_the_snapshots_lookahead_floor(tweak_only):
    """`compute_budget_snapshot`'s new `overrides` kwarg, directly -- the one
    the impact column now depends on. Asserted on the floor rather than on
    the weekly figure so a change in the proration math cannot mask it."""
    db, user, account, scenario, _item = tweak_only
    overrides, proposal = scenario_service.resolve_scenario(db, user.id, scenario.id)

    baseline = compute_budget_snapshot(db, user, account.id)
    tweaked = compute_budget_snapshot(
        db, user, account.id, proposal=proposal, overrides=overrides,
    )

    assert tweaked.lookahead_minimum < baseline.lookahead_minimum
    assert tweaked.safety_margin < baseline.safety_margin


def test_the_commitments_helper_never_writes_the_tweak_onto_the_real_item(tweak_only):
    """The tweaked amount is a preview. Costing the item at amount + delta by
    assigning to the ORM row would be flushed by the very next query in the
    session, turning reading the strip into editing a real bill."""
    db, user, account, scenario, item = tweak_only
    before = item.amount
    scenario_service.scenario_impact(db, user, account.id, scenario.id)
    db.expire_all()
    assert db.query(models.RecurringItem).filter(
        models.RecurringItem.id == item.id,
    ).one().amount == before


def test_a_committed_tweak_is_not_counted_a_second_time(tweak_only):
    """Once committed, the tweak lives in the real item's amount. The resolver
    answers with nothing for a committed scenario, so both columns of the
    strip must read the same -- the post-commit reality, counted once."""
    db, user, account, scenario, item = tweak_only
    scenario_service.commit_scenario(db, user.id, scenario.id)

    impact = scenario_service.scenario_impact(db, user, account.id, scenario.id)
    assert impact["scenario"] == impact["baseline"]
    assert impact["baseline"]["total_monthly_commitments"] == \
        ONGOING_MONTHLY + OVERRIDE_DELTA + ENDING_MONTHLY


def test_impact_does_not_persist_the_proposal(seeded):
    db, user, account, scenario = seeded
    before = db.query(models.RecurringItem).count()
    scenario_service.scenario_impact(db, user, account.id, scenario.id)
    assert db.query(models.RecurringItem).count() == before


def test_impact_route_returns_both_columns(seeded):
    db, user, account, scenario = seeded
    app = FastAPI()
    app.include_router(scenarios_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    c = TestClient(app)

    r = c.get(f"/scenarios/{scenario.id}/impact", params={"account_id": account.id})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"baseline", "scenario"}
    assert set(body["baseline"]) == {
        "low", "low_date", "safety_margin_weekly", "total_monthly_commitments",
    }


def test_impact_on_an_unknown_scenario_is_404(seeded):
    db, user, account, _scenario = seeded
    app = FastAPI()
    app.include_router(scenarios_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    c = TestClient(app)

    r = c.get("/scenarios/9999/impact", params={"account_id": account.id})
    assert r.status_code == 404


def test_impact_with_an_unknown_account_is_404(seeded):
    db, user, account, scenario = seeded
    app = FastAPI()
    app.include_router(scenarios_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    c = TestClient(app)

    r = c.get(f"/scenarios/{scenario.id}/impact", params={"account_id": 999999})
    assert r.status_code == 404


def test_impact_with_a_foreign_account_is_404(seeded):
    """A real account that belongs to a different user must 404, not
    silently return a plausible-looking zeroed-out column."""
    db, user, account, scenario = seeded
    other = models.User(username="impact-other", hashed_password="x", display_name="Other")
    db.add(other)
    db.flush()
    other_account = models.Account(
        user_id=other.id, name="Other Checking", type=models.AccountType.checking,
        current_balance=Decimal("100.00"),
    )
    db.add(other_account)
    db.commit()

    app = FastAPI()
    app.include_router(scenarios_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    c = TestClient(app)

    r = c.get(f"/scenarios/{scenario.id}/impact", params={"account_id": other_account.id})
    assert r.status_code == 404
