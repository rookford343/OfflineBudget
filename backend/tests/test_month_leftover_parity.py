"""The Recurring page's Left over and the Dashboard's Leftover are one number.

They used to be two models of the month and disagreed every month: the
snapshot took monthly income only, base bill amounts, quarterly bills spread
over three months, and subtracted Groceries and Savings; the Recurring strip
took every real occurrence at this month's amount but no budgets. Neither
counted the Social Security boost the forecast already adds once the wage
base is met. Both now read services/month_base.build_month_base.

All figures are invented.
"""
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from backend import models
from backend.services.budget_snapshot import compute_budget_snapshot, leftover_parts
from backend.services.explain import children_consistent, replay
from backend.services.forecast_engine import build_forecast, ss_paycheck_boosts
from backend.services.month_summary import build_month_summary
from backend.tests.test_budget_snapshot import _fake_quarter_min

D = Decimal
GROSS = D("6932.14")
NET = D("4895.60")
BOOST = (GROSS * D("0.062")).quantize(D("0.01"))  # 429.79
WAGE_BASE = D("13864.28")
TODAY = date(2026, 11, 2)  # Nov 15 2026 is a Sunday: paid Friday the 13th


def _freeze_today(monkeypatch, fixed: date = TODAY) -> date:
    class _FixedDate(date):
        @classmethod
        def today(cls):
            return fixed
    monkeypatch.setattr("backend.services.forecast_engine.date", _FixedDate)
    return fixed


def _seed(db, name, *, remaining: Decimal, strategy: str = "save_monthly"):
    """Paid on the 15th and the last day. `remaining` is the gross left under
    the wage base before November's first paycheck (legacy ss_bonus_ytd mode,
    no paycheck actuals on record)."""
    user = models.User(
        username=name, hashed_password="x", display_name=name,
        ss_gross_per_paycheck=GROSS, ss_wage_base=WAGE_BASE,
        ss_bonus_ytd=WAGE_BASE - remaining, savings_strategy=strategy,
    )
    db.add(user)
    db.flush()
    checking = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=D("10000.00"),
    )
    db.add(checking)
    db.flush()
    for day in (15, 0):
        db.add(models.RecurringItem(
            user_id=user.id, account_id=checking.id, name="Paycheck", amount=NET,
            type=models.RecurringType.income, frequency=models.RecurringFrequency.monthly,
            day_of_month=day, start_date=date(2026, 1, 1),
        ))
    db.flush()
    return user, checking


def _expense(db, user, acct, name, amount, **kw):
    kw.setdefault("frequency", models.RecurringFrequency.monthly)
    kw.setdefault("day_of_month", 10)
    item = models.RecurringItem(
        user_id=user.id, account_id=acct.id, name=name, amount=D(amount),
        type=models.RecurringType.expense, start_date=date(2026, 1, 5), **kw,
    )
    db.add(item)
    db.flush()
    return item


def _budget(db, user, name, amount, month=0):
    cat = db.query(models.Category).filter_by(user_id=user.id, name=name).first()
    if cat is None:
        cat = models.Category(user_id=user.id, name=name, type=models.CategoryType.expense)
        db.add(cat)
        db.flush()
    db.add(models.BudgetAllocation(
        user_id=user.id, category_id=cat.id, year=2026, month=month, budgeted_amount=D(amount),
    ))


def _snapshot(db, user, checking, as_of=TODAY):
    db.commit()
    with patch("backend.services.budget_snapshot.build_forecast", return_value=_fake_quarter_min("3000.00")):
        return compute_budget_snapshot(db, user, checking.id, as_of=as_of)


def _forecast_paychecks(db, user, checking, start, end):
    entries = build_forecast(db, user.id, checking.id, start, end)
    return [(e.date, t.amount) for e in entries for t in e.transactions
            if t.name == "Paycheck" and not t.is_actual]


def test_base_met_before_the_month_both_screens_count_two_boosts(db_session, monkeypatch):
    _freeze_today(monkeypatch)
    user, checking = _seed(db_session, "ssmet", remaining=D("0"))

    summary = build_month_summary(db_session, user.id, 2026, 11)
    parts = leftover_parts(db_session, user, TODAY)
    snap = _snapshot(db_session, user, checking)

    assert [o.ss_boost for o in summary.income_items] == [BOOST, BOOST]
    assert summary.ss_boost_total == 2 * BOOST
    assert summary.income_total == 2 * (NET + BOOST)
    assert parts.income == 2 * (NET + BOOST)
    assert snap.leftover == 2 * (NET + BOOST)


def test_crossing_paycheck_gets_the_forecasts_partial_boost(db_session, monkeypatch):
    """Pay-stub checkpoint mode, as of the Oct 31 paycheck (a Saturday, so
    paid Friday Oct 30): about half a paycheck of base is left, so the Nov 15
    check (paid Friday the 13th) crosses it."""
    _freeze_today(monkeypatch)
    user, checking = _seed(db_session, "sscross", remaining=D("0"))
    user.ss_withheld_ytd = D("650.00")
    user.ss_withheld_ytd_as_of = date(2026, 10, 30)
    db_session.commit()
    left = WAGE_BASE - (D("650.00") / D("0.062")).quantize(D("0.01"))
    assert 0 < left < GROSS
    partial = ((GROSS - left) * D("0.062")).quantize(D("0.01"))  # only wages above the base

    boosts = ss_paycheck_boosts(
        db_session, user,
        db_session.query(models.RecurringItem).filter_by(user_id=user.id).all(), 2026, 11,
    )
    forecast = _forecast_paychecks(db_session, user, checking, TODAY, date(2026, 11, 30))

    assert forecast == [(date(2026, 11, 13), NET + partial), (date(2026, 11, 30), NET + BOOST)]
    assert sorted(boosts.values()) == [partial, BOOST]
    summary = build_month_summary(db_session, user.id, 2026, 11)
    assert [(o.date, o.amount) for o in summary.income_items] == [
        (date(2026, 11, 15), NET + partial),  # listed on its own date, boosted as booked
        (date(2026, 11, 30), NET + BOOST),
    ]
    assert leftover_parts(db_session, user, TODAY).ss_boost == partial + BOOST


def test_january_has_no_boost_until_the_new_base_is_met(db_session, monkeypatch):
    _freeze_today(monkeypatch)
    user, checking = _seed(db_session, "ssjan", remaining=D("0"))
    db_session.commit()

    summary = build_month_summary(db_session, user.id, 2027, 1)
    forecast = _forecast_paychecks(db_session, user, checking, TODAY, date(2027, 1, 31))

    assert summary.ss_boost_total == 0
    assert summary.income_total == 2 * NET
    assert [amt for d, amt in forecast if d.year == 2027] == [NET, NET]
    assert [amt for d, amt in forecast if d.month == 12] == [NET + BOOST, NET + BOOST]
    dec = build_month_summary(db_session, user.id, 2026, 12)
    assert dec.ss_boost_total == 2 * BOOST


def _full_month(db, user, checking):
    card = models.CreditCard(
        user_id=user.id, name="Test Visa", credit_limit=D("10000.00"),
        statement_day=28, due_day=25, current_balance=D("0"), balance_due=D("0"),
        pending_charges=D("0"),
    )
    db.add(card)
    db.flush()
    electric = _expense(db, user, checking, "Electric", "200.00", day_of_month=8)
    db.add(models.BillAmountOverride(
        user_id=user.id, recurring_item_id=electric.id, due_date=date(2026, 11, 8),
        actual_amount=D("212.40"),
    ))
    _expense(db, user, checking, "Lawn", "25.00",  # Mondays: Nov 2, 9, 16, 23, 30
             frequency=models.RecurringFrequency.weekly, day_of_month=0)
    _expense(db, user, checking, "Stormwater", "15.00",  # Feb/May/Aug/Nov, last day
             frequency=models.RecurringFrequency.quarterly, month_of_year=2, day_of_month=0)
    _expense(db, user, checking, "Insurance", "600.00",
             frequency=models.RecurringFrequency.yearly, month_of_year=11, day_of_month=3)
    _expense(db, user, checking, "Streaming", "20.00", day_of_month=12, card_id=card.id)
    db.add_all([
        models.PlannedExpense(user_id=user.id, name="New tires", amount=D("300.00"),
                              expected_date=date(2026, 11, 20)),
        models.PlannedExpense(user_id=user.id, name="Refund", amount=D("100.00"),
                              expected_date=date(2026, 11, 21),
                              direction=models.PlannedDirection.inflow),
    ])
    _budget(db, user, "Savings", "1000.00")
    _budget(db, user, "Groceries", "700.00")
    _budget(db, user, "Groceries", "750.00", month=11)  # a month-specific figure wins


def test_recurring_left_over_equals_dashboard_leftover_to_the_cent(db_session, monkeypatch):
    _freeze_today(monkeypatch)
    user, checking = _seed(db_session, "parity", remaining=D("0"))
    _full_month(db_session, user, checking)

    summary = build_month_summary(db_session, user.id, 2026, 11)
    snap = _snapshot(db_session, user, checking)

    income = 2 * (NET + BOOST)
    bills = D("212.40") + 5 * D("25.00") + D("15.00") + D("600.00") + D("20.00")
    expected = income - bills - D("300.00") + D("100.00") - D("1000.00") - D("750.00")
    assert summary.expense_total == bills
    assert summary.groceries_budget == D("750.00")
    assert summary.committed_savings == D("1000.00")
    assert summary.left_over == expected
    assert snap.leftover == expected
    assert summary.left_over_before_budgets == expected + D("1750.00")

    for explanation in (summary.explain["left_over"], snap.explain["left_to_spend"]):
        assert children_consistent(explanation)
    assert replay(summary.explain["left_over"]) == summary.left_over
    leftover_row = snap.explain["left_to_spend"].rows[0]
    assert sum((c.amount for c in leftover_row.children), D("0")) == snap.leftover


def test_pull_from_savings_sets_nothing_aside_on_both(db_session, monkeypatch):
    _freeze_today(monkeypatch)
    user, checking = _seed(db_session, "parpull", remaining=D("0"), strategy="pull_from_savings")
    _full_month(db_session, user, checking)

    summary = build_month_summary(db_session, user.id, 2026, 11)
    snap = _snapshot(db_session, user, checking)

    assert summary.savings_budget == D("1000.00")
    assert summary.committed_savings == 0
    assert summary.left_over == snap.leftover
    assert summary.left_over == summary.left_over_before_budgets - D("750.00")


def test_a_settled_card_one_off_counts_once_in_left_to_spend(db_session, monkeypatch):
    """Leftover subtracts the one-off; its real charge is inside card
    spending too, so Left to Spend adds it back once."""
    _freeze_today(monkeypatch)
    user, checking = _seed(db_session, "cardoneoff", remaining=D("0"))
    card = models.CreditCard(
        user_id=user.id, name="Test Visa", credit_limit=D("10000.00"),
        statement_day=28, due_day=25, current_balance=D("0"), balance_due=D("0"),
        pending_charges=D("0"),
    )
    db_session.add(card)
    db_session.flush()
    db_session.add(models.CreditCardTransaction(
        card_id=card.id, user_id=user.id, date=date(2026, 11, 1), amount=D("200.00"),
        merchant="TIRE SHOP", source=models.CardTransactionSource.bank_sync,
    ))
    db_session.add(models.PlannedExpense(
        user_id=user.id, name="Tires", amount=D("180.00"), expected_date=date(2026, 11, 1),
        card_id=card.id, settled_on=date(2026, 11, 1), actual_amount=D("200.00"),
    ))

    snap = _snapshot(db_session, user, checking)

    assert snap.leftover == 2 * (NET + BOOST) - D("200.00")
    assert snap.left_to_spend == snap.leftover, "the $200 charge must not come off twice"
    assert replay(snap.explain["left_to_spend"]) == snap.left_to_spend
