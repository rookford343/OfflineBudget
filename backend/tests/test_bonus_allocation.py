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
    assert round_down(Decimal("23500"), Decimal("1000")) == Decimal("23000.00")


def test_round_down_with_no_round_to_floors_to_cents():
    # A true floor, not Python's default ROUND_HALF_EVEN quantize -- .017
    # must drop to .01, never round up to .02.
    assert round_down(Decimal("100.017"), None) == Decimal("100.01")


def test_round_down_ignores_a_zero_round_to():
    assert round_down(Decimal("23500"), Decimal("0")) == Decimal("23500.00")


# ── split_bonus ───────────────────────────────────────────────────────────

MM = 1
SAVINGS = 2

WATERFALL = [
    _step(MM, "fixed", Decimal("25000")),
    _step(SAVINGS, "rest", round_to=Decimal("1000")),
]


def test_the_brief_example_moves_fixed_then_rounded_down_rest():
    result = split_bonus(Decimal("48500.00"), WATERFALL, None, None)
    assert result == [(MM, Decimal("25000.00")), (SAVINGS, Decimal("23000.00"))]
    moved = sum(amt for _, amt in result)
    assert moved == Decimal("48000.00"), "500.00 stays in checking"


def test_a_shortfall_with_a_shortfall_account_set_sends_it_all_there_rounded_down():
    result = split_bonus(Decimal("19500.00"), WATERFALL, SAVINGS, Decimal("1000"))
    assert result == [(SAVINGS, Decimal("19000.00"))], "500.00 stays in checking"


def test_a_shortfall_rounded_down_below_the_round_to_produces_no_transfer():
    # 400 floored to the nearest 1,000 is 0 -- a (SAVINGS, 0.00) pair would
    # be a no-op transfer; it must not appear in the result at all.
    result = split_bonus(Decimal("400.00"), WATERFALL, SAVINGS, Decimal("1000"))
    assert result == []


def test_a_shortfall_with_no_shortfall_account_clamps_the_fixed_step():
    result = split_bonus(Decimal("19500.00"), WATERFALL, None, None)
    assert result == [(MM, Decimal("19500.00"))], (
        "the fixed step eats the whole bonus; nothing is left for the rest step"
    )


def test_percent_step_rounds_down_against_the_total_not_the_remaining():
    steps = [_step(SAVINGS, "percent", Decimal("37"), Decimal("500"))]
    # 10,000 * 37% = 3,700.00, floored to the nearest 500 -> 3,500.00
    result = split_bonus(Decimal("10000.00"), steps, None, None)
    assert result == [(SAVINGS, Decimal("3500.00"))]


def test_a_rest_step_alone_takes_whatever_remains_rounded_down():
    steps = [_step(SAVINGS, "rest", round_to=Decimal("1000"))]
    result = split_bonus(Decimal("12400.00"), steps, None, None)
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


def test_an_actual_on_the_natural_weekend_date_suppresses_even_across_a_month_boundary(db_session):
    """2027-05-01 is a Saturday, so the payout shifts back to 2027-04-30 (a
    Friday) -- a DIFFERENT month than the natural date. A real deposit dated
    on the natural date (May) must still suppress the Apr-30 projection, even
    though April's own actuals are empty (mirrors build_forecast's own
    adj_actual_recurring_ids check for a Friday pull-forward)."""
    user, checking, mm, savings = _seed_user_and_accounts(db_session, "at6")
    item, _ = _seed_plan(db_session, user, checking, month=5, day=1, fixed_gross="20000")
    db_session.add(models.Transaction(
        user_id=user.id, account_id=checking.id, recurring_item_id=item.id,
        date=date(2027, 5, 1), amount=Decimal("14000.00"), description="BONUS PAYROLL", is_actual=True,
    ))
    db_session.commit()
    _add_steps(db_session, user, [_step(mm.id, "fixed", Decimal("5000"))])

    result = allocation_transfers(db_session, user, date(2027, 1, 1), date(2027, 12, 31))

    assert result == {}, "the actual landed on the natural (pre-shift) date -- the Apr 30 projection must be suppressed too"


def test_an_item_excluded_from_the_forecast_produces_no_transfer(db_session):
    """include_in_forecast=False means the item is real income but already
    spoken for -- build_forecast drops it from the day walk entirely, so a
    transfer "out" of a bonus that was never shown "in" would leave checking
    looking like it dropped for no reason."""
    user, checking, mm, savings = _seed_user_and_accounts(db_session, "at7")
    item, _ = _seed_plan(db_session, user, checking, month=4, day=15, fixed_gross="20000")
    item.include_in_forecast = False
    db_session.commit()
    _add_steps(db_session, user, [_step(mm.id, "fixed", Decimal("5000"))])

    result = allocation_transfers(db_session, user, date(2027, 1, 1), date(2027, 12, 31))

    assert result == {}


def test_a_scenario_override_that_reduces_the_bonus_shrinks_the_split(db_session):
    """The engine computes a projected bonus's amount as
    bonus_net(...) + override_map.get(item.id, 0) -- the split must run on
    THAT amount, not the unmodified net, or a what-if scenario that cuts the
    bonus would still move the old, bigger amount into savings."""
    user, checking, mm, savings = _seed_user_and_accounts(db_session, "at8")
    item, _ = _seed_plan(db_session, user, checking, month=4, day=15, fixed_gross="20000", withholding="30")  # net 14,000
    _add_steps(db_session, user, [_step(mm.id, "fixed", Decimal("5000"))])

    result = allocation_transfers(db_session, user, date(2027, 1, 1), date(2027, 12, 31),
                                  override_map={item.id: Decimal("-11000.00")})

    [transfer] = result[date(2027, 4, 15)]
    assert transfer.amount == Decimal("3000.00"), "net 14,000 - 11,000 override = 3,000, below the 5,000 fixed step"


def test_a_scenario_override_that_zeroes_the_bonus_skips_the_split_entirely(db_session):
    user, checking, mm, savings = _seed_user_and_accounts(db_session, "at9")
    item, _ = _seed_plan(db_session, user, checking, month=4, day=15, fixed_gross="20000", withholding="30")  # net 14,000
    _add_steps(db_session, user, [_step(mm.id, "fixed", Decimal("5000"))])

    result = allocation_transfers(db_session, user, date(2027, 1, 1), date(2027, 12, 31),
                                  override_map={item.id: Decimal("-14000.00")})

    assert result == {}, "the override cancels the bonus out entirely -- nothing lands, so nothing to split"


def test_an_inactive_destination_account_is_skipped(db_session):
    user, checking, mm, savings = _seed_user_and_accounts(db_session, "at10")
    _seed_plan(db_session, user, checking, month=4, day=15, fixed_gross="20000")
    _add_steps(db_session, user, [_step(mm.id, "fixed", Decimal("5000"))])
    mm.is_active = False
    db_session.commit()

    result = allocation_transfers(db_session, user, date(2027, 1, 1), date(2027, 12, 31))

    assert result == {}, "the step's only destination account is inactive -- there's nothing left to split to"


def test_an_inactive_source_account_is_skipped(db_session):
    user, checking, mm, savings = _seed_user_and_accounts(db_session, "at11")
    _seed_plan(db_session, user, checking, month=4, day=15, fixed_gross="20000")
    _add_steps(db_session, user, [_step(mm.id, "fixed", Decimal("5000"))])
    checking.is_active = False
    db_session.commit()

    result = allocation_transfers(db_session, user, date(2027, 1, 1), date(2027, 12, 31))

    assert result == {}, "the bonus item's own (source) account is inactive -- can't transfer out of a closed account"


# ── Important 1: a second users<->accounts fk must not block user deletion ──

def test_a_user_with_a_shortfall_account_set_can_be_deleted(db_session):
    """users.bonus_shortfall_account_id is a SECOND fk into accounts
    (accounts.user_id -> users.id already exists). Deleting the user
    cascades (via User.accounts' delete-orphan) into deleting their accounts
    FIRST, including whichever one this column still points at -- without
    ondelete=SET NULL that's an IntegrityError, and without use_alter=True
    SQLAlchemy can't even sort the two tables for CREATE/DROP (the
    'unresolvable FK cycle' warning)."""
    user, checking, mm, savings = _seed_user_and_accounts(db_session, "del1")
    user.bonus_shortfall_account_id = mm.id
    db_session.commit()

    db_session.delete(user)
    db_session.commit()  # must not raise IntegrityError

    assert db_session.query(models.User).filter(models.User.id == user.id).first() is None


def test_deleting_a_user_works_even_on_the_live_pre_fix_schema():
    """The real data/budget.db already got bonus_shortfall_account_id from
    the PRE-FIX migration line, which has no ON DELETE clause at all --
    upgrade_schema() swallows "duplicate column" on every later run, so it
    can never retrofit ON DELETE SET NULL onto a column that already
    exists there. The actual guard has to live in application code
    (routers/auth.py's delete_account nulls the column before deleting),
    not rely on the fk's own on-delete action -- models.py's fix alone only
    helps a brand-new database.

    Reproduces that live schema by temporarily clearing the
    ForeignKeyConstraint's own ondelete (a separate attribute from the
    ForeignKey object's -- DDL rendering for this table-level constraint
    reads the constraint's copy, not the column-level one) before building
    a throwaway engine, so the emitted CREATE TABLE genuinely lacks "ON
    DELETE SET NULL" -- not just a model that still says it should have
    one. Restored immediately via try/finally regardless of outcome, since
    it mutates the shared, module-level Base.metadata.

    Does NOT use the db_session fixture (that engine's tables are already
    built with the real ondelete baked in before this test body runs);
    needs its own fresh engine built while the attribute is cleared.
    Then calls the REAL delete_account route function (not a hand-written
    equivalent) against it."""
    from sqlalchemy import create_engine, event, text
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from backend.auth import hash_password
    from backend.database import Base
    from backend.routers.auth import delete_account
    from backend.schemas import DeleteAccountRequest

    constraint = next(iter(models.User.__table__.c.bonus_shortfall_account_id.foreign_keys)).constraint
    original_ondelete = constraint.ondelete
    assert original_ondelete == "SET NULL", "models.py's fix changed shape -- update this test"

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _fk_pragma(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    try:
        constraint.ondelete = None
        Base.metadata.create_all(bind=engine)
    finally:
        constraint.ondelete = original_ondelete

    with engine.connect() as conn:
        ddl = conn.execute(text(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='users'"
        )).scalar()
    assert "ON DELETE SET NULL" not in ddl, "the pre-fix schema must genuinely lack the clause"

    db = sessionmaker(bind=engine)()
    try:
        user = models.User(username="u1", hashed_password=hash_password("correct-password"), display_name="U")
        db.add(user)
        db.flush()
        mm = models.Account(user_id=user.id, name="Money Market", type=models.AccountType.money_market,
                            current_balance=Decimal("0"))
        db.add(mm)
        db.flush()
        user.bonus_shortfall_account_id = mm.id
        db.commit()

        delete_account(DeleteAccountRequest(password="correct-password"), db, user)  # must not raise

        assert db.query(models.User).filter(models.User.id == user.id).first() is None
    finally:
        db.close()
        engine.dispose()


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
