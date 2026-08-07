from decimal import Decimal
from datetime import date
from backend import models
from backend.services.forecast_engine import _compute_transfer_schedule


def test_buffer_transfer_rule_persists_with_expected_defaults(db_session):
    user = models.User(username="t", hashed_password="x", display_name="T")
    db_session.add(user)
    db_session.flush()
    savings = models.Account(user_id=user.id, name="Savings", type=models.AccountType.savings, current_balance=Decimal("0"))
    checking = models.Account(user_id=user.id, name="Main Checking", type=models.AccountType.checking, current_balance=Decimal("0"))
    db_session.add_all([savings, checking])
    db_session.flush()

    rule = models.BufferTransferRule(
        user_id=user.id,
        from_account_id=savings.id,
        to_account_id=checking.id,
        action_threshold=Decimal("100.00"),
        target_floor=Decimal("200.00"),
        increment=Decimal("1000.00"),
        check_day=1,
    )
    db_session.add(rule)
    db_session.commit()
    db_session.refresh(rule)

    assert rule.id is not None
    assert rule.is_active is True
    assert rule.from_account.name == "Savings"
    assert rule.to_account.name == "Main Checking"
    assert savings.outgoing_buffer_rules == [rule]
    assert checking.incoming_buffer_rules == [rule]


def _make_user_accounts(db):
    user = models.User(username="t2", hashed_password="x", display_name="T2")
    db.add(user)
    db.flush()
    savings = models.Account(user_id=user.id, name="Savings", type=models.AccountType.savings, current_balance=Decimal("0"))
    checking = models.Account(user_id=user.id, name="Main Checking", type=models.AccountType.checking, current_balance=Decimal("500.00"))
    db.add_all([savings, checking])
    db.flush()
    return user, savings, checking


def _make_rule(db, user, savings, checking, action=Decimal("100"), floor=Decimal("200"), increment=Decimal("1000"), check_day=1):
    rule = models.BufferTransferRule(
        user_id=user.id, from_account_id=savings.id, to_account_id=checking.id,
        action_threshold=action, target_floor=floor, increment=increment, check_day=check_day,
    )
    db.add(rule)
    db.flush()
    return rule


def test_schedule_empty_when_balance_never_dips_below_action_threshold(db_session):
    user, savings, checking = _make_user_accounts(db_session)
    rule = _make_rule(db_session, user, savings, checking)
    db_session.commit()

    schedule = _compute_transfer_schedule(db_session, user.id, rule, date(2026, 7, 1), date(2026, 7, 31))
    assert schedule == {}


def test_schedule_injects_rounded_up_transfer_when_shortfall_detected(db_session):
    user, savings, checking = _make_user_accounts(db_session)
    rule = _make_rule(db_session, user, savings, checking)
    # Checking starts at $500, one big expense on 7/15 drops it to -$2,625.
    # start_date is July 1st (not Jan 1st) so the bill doesn't fire in the
    # Jan-June months that the schedule now dry-runs through internally
    # (it's anchored at Jan 1 of the queried year regardless of the caller's
    # start_date -- see _compute_transfer_schedule docstring).
    db_session.add(models.RecurringItem(
        user_id=user.id, account_id=checking.id, name="Big Bill", amount=Decimal("3125.00"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=15, start_date=date(2026, 7, 1),
    ))
    db_session.commit()

    schedule = _compute_transfer_schedule(db_session, user.id, rule, date(2026, 7, 1), date(2026, 7, 31))

    # Raw low is -$2,625; shortfall to $200 floor is $2,825 -> rounds up to $3,000.
    assert schedule == {date(2026, 7, 1): Decimal("3000.00")}


def test_schedule_carries_prior_transfer_credit_into_next_month(db_session):
    user, savings, checking = _make_user_accounts(db_session)
    rule = _make_rule(db_session, user, savings, checking)
    # $3,125 bill on the 15th, $3,000 paycheck on the 20th, every month.
    # The raw (no-transfer) trajectory is cumulative across the whole window,
    # so August's raw low is deeper than July's -- this test exists to prove
    # the credit from July's injected transfer is carried forward correctly
    # rather than each month being evaluated against a reset baseline.
    # start_date is July 1st (not Jan 1st) for the same reason as above -- so
    # these items don't fire in the Jan-June months the schedule now
    # dry-runs through internally regardless of the caller's start_date.
    db_session.add_all([
        models.RecurringItem(
            user_id=user.id, account_id=checking.id, name="Big Bill", amount=Decimal("3125.00"),
            type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
            day_of_month=15, start_date=date(2026, 7, 1),
        ),
        models.RecurringItem(
            user_id=user.id, account_id=checking.id, name="Paycheck", amount=Decimal("3000.00"),
            type=models.RecurringType.income, frequency=models.RecurringFrequency.monthly,
            day_of_month=20, start_date=date(2026, 7, 1),
        ),
    ])
    db_session.commit()

    schedule = _compute_transfer_schedule(db_session, user.id, rule, date(2026, 7, 1), date(2026, 8, 31))

    # July: raw low is -$2,625 (500 open - $3,125 bill, before the day-20
    # paycheck) -> shortfall to the $200 floor is $2,825, rounds up to $3,000.
    assert schedule[date(2026, 7, 1)] == Decimal("3000.00")
    # August: raw low (cumulative, still no transfers applied) is -$2,750.
    # Credited with July's +$3,000 that's $250 -- already clears both the
    # $100 action threshold and the $200 floor, so no second transfer fires.
    assert date(2026, 8, 1) not in schedule


def test_schedule_is_independent_of_caller_window_start(db_session):
    """Regression guard for the window-dependence bug: /forecast/quarters
    calls _compute_transfer_schedule (indirectly, via build_forecast) with
    start_date=Jan 1 of the year, while /forecast/risk calls it with
    start_date=date.today() -- some arbitrary mid-year day. Both must land on
    the exact same August transfer amount for the same account/rule, because
    the schedule is supposed to be a property of the account and rule, not of
    which window the caller happened to request.
    """
    user, savings, checking = _make_user_accounts(db_session)
    rule = _make_rule(db_session, user, savings, checking)
    # Monthly bill big enough to force an August transfer, no offsetting
    # income, starting at the beginning of the year like a real recurring
    # item would.
    db_session.add(models.RecurringItem(
        user_id=user.id, account_id=checking.id, name="Big Bill", amount=Decimal("3125.00"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=15, start_date=date(2026, 1, 1),
    ))
    db_session.commit()

    end_date = date(2026, 8, 31)

    # Full-year window, as build_quarters/build_forecast(Jan 1) would request.
    full_year_schedule = _compute_transfer_schedule(
        db_session, user.id, rule, date(2026, 1, 1), end_date
    )
    # Mid-August window, as /forecast/risk querying from date.today() would
    # request on any day of August after the 1st.
    mid_month_schedule = _compute_transfer_schedule(
        db_session, user.id, rule, date(2026, 8, 15), end_date
    )

    august = date(2026, 8, 1)
    assert august in full_year_schedule
    assert august in mid_month_schedule
    assert full_year_schedule[august] == mid_month_schedule[august]
