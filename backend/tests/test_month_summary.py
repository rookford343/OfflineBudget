"""GET /recurring/month-summary and its service, backend.services.month_summary.

Real month totals for the Recurring page: every occurrence of every active
recurring item that fires in the given calendar month (via forecast_engine's
own `_fires_on`, so this can never disagree with the day-by-day forecast),
plus one-off PlannedExpense rows landing in that month.
"""
from datetime import date
from decimal import Decimal
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.dependencies import get_db, get_current_user
from backend.routers import recurring as recurring_router_module
from backend.services.month_summary import build_month_summary


def _user(db, username="msu"):
    user = models.User(username=username, hashed_password="x", display_name="M")
    db.add(user)
    db.flush()
    return user


def _account(db, user):
    acct = models.Account(
        user_id=user.id, name="Chk", type=models.AccountType.checking,
        current_balance=Decimal("0"),
    )
    db.add(acct)
    db.flush()
    return acct


def _item(db, user, acct, **kwargs):
    defaults = dict(
        user_id=user.id, account_id=acct.id, name="Item", amount=Decimal("100.00"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=15, start_date=date(2020, 1, 1), is_active=True,
    )
    defaults.update(kwargs)
    item = models.RecurringItem(**defaults)
    db.add(item)
    db.flush()
    return item


def _client(db_session, user):
    app = FastAPI()
    app.include_router(recurring_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_monthly_bill_counted_once(db_session):
    user = _user(db_session)
    acct = _account(db_session, user)
    _item(db_session, user, acct, name="Streaming Service", amount=Decimal("15.00"), day_of_month=10)
    db_session.commit()

    summary = build_month_summary(db_session, user.id, 2026, 6)

    dates = [o.date for o in summary.monthly_bills if o.name == "Streaming Service"]
    assert dates == [date(2026, 6, 10)]
    assert summary.monthly_bills_total == Decimal("15.00")


def test_last_day_bill(db_session):
    user = _user(db_session)
    acct = _account(db_session, user)
    _item(db_session, user, acct, name="Rent", amount=Decimal("1200.00"), day_of_month=0)
    db_session.commit()

    summary = build_month_summary(db_session, user.id, 2026, 4)  # April has 30 days

    assert [o.date for o in summary.monthly_bills if o.name == "Rent"] == [date(2026, 4, 30)]


def test_biweekly_counted_two_or_three_times(db_session):
    user = _user(db_session)
    acct = _account(db_session, user)
    _item(
        db_session, user, acct, name="Groceries", amount=Decimal("50.00"),
        frequency=models.RecurringFrequency.biweekly, day_of_month=1, start_date=date(2026, 1, 1),
    )
    db_session.commit()

    summary = build_month_summary(db_session, user.id, 2026, 6)

    count = len([o for o in summary.monthly_bills if o.name == "Groceries"])
    assert count in (2, 3)


def test_yearly_bill_fires_only_in_its_month(db_session):
    user = _user(db_session)
    acct = _account(db_session, user)
    _item(
        db_session, user, acct, name="Car Registration", amount=Decimal("90.00"),
        frequency=models.RecurringFrequency.yearly, month_of_year=6, day_of_month=1,
        start_date=date(2020, 1, 1),
    )
    db_session.commit()

    firing = build_month_summary(db_session, user.id, 2026, 6)
    off = build_month_summary(db_session, user.id, 2026, 7)

    assert len(firing.periodic_due) == 1
    assert firing.periodic_due[0].frequency == models.RecurringFrequency.yearly
    assert len(off.periodic_due) == 0


def test_quarterly_bill_firing_vs_off_month(db_session):
    user = _user(db_session)
    acct = _account(db_session, user)
    _item(
        db_session, user, acct, name="Stormwater", amount=Decimal("14.82"),
        frequency=models.RecurringFrequency.quarterly, month_of_year=3, day_of_month=31,
        start_date=date(2020, 1, 1),
    )
    db_session.commit()

    firing = build_month_summary(db_session, user.id, 2026, 6)  # cycle: 3, 6, 9, 12
    off = build_month_summary(db_session, user.id, 2026, 5)

    assert len(firing.periodic_due) == 1
    assert len(off.periodic_due) == 0


def test_bill_past_end_date_not_counted(db_session):
    user = _user(db_session)
    acct = _account(db_session, user)
    _item(
        db_session, user, acct, name="Old Loan", amount=Decimal("200.00"), day_of_month=5,
        start_date=date(2020, 1, 1), end_date=date(2026, 5, 31),
    )
    db_session.commit()

    summary = build_month_summary(db_session, user.id, 2026, 6)

    assert not any(o.name == "Old Loan" for o in summary.monthly_bills)


def test_bill_before_start_date_not_counted(db_session):
    user = _user(db_session)
    acct = _account(db_session, user)
    _item(
        db_session, user, acct, name="New Subscription", amount=Decimal("9.00"), day_of_month=5,
        start_date=date(2026, 7, 1),
    )
    db_session.commit()

    summary = build_month_summary(db_session, user.id, 2026, 6)

    assert not any(o.name == "New Subscription" for o in summary.monthly_bills)


def test_override_replaces_amount_and_flags_overridden(db_session):
    user = _user(db_session)
    acct = _account(db_session, user)
    item = _item(
        db_session, user, acct, name="Electric", amount=Decimal("180.00"), day_of_month=8,
        start_date=date(2020, 1, 1),
    )
    db_session.add(models.BillAmountOverride(
        user_id=user.id, recurring_item_id=item.id,
        due_date=date(2026, 6, 8), actual_amount=Decimal("224.31"),
    ))
    db_session.commit()

    summary = build_month_summary(db_session, user.id, 2026, 6)

    row = next(o for o in summary.monthly_bills if o.name == "Electric")
    assert row.amount == Decimal("224.31")
    assert row.overridden is True


def test_credit_card_payment_excluded(db_session):
    user = _user(db_session)
    acct = _account(db_session, user)
    _item(
        db_session, user, acct, name="Card Payoff", amount=Decimal("500.00"),
        type=models.RecurringType.credit_card_payment, day_of_month=25, start_date=date(2020, 1, 1),
    )
    db_session.commit()

    summary = build_month_summary(db_session, user.id, 2026, 6)

    names = (
        [o.name for o in summary.monthly_bills]
        + [o.name for o in summary.periodic_due]
        + [o.name for o in summary.income_items]
    )
    assert "Card Payoff" not in names


def test_one_off_unsettled_uses_expected_date_and_amount(db_session):
    user = _user(db_session)
    db_session.add(models.PlannedExpense(
        user_id=user.id, name="Vacation", amount=Decimal("900.00"),
        expected_date=date(2026, 6, 12),
    ))
    db_session.commit()

    summary = build_month_summary(db_session, user.id, 2026, 6)

    row = next(o for o in summary.one_offs if o.name == "Vacation")
    assert row.date == date(2026, 6, 12)
    assert row.amount == Decimal("900.00")
    assert row.settled is False


def test_one_off_settled_uses_actual_amount_and_settled_date(db_session):
    user = _user(db_session)
    db_session.add(models.PlannedExpense(
        user_id=user.id, name="Repair", amount=Decimal("300.00"),
        expected_date=date(2026, 6, 1), settled_on=date(2026, 6, 20),
        actual_amount=Decimal("340.00"),
    ))
    db_session.commit()

    summary = build_month_summary(db_session, user.id, 2026, 6)

    row = next(o for o in summary.one_offs if o.name == "Repair")
    assert row.date == date(2026, 6, 20)
    assert row.amount == Decimal("340.00")
    assert row.settled is True


def test_one_off_out_of_month_excluded(db_session):
    user = _user(db_session)
    db_session.add(models.PlannedExpense(
        user_id=user.id, name="Next Month", amount=Decimal("50.00"),
        expected_date=date(2026, 7, 1),
    ))
    db_session.commit()

    summary = build_month_summary(db_session, user.id, 2026, 6)

    assert not any(o.name == "Next Month" for o in summary.one_offs)


def test_one_off_direction_in_adds(db_session):
    user = _user(db_session)
    db_session.add(models.PlannedExpense(
        user_id=user.id, name="Gift Received", amount=Decimal("1000.00"),
        expected_date=date(2026, 6, 5), direction=models.PlannedDirection.inflow,
    ))
    db_session.commit()

    summary = build_month_summary(db_session, user.id, 2026, 6)

    assert summary.one_off_in_total == Decimal("1000.00")
    assert summary.one_off_out_total == Decimal("0")


def test_left_over_arithmetic(db_session):
    user = _user(db_session)
    acct = _account(db_session, user)
    _item(
        db_session, user, acct, name="Paycheck", amount=Decimal("2000.00"),
        type=models.RecurringType.income, day_of_month=1, start_date=date(2020, 1, 1),
    )
    _item(
        db_session, user, acct, name="Rent", amount=Decimal("1200.00"), day_of_month=1,
        start_date=date(2020, 1, 1),
    )
    db_session.add(models.PlannedExpense(
        user_id=user.id, name="Gift Received", amount=Decimal("100.00"),
        expected_date=date(2026, 6, 10), direction=models.PlannedDirection.inflow,
    ))
    db_session.add(models.PlannedExpense(
        user_id=user.id, name="Furniture", amount=Decimal("300.00"),
        expected_date=date(2026, 6, 15),
    ))
    db_session.commit()

    summary = build_month_summary(db_session, user.id, 2026, 6)

    assert summary.income_total == Decimal("2000.00")
    assert summary.expense_total == Decimal("1200.00")
    assert summary.one_off_in_total == Decimal("100.00")
    assert summary.one_off_out_total == Decimal("300.00")
    assert summary.left_over == (
        Decimal("2000.00") - Decimal("1200.00") - Decimal("300.00") + Decimal("100.00")
    )


def test_other_users_items_never_appear(db_session):
    user_a = _user(db_session, "usera")
    acct_a = _account(db_session, user_a)
    user_b = _user(db_session, "userb")
    acct_b = _account(db_session, user_b)
    _item(db_session, user_a, acct_a, name="A's Bill", day_of_month=10)
    _item(db_session, user_b, acct_b, name="B's Bill", day_of_month=10)
    db_session.commit()

    summary = build_month_summary(db_session, user_a.id, 2026, 6)

    assert [o.name for o in summary.monthly_bills] == ["A's Bill"]


def test_endpoint_returns_200(db_session):
    user = _user(db_session)
    acct = _account(db_session, user)
    _item(db_session, user, acct, name="Item", day_of_month=10)
    db_session.commit()

    resp = _client(db_session, user).get("/recurring/month-summary", params={"year": 2026, "month": 6})

    assert resp.status_code == 200
    assert resp.json()["year"] == 2026
    assert resp.json()["month"] == 6


def test_endpoint_rejects_month_out_of_range(db_session):
    user = _user(db_session)
    db_session.commit()

    resp = _client(db_session, user).get("/recurring/month-summary", params={"year": 2026, "month": 13})

    assert resp.status_code == 400


def test_endpoint_rejects_year_out_of_range(db_session):
    user = _user(db_session)
    db_session.commit()

    resp = _client(db_session, user).get("/recurring/month-summary", params={"year": 0, "month": 6})

    assert resp.status_code == 400
