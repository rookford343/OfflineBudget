"""Bonus allocation: split_bonus's waterfall math, allocation_transfers's
payout walk, and the day-by-day forecast injection. All figures made up."""
from datetime import date
from decimal import Decimal

from backend import models
from backend.services.bonus_allocation import allocation_transfers, round_down, split_bonus
from backend.services.forecast_engine import build_forecast


def _step(account_id, kind, value=None, round_to=None):
    return models.BonusAllocationStep(account_id=account_id, kind=kind, value=value, round_to=round_to)


# ── round_down ────────────────────────────────────────────────────────────

def test_round_down_floors_to_the_multiple():
    assert round_down(Decimal("23656"), Decimal("1000")) == Decimal("23000.00")


def test_round_down_with_no_round_to_just_quantizes_to_cents():
    assert round_down(Decimal("23656.017"), None) == Decimal("23656.02")


def test_round_down_ignores_a_zero_round_to():
    assert round_down(Decimal("23656"), Decimal("0")) == Decimal("23656.00")


# ── split_bonus ───────────────────────────────────────────────────────────

MM = 1
SAVINGS = 2

WATERFALL = [
    _step(MM, "fixed", Decimal("25000")),
    _step(SAVINGS, "rest", round_to=Decimal("1000")),
]


def test_the_brief_example_moves_fixed_then_rounded_down_rest():
    result = split_bonus(Decimal("48656.00"), WATERFALL, None, None)
    assert result == [(MM, Decimal("25000.00")), (SAVINGS, Decimal("23000.00"))]
    moved = sum(amt for _, amt in result)
    assert moved == Decimal("48000.00"), "656.00 stays in checking"


def test_a_shortfall_with_a_shortfall_account_set_sends_it_all_there_rounded_down():
    result = split_bonus(Decimal("20500.00"), WATERFALL, SAVINGS, Decimal("1000"))
    assert result == [(SAVINGS, Decimal("20000.00"))], "500.00 stays in checking"


def test_a_shortfall_with_no_shortfall_account_clamps_the_fixed_step():
    result = split_bonus(Decimal("20500.00"), WATERFALL, None, None)
    assert result == [(MM, Decimal("20500.00"))], (
        "the fixed step eats the whole bonus; nothing is left for the rest step"
    )


def test_percent_step_rounds_down_against_the_total_not_the_remaining():
    steps = [_step(SAVINGS, "percent", Decimal("37"), Decimal("500"))]
    # 10,000 * 37% = 3,700.00, floored to the nearest 500 -> 3,500.00
    result = split_bonus(Decimal("10000.00"), steps, None, None)
    assert result == [(SAVINGS, Decimal("3500.00"))]


def test_a_rest_step_alone_takes_whatever_remains_rounded_down():
    steps = [_step(SAVINGS, "rest", round_to=Decimal("1000"))]
    result = split_bonus(Decimal("12345.00"), steps, None, None)
    assert result == [(SAVINGS, Decimal("12000.00"))]


def test_transfers_never_total_more_than_the_total():
    # Two percent steps that would overlap (60% + 60% of the total) must
    # still clamp to what's left, never moving more than the bonus itself.
    steps = [
        _step(MM, "percent", Decimal("60")),
        _step(SAVINGS, "percent", Decimal("60")),
    ]
    result = split_bonus(Decimal("1000.00"), steps, None, None)
    assert sum(amt for _, amt in result) == Decimal("1000.00")
    assert result == [(MM, Decimal("600.00")), (SAVINGS, Decimal("400.00"))]


def test_zero_amounts_are_skipped():
    steps = [
        _step(MM, "fixed", Decimal("25000")),
        _step(SAVINGS, "rest"),
    ]
    # Fixed step takes it all; the rest step would be exactly 0 and must not
    # appear in the result.
    result = split_bonus(Decimal("25000.00"), steps, None, None)
    assert result == [(MM, Decimal("25000.00"))]


# ── allocation_transfers ────────────────────────────────────────────────

def _seed_plan(db, user, checking, *, month, day, fixed_gross, withholding="30", year=2027):
    """A single yearly-income bonus item + plan with a fixed gross for one
    year, so net is known without relying on the salary formula."""
    item = models.RecurringItem(
        user_id=user.id, account_id=checking.id, name=f"Bonus {month}-{day}", amount=Decimal("1"),
        type=models.RecurringType.income, frequency=models.RecurringFrequency.yearly,
        month_of_year=month, day_of_month=day, start_date=date(2020, 1, 1),
    )
    db.add(item)
    db.flush()
    plan = models.BonusPlan(user_id=user.id, recurring_item_id=item.id, target_pct=Decimal("20"),
                            salary_lag_years=1, withholding_pct=Decimal(withholding))
    db.add(plan)
    db.flush()
    db.add(models.BonusPlanYear(plan_id=plan.id, year=year, gross_amount=Decimal(fixed_gross)))
    db.commit()
    return item, plan


def _seed_user_and_accounts(db, username):
    user = models.User(username=username, hashed_password="x", display_name="A",
                       annual_salary=Decimal("100000"), annual_salary_year=2026, annual_raise_pct=Decimal("0"))
    db.add(user)
    db.flush()
    checking = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking,
                              current_balance=Decimal("0"))
    mm = models.Account(user_id=user.id, name="Money Market", type=models.AccountType.money_market,
                        current_balance=Decimal("0"))
    savings = models.Account(user_id=user.id, name="Savings", type=models.AccountType.savings,
                             current_balance=Decimal("0"))
    db.add_all([checking, mm, savings])
    db.flush()
    return user, checking, mm, savings


def _add_steps(db, user, steps, shortfall_account_id=None, shortfall_round_to=None):
    for i, s in enumerate(steps):
        db.add(models.BonusAllocationStep(user_id=user.id, position=i, account_id=s.account_id,
                                          kind=s.kind, value=s.value, round_to=s.round_to))
    user.bonus_shortfall_account_id = shortfall_account_id
    user.bonus_shortfall_round_to = shortfall_round_to
    db.commit()


def test_no_config_returns_an_empty_dict(db_session):
    user, checking, mm, savings = _seed_user_and_accounts(db_session, "at1")
    _seed_plan(db_session, user, checking, month=4, day=15, fixed_gross="20000")
    # No steps and no shortfall account configured at all.
    assert allocation_transfers(db_session, user, date(2027, 1, 1), date(2027, 12, 31)) == {}


def test_a_weekend_payout_shifts_to_friday(db_session):
    user, checking, mm, savings = _seed_user_and_accounts(db_session, "at2")
    # 2027-05-15 is a Saturday (see test_bonus_forecast.py's own comment).
    _seed_plan(db_session, user, checking, month=5, day=15, fixed_gross="20000")
    _add_steps(db_session, user, [_step(mm.id, "fixed", Decimal("5000"))])

    result = allocation_transfers(db_session, user, date(2027, 1, 1), date(2027, 12, 31))

    assert list(result.keys()) == [date(2027, 5, 14)]
    [transfer] = result[date(2027, 5, 14)]
    assert transfer.from_account_id == checking.id
    assert transfer.to_account_id == mm.id
    assert transfer.amount == Decimal("5000.00")
    assert transfer.from_name == "Checking"
    assert transfer.to_name == "Money Market"


def test_two_bonuses_on_the_same_day_are_summed_into_one_split(db_session):
    user, checking, mm, savings = _seed_user_and_accounts(db_session, "at3")
    # Both land 2027-04-15 (a Thursday, no weekend shift) in the same account.
    _seed_plan(db_session, user, checking, month=4, day=15, fixed_gross="10000", withholding="30")  # net 7,000
    _seed_plan(db_session, user, checking, month=4, day=15, fixed_gross="20000", withholding="20")  # net 16,000
    _add_steps(db_session, user, [
        _step(mm.id, "fixed", Decimal("10000")),
        _step(savings.id, "rest", round_to=Decimal("1000")),
    ])

    result = allocation_transfers(db_session, user, date(2027, 1, 1), date(2027, 12, 31))

    assert list(result.keys()) == [date(2027, 4, 15)]
    transfers = {t.to_account_id: t.amount for t in result[date(2027, 4, 15)]}
    # Combined net is 7,000 + 16,000 = 23,000.00 -- fixed step takes 10,000,
    # the rest step takes the remaining 13,000 (already a multiple of 1,000).
    assert transfers == {mm.id: Decimal("10000.00"), savings.id: Decimal("13000.00")}


def test_a_payout_with_a_linked_actual_that_month_produces_nothing(db_session):
    user, checking, mm, savings = _seed_user_and_accounts(db_session, "at4")
    item, _ = _seed_plan(db_session, user, checking, month=4, day=15, fixed_gross="20000")
    db_session.add(models.Transaction(
        user_id=user.id, account_id=checking.id, recurring_item_id=item.id,
        date=date(2027, 4, 16), amount=Decimal("14000.00"), description="BONUS PAYROLL", is_actual=True,
    ))
    db_session.commit()
    _add_steps(db_session, user, [_step(mm.id, "fixed", Decimal("5000"))])

    result = allocation_transfers(db_session, user, date(2027, 1, 1), date(2027, 12, 31))

    assert result == {}, "a real deposit that month means the real transfer takes over, not a projected one"


def test_a_destination_equal_to_the_source_account_is_skipped(db_session):
    user, checking, mm, savings = _seed_user_and_accounts(db_session, "at5")
    _seed_plan(db_session, user, checking, month=4, day=15, fixed_gross="20000")
    # The fixed step's destination IS the source account (checking) --
    # nothing should move since it's already there.
    _add_steps(db_session, user, [_step(checking.id, "fixed", Decimal("5000"))])

    result = allocation_transfers(db_session, user, date(2027, 1, 1), date(2027, 12, 31))

    assert result == {}


# ── Engine: the injected transfer appears on both sides of the forecast ───

def _seed_engine(db):
    user, checking, mm, savings = _seed_user_and_accounts(db, "ae1")
    checking.current_balance = Decimal("1000")
    item, _ = _seed_plan(db, user, checking, month=4, day=15, fixed_gross="20000", withholding="30")  # net 14,000
    _add_steps(db, user, [_step(mm.id, "fixed", Decimal("5000"))])
    return user, checking, mm, savings, item


def test_checking_forecast_shows_the_bonus_in_and_the_transfer_out_same_day(db_session):
    user, checking, mm, savings, item = _seed_engine(db_session)

    entries = build_forecast(db_session, user.id, checking.id, date(2027, 1, 1), date(2027, 12, 31))

    [entry] = [e for e in entries if e.date == date(2027, 4, 15)]
    names = {t.name: t.amount for t in entry.transactions}
    assert names["Bonus 4-15"] == Decimal("14000.00")
    assert names["Bonus transfer to Money Market"] == Decimal("-5000.00")
    transfer_txn = next(t for t in entry.transactions if t.name == "Bonus transfer to Money Market")
    assert transfer_txn.is_transfer and transfer_txn.is_planned_transfer


def test_money_market_forecast_shows_the_matching_inflow_same_day(db_session):
    user, checking, mm, savings, item = _seed_engine(db_session)

    entries = build_forecast(db_session, user.id, mm.id, date(2027, 1, 1), date(2027, 12, 31))

    [entry] = [e for e in entries if e.date == date(2027, 4, 15)]
    names = {t.name: t.amount for t in entry.transactions}
    assert names["Bonus transfer from Checking"] == Decimal("5000.00")
    transfer_txn = next(t for t in entry.transactions if t.name == "Bonus transfer from Checking")
    assert transfer_txn.is_transfer and transfer_txn.is_planned_transfer
