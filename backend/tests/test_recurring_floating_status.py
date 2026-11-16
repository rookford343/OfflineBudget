"""GET /recurring/floating-status and its build_floating_status() service --
the per-item, per-month Matched/Pending/Skipped read for floating recurring
items (Task 5 of the floating-recurring-expenses plan).

Checking-item matching uses models.Transaction.recurring_item_id (Task 2);
card-item matching (item.card_id set) uses
models.CreditCardTransaction.recurring_item_id (Task 4). "Matched" wins over
"skipped": finding both a RecurringSkip row and a linked transaction for the
same (item, year, month) deletes the stale skip row rather than reporting
matched while leaving the database in a contradictory state.
"""
from datetime import date
from decimal import Decimal
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.dependencies import get_current_user, get_db
from backend.routers import recurring as recurring_router_module
from backend.services.recurring_floating_status import build_floating_status


def _floating_item(user, account, **overrides) -> models.RecurringItem:
    kwargs = dict(
        user_id=user.id, account_id=account.id, name="Test Cleaning Co",
        amount=Decimal("150.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=0,
        start_date=date(2026, 1, 1), is_floating=True,
    )
    kwargs.update(overrides)
    return models.RecurringItem(**kwargs)


def test_pending_when_no_skip_or_match(db_session, test_user, test_account):
    item = _floating_item(test_user, test_account)
    db_session.add(item)
    db_session.commit()

    out = build_floating_status(db_session, test_user.id, 2026, 11)

    assert len(out) == 1
    assert out[0].recurring_item_id == item.id
    assert out[0].status == "pending"
    assert out[0].matched_date is None
    assert out[0].matched_amount is None
    assert out[0].variance is None


def test_skipped_when_skip_row_exists(db_session, test_user, test_account):
    item = _floating_item(test_user, test_account)
    db_session.add(item)
    db_session.flush()
    db_session.add(models.RecurringSkip(
        user_id=test_user.id, recurring_item_id=item.id, year=2026, month=11,
    ))
    db_session.commit()

    out = build_floating_status(db_session, test_user.id, 2026, 11)

    assert out[0].status == "skipped"
    assert out[0].matched_date is None


def test_matched_wins_over_skip(db_session, test_user, test_account):
    item = _floating_item(test_user, test_account)
    db_session.add(item)
    db_session.flush()
    db_session.add(models.RecurringSkip(
        user_id=test_user.id, recurring_item_id=item.id, year=2026, month=11,
    ))
    txn = models.Transaction(
        user_id=test_user.id, account_id=test_account.id,
        recurring_item_id=item.id, date=date(2026, 11, 22),
        amount=Decimal("-150.00"), description="Test Cleaning Co payment",
    )
    db_session.add(txn)
    db_session.commit()

    out = build_floating_status(db_session, test_user.id, 2026, 11)

    assert out[0].status == "matched"
    assert out[0].matched_date == date(2026, 11, 22)
    assert out[0].matched_amount == Decimal("150.00")
    assert out[0].variance == Decimal("0.00")

    # The stale skip row is left in place -- it simply has no effect once a
    # real match exists, consistently everywhere (effective_skips(), shared
    # with month_base.py/forecast_engine.py), rather than being deleted as a
    # side effect of this one read.
    remaining = db_session.query(models.RecurringSkip).filter_by(
        recurring_item_id=item.id,
    ).count()
    assert remaining == 1


def test_matched_variance_reflects_amount_difference(db_session, test_user, test_account):
    item = _floating_item(test_user, test_account, amount=Decimal("150.00"))
    db_session.add(item)
    db_session.flush()
    txn = models.Transaction(
        user_id=test_user.id, account_id=test_account.id,
        recurring_item_id=item.id, date=date(2026, 11, 5),
        amount=Decimal("-162.50"), description="Test Cleaning Co payment",
    )
    db_session.add(txn)
    db_session.commit()

    out = build_floating_status(db_session, test_user.id, 2026, 11)

    assert out[0].status == "matched"
    assert out[0].matched_amount == Decimal("162.50")
    assert out[0].variance == Decimal("12.50")


def test_card_linked_item_matches_credit_card_transaction(db_session, test_user, test_account, test_card):
    """A floating item charged to a card (card_id set) matches against
    CreditCardTransaction.recurring_item_id (Task 4), not the checking
    Transaction table."""
    item = _floating_item(
        test_user, test_account, name="Test Haircut", amount=Decimal("45.00"),
        card_id=test_card.id,
    )
    db_session.add(item)
    db_session.flush()
    card_txn = models.CreditCardTransaction(
        user_id=test_user.id, card_id=test_card.id,
        recurring_item_id=item.id, date=date(2026, 11, 10),
        amount=Decimal("45.00"), merchant="Test Barber Shop",
    )
    db_session.add(card_txn)
    db_session.commit()

    out = build_floating_status(db_session, test_user.id, 2026, 11)

    assert out[0].status == "matched"
    assert out[0].matched_date == date(2026, 11, 10)
    assert out[0].matched_amount == Decimal("45.00")
    assert out[0].variance == Decimal("0.00")


def test_match_outside_month_is_not_matched(db_session, test_user, test_account):
    """A linked transaction dated in a different month must not satisfy
    this month's status -- it should still read pending (no skip exists)."""
    item = _floating_item(test_user, test_account)
    db_session.add(item)
    db_session.flush()
    txn = models.Transaction(
        user_id=test_user.id, account_id=test_account.id,
        recurring_item_id=item.id, date=date(2026, 10, 30),
        amount=Decimal("-150.00"), description="Test Cleaning Co payment",
    )
    db_session.add(txn)
    db_session.commit()

    out = build_floating_status(db_session, test_user.id, 2026, 11)

    assert out[0].status == "pending"


def test_inactive_item_excluded(db_session, test_user, test_account):
    item = _floating_item(test_user, test_account, is_active=False)
    db_session.add(item)
    db_session.commit()

    out = build_floating_status(db_session, test_user.id, 2026, 11)

    assert out == []


def test_non_floating_item_excluded(db_session, test_user, test_account):
    item = _floating_item(test_user, test_account, is_floating=False, day_of_month=1)
    db_session.add(item)
    db_session.commit()

    out = build_floating_status(db_session, test_user.id, 2026, 11)

    assert out == []


def test_item_not_yet_started_excluded(db_session, test_user, test_account):
    """Regression: the status list used to show every active floating item
    for the requested month with no frequency/start_date/end_date check at
    all -- an item that hasn't started yet could show "Pending -- expected
    this month" with a Skip button even though month_base/forecast_engine
    correctly exclude it. _fires_in_month() now gates this the same way."""
    item = _floating_item(test_user, test_account, start_date=date(2026, 12, 1))
    db_session.add(item)
    db_session.commit()

    out = build_floating_status(db_session, test_user.id, 2026, 11)

    assert out == []

    # The month it actually starts in still shows it.
    out_december = build_floating_status(db_session, test_user.id, 2026, 12)
    assert len(out_december) == 1


def test_already_ended_item_excluded(db_session, test_user, test_account):
    item = _floating_item(test_user, test_account, end_date=date(2026, 10, 31))
    db_session.add(item)
    db_session.commit()

    out = build_floating_status(db_session, test_user.id, 2026, 11)

    assert out == []


def test_non_monthly_floating_item_excluded(db_session, test_user, test_account):
    """Nothing at the data layer ties is_floating to frequency == monthly
    (schemas.py's RecurringCreate/RecurringUpdate validators reject this
    combination through the API, but a row created directly, or one from
    before that validation existed, could still have it) -- a
    weekly/quarterly/yearly item flagged is_floating must not show a
    Matched/Pending/Skipped row for every one of its several occurrences a
    month collapsed into one."""
    item = _floating_item(
        test_user, test_account, frequency=models.RecurringFrequency.weekly,
        day_of_month=0, start_date=date(2026, 1, 5),
    )
    db_session.add(item)
    db_session.commit()

    out = build_floating_status(db_session, test_user.id, 2026, 11)

    assert out == []


# ── Router-level tests ────────────────────────────────────────────────────────
# Mirrors test_recurring_router.py's local client fixture: this repo wires
# auth via a get_current_user dependency override rather than a bearer-token
# auth_headers fixture, so no header is needed here either.

@pytest.fixture()
def client(db_session):
    user = models.User(username="dan", hashed_password="x", display_name="the user")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    checking = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking)
    db_session.add(checking)
    db_session.commit()
    db_session.refresh(checking)

    app = FastAPI()
    app.include_router(recurring_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app), user, checking


def test_endpoint_returns_status_rows(client, db_session):
    test_client, user, checking = client
    item = _floating_item(user, checking)
    db_session.add(item)
    db_session.commit()

    resp = test_client.get("/recurring/floating-status", params={"year": 2026, "month": 11})

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["recurring_item_id"] == item.id
    assert body[0]["status"] == "pending"


def test_endpoint_rejects_invalid_month(client):
    test_client, _user, _checking = client
    resp = test_client.get("/recurring/floating-status", params={"year": 2026, "month": 13})
    assert resp.status_code == 400


def test_endpoint_rejects_invalid_year(client):
    test_client, _user, _checking = client
    resp = test_client.get("/recurring/floating-status", params={"year": 0, "month": 11})
    assert resp.status_code == 400
