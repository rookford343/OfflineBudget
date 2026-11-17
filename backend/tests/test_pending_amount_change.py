"""pending_amount / pending_amount_effective_date on RecurringItem -- lets the
user schedule a recurring item's future amount change today (e.g. a mortgage
payment dropping after an escrow re-analysis) without it retroactively
applying to months before the change takes effect. This task adds just the
two fields plus both-or-neither validation; Task 2/3 make the forecast engine
and a scheduler sweep read them, Task 4 adds the frontend UI.

This repo wires auth via a get_current_user dependency override rather than a
bearer-token scheme (see test_recurring_breakdown_account.py) -- auth_headers
below is an empty placeholder kept only so the call shape matches other
router test files; no real header is required.
"""
from datetime import date
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import models
from backend.dependencies import get_db, get_current_user
from backend.routers import recurring as recurring_router_module
from backend.services.forecast_engine import build_forecast
from backend.services.pending_amount import promote_due_pending_amounts

D = Decimal


@pytest.fixture()
def client(db_session, test_user):
    app = FastAPI()
    app.include_router(recurring_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: test_user
    return TestClient(app)


@pytest.fixture()
def auth_headers():
    return {}


def _world(db):
    user = models.User(username="pendingamt", hashed_password="x", display_name="PendingAmt")
    db.add(user)
    db.flush()
    checking = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=D("1000.00"),
    )
    db.add(checking)
    db.flush()
    item = models.RecurringItem(
        user_id=user.id, account_id=checking.id, name="Test Mortgage", amount=D("2200.00"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=1, start_date=date(2026, 1, 1),
    )
    db.add(item)
    db.commit()
    return user, checking, item


def test_pending_fields_default_to_none(db_session):
    _, _, item = _world(db_session)
    assert item.pending_amount is None and item.pending_amount_effective_date is None


def test_create_rejects_a_half_entered_pair(client, auth_headers, test_account):
    body = {
        "name": "Half Entered", "amount": "100.00", "type": "expense", "frequency": "monthly",
        "account_id": test_account.id, "day_of_month": 1, "start_date": "2026-01-01",
        "pending_amount": "90.00",
    }
    r = client.post("/recurring", json=body, headers=auth_headers)
    assert r.status_code == 422


def test_create_accepts_a_complete_pair(client, auth_headers, test_account):
    body = {
        "name": "Complete Pair", "amount": "2200.00", "type": "expense", "frequency": "monthly",
        "account_id": test_account.id, "day_of_month": 1, "start_date": "2026-01-01",
        "pending_amount": "1950.00", "pending_amount_effective_date": "2027-01-01",
    }
    r = client.post("/recurring", json=body, headers=auth_headers)
    assert r.status_code == 201
    assert r.json()["pending_amount"] == "1950.00"
    assert r.json()["pending_amount_effective_date"] == "2027-01-01"


def test_update_rejects_a_half_entered_pair(client, auth_headers, db_session, test_user, test_account):
    item = models.RecurringItem(
        user_id=test_user.id, account_id=test_account.id, name="Test Item", amount=D("100.00"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=1, start_date=date(2026, 1, 1),
    )
    db_session.add(item)
    db_session.commit()
    r = client.patch(f"/recurring/{item.id}", json={"pending_amount": "90.00"}, headers=auth_headers)
    assert r.status_code == 422


def test_breakdown_is_unaffected_by_a_future_pending_change(client, auth_headers, db_session, test_user, test_account):
    item = models.RecurringItem(
        user_id=test_user.id, account_id=test_account.id, name="Test Mortgage", amount=D("2200.00"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=1, start_date=date(2026, 1, 1),
        pending_amount=D("1950.00"), pending_amount_effective_date=date(2027, 1, 1),
    )
    db_session.add(item)
    db_session.commit()
    r = client.get("/recurring/breakdown", headers=auth_headers)
    row = next(
        i for g in r.json()["by_category"] for i in (g["items"] or [it for c in g["categories"] for it in c["items"]])
        if i["id"] == item.id
    )
    assert row["amount"] == "2200.00"


def test_update_can_clear_a_scheduled_change(client, auth_headers, db_session, test_user, test_account):
    item = models.RecurringItem(
        user_id=test_user.id, account_id=test_account.id, name="Test Item", amount=D("100.00"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=1, start_date=date(2026, 1, 1),
        pending_amount=D("90.00"), pending_amount_effective_date=date(2027, 1, 1),
    )
    db_session.add(item)
    db_session.commit()
    r = client.patch(
        f"/recurring/{item.id}", json={"pending_amount": None, "pending_amount_effective_date": None},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["pending_amount"] is None and r.json()["pending_amount_effective_date"] is None


# Task 2: build_forecast resolves the scheduled amount change by occurrence date.
#
# ForecastTransaction.amount is signed (confirmed against test_checking_level.py's
# sweep/inflow assertions and by running build_forecast directly against this
# fixture before writing these assertions): an expense's occurrence amount comes
# back negative. _amount_on below returns that signed value as-is, so a
# "Test Mortgage" expense of $2,200.00/mo appears as Decimal("-2200.00"), not
# Decimal("2200.00").

def _mortgage_world(db, pending_amount=None, effective_date=None):
    user = models.User(username="forecastpending", hashed_password="x", display_name="ForecastPending")
    db.add(user)
    db.flush()
    checking = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=D("10000.00"),
    )
    db.add(checking)
    db.flush()
    item = models.RecurringItem(
        user_id=user.id, account_id=checking.id, name="Test Mortgage", amount=D("2200.00"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=1, start_date=date(2026, 1, 1),
        pending_amount=pending_amount, pending_amount_effective_date=effective_date,
    )
    db.add(item)
    db.commit()
    return user, checking, item


def _amount_on(entries, name, on_day):
    for e in entries:
        if e.date == on_day:
            for t in e.transactions:
                if t.name == name:
                    return t.amount
    return None


def test_pre_effective_occurrence_keeps_the_old_amount(db_session):
    user, checking, _ = _mortgage_world(
        db_session, pending_amount=D("1950.00"), effective_date=date(2027, 1, 1),
    )
    entries = build_forecast(db_session, user.id, checking.id, date(2026, 12, 1), date(2026, 12, 31))
    assert _amount_on(entries, "Test Mortgage", date(2026, 12, 1)) == D("-2200.00")


def test_on_and_after_effective_occurrence_uses_the_new_amount(db_session):
    user, checking, _ = _mortgage_world(
        db_session, pending_amount=D("1950.00"), effective_date=date(2027, 1, 1),
    )
    entries = build_forecast(db_session, user.id, checking.id, date(2027, 1, 1), date(2027, 1, 31))
    assert _amount_on(entries, "Test Mortgage", date(2027, 1, 1)) == D("-1950.00")


def test_no_pending_amount_is_unaffected(db_session):
    user, checking, _ = _mortgage_world(db_session)
    entries = build_forecast(db_session, user.id, checking.id, date(2027, 1, 1), date(2027, 1, 31))
    assert _amount_on(entries, "Test Mortgage", date(2027, 1, 1)) == D("-2200.00")


def test_a_confirmed_statement_amount_still_beats_a_pending_change(db_session):
    user, checking, item = _mortgage_world(
        db_session, pending_amount=D("1950.00"), effective_date=date(2027, 1, 1),
    )
    db_session.add(models.BillAmountOverride(
        user_id=user.id, recurring_item_id=item.id, due_date=date(2027, 1, 1), actual_amount=D("2015.42"),
    ))
    db_session.commit()
    entries = build_forecast(db_session, user.id, checking.id, date(2027, 1, 1), date(2027, 1, 31))
    assert _amount_on(entries, "Test Mortgage", date(2027, 1, 1)) == D("-2015.42")


# Task 3: once the effective date arrives, promote_due_pending_amounts moves
# pending_amount into amount and clears both pending fields.

def test_promotes_an_item_whose_date_has_arrived(db_session):
    _, _, item = _mortgage_world(db_session, pending_amount=D("1950.00"), effective_date=date(2027, 1, 1))
    ids = promote_due_pending_amounts(db_session, date(2027, 1, 1))
    db_session.refresh(item)
    assert ids == [item.id]
    assert item.amount == D("1950.00")
    assert item.pending_amount is None and item.pending_amount_effective_date is None


def test_leaves_a_not_yet_due_item_alone(db_session):
    _, _, item = _mortgage_world(db_session, pending_amount=D("1950.00"), effective_date=date(2027, 1, 1))
    ids = promote_due_pending_amounts(db_session, date(2026, 12, 31))
    db_session.refresh(item)
    assert ids == []
    assert item.amount == D("2200.00") and item.pending_amount == D("1950.00")


def test_running_it_twice_on_the_same_day_is_a_no_op_the_second_time(db_session):
    _, _, item = _mortgage_world(db_session, pending_amount=D("1950.00"), effective_date=date(2027, 1, 1))
    promote_due_pending_amounts(db_session, date(2027, 1, 1))
    ids = promote_due_pending_amounts(db_session, date(2027, 1, 1))
    assert ids == []


# Finding 1 (final whole-branch review): the amount boundary must compare
# against the NATURAL due date, not the weekend-shifted posting date
# (`current`). May 1, 2027 is a Saturday, so that occurrence posts on the
# preceding Friday, April 30 -- but its natural due date (May 1) is still
# on/after a May 1 effective date, so the new amount must already apply.

def test_weekend_shifted_posting_still_uses_the_new_amount_on_its_natural_date(db_session):
    user, checking, _ = _mortgage_world(
        db_session, pending_amount=D("1950.00"), effective_date=date(2027, 5, 1),
    )
    entries = build_forecast(db_session, user.id, checking.id, date(2027, 4, 1), date(2027, 5, 31))
    # Sanity check: the fix didn't overshoot -- the April occurrence (posts
    # ~April 1, well before the May 1 effective date) still uses the old amount.
    assert _amount_on(entries, "Test Mortgage", date(2027, 4, 1)) == D("-2200.00")
    # The May 1 occurrence posts on Friday April 30 (weekend shift), and
    # must already reflect the new amount since its natural due date (May 1)
    # is on/after the May 1 effective date.
    assert _amount_on(entries, "Test Mortgage", date(2027, 4, 30)) == D("-1950.00")


# Finding 2 (final whole-branch review): promoting a scheduled amount change
# must mark every pre-change payment as already-reconciled
# (drift_dismissed_through), so the "Amounts changed?" drift prompt doesn't
# immediately offer to revert the promotion by comparing the last payment at
# the OLD amount against the item's new amount.

def test_promotion_sets_drift_dismissed_through_to_the_day_before_effective(db_session):
    _, _, item = _mortgage_world(db_session, pending_amount=D("1950.00"), effective_date=date(2027, 1, 1))
    assert item.drift_dismissed_through is None
    promote_due_pending_amounts(db_session, date(2027, 1, 1))
    db_session.refresh(item)
    assert item.drift_dismissed_through == date(2026, 12, 31)


def test_promotion_does_not_pull_back_a_later_drift_dismissed_through(db_session):
    user, checking, item = _mortgage_world(
        db_session, pending_amount=D("1950.00"), effective_date=date(2027, 1, 1),
    )
    item.drift_dismissed_through = date(2027, 1, 15)
    db_session.commit()
    promote_due_pending_amounts(db_session, date(2027, 1, 1))
    db_session.refresh(item)
    assert item.drift_dismissed_through == date(2027, 1, 15)


# Final review finding: build_forecast's own inline old-vs-pending resolution
# duplicated the same date comparison three other forward-looking readers of
# RecurringItem.amount also needed (Dashboard Upcoming Bills, the daily
# email's 7-day section, the Recurring page's future-month summary) -- each
# one read item.amount directly and so kept showing the OLD amount for days/
# weeks before a scheduled change took effect, disagreeing with the Forecast/
# Contingency pages that already resolved it correctly. amount_on() is the
# single shared helper every one of those readers (plus the card-subscription
# -charge walk feeding card_payment_model.py) now goes through, so there is
# exactly one place that does this date comparison, not four.

from backend.services.pending_amount import amount_on


def _plain_item(amount, pending_amount=None, effective_date=None) -> models.RecurringItem:
    """An unpersisted RecurringItem -- amount_on() only reads plain
    attributes, so no db session/commit is needed for these pure-function
    tests of the helper in isolation."""
    return models.RecurringItem(
        name="Plain", amount=amount, type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=1,
        start_date=date(2026, 1, 1),
        pending_amount=pending_amount, pending_amount_effective_date=effective_date,
    )


def test_amount_on_before_effective_date_returns_the_old_amount():
    item = _plain_item(D("2200.00"), D("1950.00"), date(2027, 1, 1))
    assert amount_on(item, date(2026, 12, 31)) == D("2200.00")


def test_amount_on_on_the_effective_date_returns_the_new_amount():
    item = _plain_item(D("2200.00"), D("1950.00"), date(2027, 1, 1))
    assert amount_on(item, date(2027, 1, 1)) == D("1950.00")


def test_amount_on_after_the_effective_date_returns_the_new_amount():
    item = _plain_item(D("2200.00"), D("1950.00"), date(2027, 1, 1))
    assert amount_on(item, date(2027, 6, 15)) == D("1950.00")


def test_amount_on_with_no_pending_amount_returns_the_plain_amount():
    item = _plain_item(D("500.00"))
    assert amount_on(item, date(2026, 1, 1)) == D("500.00")


# Dashboard surface: GET /recurring/upcoming (the Upcoming Bills card) reads
# upcoming_bills() directly.

def test_upcoming_bills_dashboard_card_shows_the_new_amount_once_effective(db_session):
    from backend.services.upcoming_bills import upcoming_bills

    user, checking, item = _mortgage_world(
        db_session, pending_amount=D("1950.00"), effective_date=date(2027, 1, 1),
    )
    bills = upcoming_bills(
        db_session, user.id, date(2026, 12, 20), 30, types=[models.RecurringType.expense],
    )
    bill = next(b for b in bills if b.recurring_item_id == item.id)
    assert bill.due_date == date(2027, 1, 1)
    assert bill.amount == D("1950.00"), "the Dashboard card must show the new amount, not the stale item.amount"
    # estimated_amount is documented to stay the plain planning amount
    # (item.amount itself hasn't been promoted yet) -- unaffected by this fix.
    assert bill.estimated_amount == D("2200.00")


def test_upcoming_bills_dashboard_card_keeps_the_old_amount_before_effective(db_session):
    from backend.services.upcoming_bills import upcoming_bills

    user, checking, item = _mortgage_world(
        db_session, pending_amount=D("1950.00"), effective_date=date(2027, 6, 1),
    )
    bills = upcoming_bills(
        db_session, user.id, date(2026, 12, 20), 30, types=[models.RecurringType.expense],
    )
    bill = next(b for b in bills if b.recurring_item_id == item.id)
    assert bill.due_date == date(2027, 1, 1)
    assert bill.amount == D("2200.00")


# Recurring page's future-month summary: build_month_base is the single
# per-occurrence resolution point read by both the Recurring page strip
# (via build_month_summary) and the Dashboard's Leftover.

def test_month_base_future_month_resolves_the_pending_amount(db_session):
    from backend.services.month_base import build_month_base

    user, checking, item = _mortgage_world(
        db_session, pending_amount=D("1950.00"), effective_date=date(2027, 1, 1),
    )
    base = build_month_base(db_session, user, 2027, 1)
    occurrence = next(o for o in base.monthly_bills if o.recurring_item_id == item.id)
    assert occurrence.amount == D("1950.00")


def test_month_base_a_month_before_effective_keeps_the_old_amount(db_session):
    from backend.services.month_base import build_month_base

    user, checking, item = _mortgage_world(
        db_session, pending_amount=D("1950.00"), effective_date=date(2027, 1, 1),
    )
    base = build_month_base(db_session, user, 2026, 12)
    occurrence = next(o for o in base.monthly_bills if o.recurring_item_id == item.id)
    assert occurrence.amount == D("2200.00")


# Card-subscription-charge walk: feeds the credit-card payoff projections in
# card_payment_model.py (_card_subscription_charges builds the subscription-
# fallback estimate from each card's own recurring items).

def test_card_subscription_charges_uses_the_pending_amount_on_or_after_effective(db_session):
    from backend.services.forecast_engine import _card_subscription_charges

    user, checking, item = _mortgage_world(
        db_session, pending_amount=D("1950.00"), effective_date=date(2027, 1, 1),
    )
    charges = _card_subscription_charges([item], date(2026, 12, 1), date(2027, 1, 31))
    assert charges[date(2026, 12, 1)] == D("2200.00")
    assert charges[date(2027, 1, 1)] == D("1950.00")


# Cross-surface agreement: for the same item and the same future occurrence
# date, upcoming_bills(), build_month_base(), and build_forecast's own walk
# must all resolve to the identical amount -- the thing Dan asked this fix to
# prove ("now agree with the forecast/Contingency figures").

def test_upcoming_bills_month_base_and_forecast_agree_across_the_effective_date(db_session):
    from backend.services.upcoming_bills import upcoming_bills
    from backend.services.month_base import build_month_base

    user, checking, item = _mortgage_world(
        db_session, pending_amount=D("1950.00"), effective_date=date(2027, 1, 1),
    )

    bills = upcoming_bills(
        db_session, user.id, date(2026, 12, 20), 30, types=[models.RecurringType.expense],
    )
    upcoming_amount = next(b for b in bills if b.recurring_item_id == item.id).amount

    base = build_month_base(db_session, user, 2027, 1)
    month_base_amount = next(o for o in base.monthly_bills if o.recurring_item_id == item.id).amount

    entries = build_forecast(db_session, user.id, checking.id, date(2027, 1, 1), date(2027, 1, 31))
    forecast_amount = abs(_amount_on(entries, "Test Mortgage", date(2027, 1, 1)))

    assert upcoming_amount == month_base_amount == forecast_amount == D("1950.00")
