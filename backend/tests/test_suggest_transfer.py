from datetime import date, timedelta
from decimal import Decimal
from backend import models
from backend.schemas import ForecastEntry
from backend.services.forecast_engine import build_forecast, find_balance_risk, suggest_transfer


def _make_user(db, transfer_increment=None):
    kwargs = {"username": "t", "hashed_password": "x", "display_name": "T"}
    if transfer_increment is not None:
        kwargs["transfer_increment"] = transfer_increment
    user = models.User(**kwargs)
    db.add(user)
    db.flush()
    return user


def _make_accounts(db, user, num_savings=1):
    checking = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking)
    db.add(checking)
    savings_accounts = []
    for i in range(num_savings):
        s = models.Account(user_id=user.id, name=f"Savings {i}", type=models.AccountType.savings)
        db.add(s)
        savings_accounts.append(s)
    db.flush()
    return checking, savings_accounts


# A fixed offset from "today" rather than a hardcoded calendar date: keeps
# every test's risk window comfortably inside suggest_transfer's
# past-date clamp (see test_suggested_date_is_never_in_the_past) no matter
# when the suite actually runs.
R0 = date.today() + timedelta(days=60)


def _risk(at_risk=True, d=None, amount="-500.00", threshold="0"):
    return {
        "at_risk": at_risk,
        "date": d or R0,
        "amount": Decimal(amount) if at_risk else None,
        "threshold": Decimal(threshold),
    }


def _entries(*balances_by_date):
    """Build a minimal ForecastEntry list from (date, balance) pairs."""
    return [
        ForecastEntry(date=d, projected_balance=Decimal(str(b)), transactions=[])
        for d, b in balances_by_date
    ]


def _flat_entries(risk_dict):
    """Entries whose only low point is exactly the risk's first-breach amount.

    Keeps the classic single-dip tests honest: window minimum == risk amount,
    so the suggestion size is unchanged by the window-minimum fix.
    """
    return _entries((risk_dict["date"], risk_dict["amount"]))


def test_no_suggestion_when_not_at_risk(db_session):
    user = _make_user(db_session)
    checking, _ = _make_accounts(db_session, user)
    db_session.commit()

    result = suggest_transfer(db_session, user, checking.id, _risk(at_risk=False), [])

    assert result == {"amount": None, "date": None, "from_account_id": None, "already_planned": False}


def test_suggestion_rounds_up_to_default_increment(db_session):
    user = _make_user(db_session)
    checking, savings = _make_accounts(db_session, user, num_savings=1)
    db_session.commit()

    # shortfall = threshold(0) - window_min(-500) = 500 -> rounds up to 1000 (default increment)
    risk = _risk(amount="-500.00", threshold="0")
    result = suggest_transfer(db_session, user, checking.id, risk, _flat_entries(risk))

    assert result["amount"] == Decimal("1000.00")
    assert result["from_account_id"] == savings[0].id
    assert result["already_planned"] is False
    assert result["date"] == R0.replace(day=1)


def test_suggestion_rounds_up_to_custom_increment(db_session):
    user = _make_user(db_session, transfer_increment=Decimal("500.00"))
    checking, _ = _make_accounts(db_session, user, num_savings=1)
    db_session.commit()

    # shortfall = 500 -> exactly one 500 increment, no rounding needed
    risk = _risk(amount="-500.00", threshold="0")
    result = suggest_transfer(db_session, user, checking.id, risk, _flat_entries(risk))

    assert result["amount"] == Decimal("500.00")


def test_suggestion_leaves_from_account_unset_when_ambiguous(db_session):
    user = _make_user(db_session)
    checking, savings = _make_accounts(db_session, user, num_savings=2)
    db_session.commit()

    risk = _risk()
    result = suggest_transfer(db_session, user, checking.id, risk, _flat_entries(risk))

    assert result["from_account_id"] is None


def test_suggestion_leaves_from_account_unset_when_no_savings(db_session):
    user = _make_user(db_session)
    checking, _ = _make_accounts(db_session, user, num_savings=0)
    db_session.commit()

    risk = _risk()
    result = suggest_transfer(db_session, user, checking.id, risk, _flat_entries(risk))

    assert result["from_account_id"] is None


def test_suggestion_never_suggests_transferring_from_the_account_itself(db_session):
    """Viewing a savings account's own forecast must not suggest moving money
    from that account into itself."""
    user = _make_user(db_session)
    savings = models.Account(user_id=user.id, name="Savings", type=models.AccountType.savings)
    db_session.add(savings)
    db_session.commit()

    risk = _risk()
    result = suggest_transfer(db_session, user, savings.id, risk, _flat_entries(risk))

    assert result["amount"] == Decimal("1000.00")
    assert result["from_account_id"] is None


def test_suggested_date_is_never_in_the_past(db_session):
    """A risk landing in the current calendar month defaults to the 1st of
    that month, which has already passed -- must clamp forward to today
    rather than suggest a transfer date that's already gone."""
    user = _make_user(db_session)
    checking, _ = _make_accounts(db_session, user, num_savings=1)
    db_session.commit()

    risk = _risk(d=date.today())
    result = suggest_transfer(db_session, user, checking.id, risk, _flat_entries(risk))

    assert result["date"] == date.today()


def test_suggested_date_defaults_to_the_first_of_the_risk_month(db_session):
    """The default pull date is the 1st of the month the shortfall lands
    in -- Dan wants the money in before that month's spending starts, not
    a few days before the specific dip."""
    user = _make_user(db_session)
    checking, _ = _make_accounts(db_session, user, num_savings=1)
    db_session.commit()

    risk = _risk(d=R0)
    result = suggest_transfer(db_session, user, checking.id, risk, _flat_entries(risk))

    assert result["date"] == R0.replace(day=1)


def test_suggestion_is_sized_to_the_deepest_dip_not_the_first(db_session):
    """Regression: a shallow dip followed by a deeper one used to size the
    suggestion off the shallow one, leaving the real hole uncovered."""
    user = _make_user(db_session)
    checking, savings = _make_accounts(db_session, user, num_savings=1)
    db_session.commit()

    entries = _entries(
        (R0 - timedelta(days=14), "5000.00"),
        (R0, "-200.00"),                      # shallow dip -- first breach
        (R0 + timedelta(days=5), "3000.00"),
        (R0 + timedelta(days=20), "-8400.00"),  # the real hole
    )
    risk = find_balance_risk(entries, Decimal("0"))
    assert risk["date"] == R0
    assert risk["amount"] == Decimal("-200.00")

    result = suggest_transfer(db_session, user, checking.id, risk, entries)

    # Sized to 8400, not 200: 8400 -> next 1000 increment = 9000
    assert result["amount"] == Decimal("9000.00")


def test_inadequate_existing_plan_still_produces_a_topup(db_session):
    """An active plan that doesn't cover the hole must not suppress the
    suggestion -- build_forecast already netted it out of the entries, so
    what remains is a genuine top-up, not a duplicate."""
    user = _make_user(db_session)
    checking, savings = _make_accounts(db_session, user, num_savings=1)
    db_session.flush()
    db_session.add(models.PlannedTransfer(
        user_id=user.id, from_account_id=savings[0].id, to_account_id=checking.id,
        amount=Decimal("1000.00"), target_date=R0 - timedelta(days=2),
        status=models.PlannedTransferStatus.pending,
    ))
    db_session.commit()

    # Entries are already net of that $1000 injection and still $2500 short.
    entries = _entries(
        (R0 - timedelta(days=2), "1000.00"),
        (R0, "-2500.00"),
    )
    risk = find_balance_risk(entries, Decimal("0"))

    result = suggest_transfer(db_session, user, checking.id, risk, entries)

    assert result["already_planned"] is True  # informational only
    assert result["amount"] == Decimal("3000.00")
    assert result["date"] == R0.replace(day=1)
    assert result["from_account_id"] == savings[0].id


def test_adequate_existing_plan_never_reaches_the_suggestion_branch(db_session):
    """End-to-end: once an adequate pending transfer is injected by
    build_forecast, the account is no longer at risk at all, so no bogus
    suggestion is produced. Suppression by adequacy, not by existence."""
    user = _make_user(db_session)
    checking = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("500.00"),
    )
    savings = models.Account(
        user_id=user.id, name="Savings", type=models.AccountType.savings,
        current_balance=Decimal("50000.00"),
    )
    db_session.add_all([checking, savings])
    db_session.flush()

    start = date.today()
    db_session.add(models.RecurringItem(
        user_id=user.id, account_id=checking.id, name="Big Bill",
        amount=Decimal("2000.00"), type=models.RecurringType.expense,
        day_of_month=(start + timedelta(days=10)).day,
        frequency=models.RecurringFrequency.monthly,
        start_date=start, is_active=True, include_in_forecast=True,
    ))
    db_session.add(models.PlannedTransfer(
        user_id=user.id, from_account_id=savings.id, to_account_id=checking.id,
        amount=Decimal("5000.00"), target_date=start + timedelta(days=5),
        status=models.PlannedTransferStatus.pending,
    ))
    db_session.commit()

    entries = build_forecast(db_session, user.id, checking.id, start, start + timedelta(days=20))
    risk = find_balance_risk(entries, Decimal("0"))
    assert risk["at_risk"] is False

    result = suggest_transfer(db_session, user, checking.id, risk, entries)

    assert result["amount"] is None
    assert result["date"] is None
    assert result["from_account_id"] is None


def test_verified_transfer_does_not_suppress_a_new_suggestion(db_session):
    """A verified transfer means the real transaction already happened and
    is reflected in actuals -- a NEW risk near the same date needs its own
    new suggestion, and already_planned must stay False for it."""
    user = _make_user(db_session)
    checking, savings = _make_accounts(db_session, user, num_savings=1)
    db_session.flush()
    db_session.add(models.PlannedTransfer(
        user_id=user.id, from_account_id=savings[0].id, to_account_id=checking.id,
        amount=Decimal("1000.00"), target_date=R0 - timedelta(days=2),
        status=models.PlannedTransferStatus.verified,
    ))
    db_session.commit()

    risk = _risk(d=R0)
    result = suggest_transfer(db_session, user, checking.id, risk, _flat_entries(risk))

    assert result["already_planned"] is False
    assert result["amount"] == Decimal("1000.00")
