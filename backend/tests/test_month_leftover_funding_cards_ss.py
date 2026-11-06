"""Three ways Leftover / Left to Spend disagreed with the forecast, found by
the final review of the month-base rework (2026-11):

1. A one-off funded from savings subtracted its whole amount from Leftover,
   while the forecast adds the funding transfer back into checking -- so
   checking nets to zero. Leftover now counts the funding inflow too, in the
   month the forecast books it, and only moves by any uncovered remainder.
2. A weekly/biweekly card bill came off Left to Spend twice: once as a bill
   in Leftover and once as posted card spending, with no add-back, because
   the card add-back only knew monthly/quarterly/yearly bills (at their base
   amount, so an entered statement amount didn't net either).
3. With a pay stub dated inside the month, the Social Security boost walk
   started at the 1st and drew the base down again for paychecks the stub's
   YTD already held.

All figures are invented.
"""
from datetime import date
from decimal import Decimal

from backend import models
from backend.services.forecast_engine import is_card_bill_in_month, ss_paycheck_boosts
from backend.services.month_summary import build_month_summary
from backend.tests.test_month_leftover_parity import (
    BOOST, GROSS, NET, WAGE_BASE, _expense, _forecast_paychecks, _freeze_today, _seed, _snapshot,
)

D = Decimal
AS_OF = date(2026, 11, 20)
BASE_LEFTOVER = 2 * (NET + BOOST)  # base met: both November paychecks boosted


def _card(db, user):
    card = models.CreditCard(
        user_id=user.id, name="Test Visa", credit_limit=D("10000.00"),
        statement_day=28, due_day=25, current_balance=D("0"), balance_due=D("0"),
        pending_charges=D("0"),
    )
    db.add(card)
    db.flush()
    return card


def _savings(db, user):
    sav = models.Account(
        user_id=user.id, name="Savings", type=models.AccountType.savings,
        current_balance=D("50000.00"),
    )
    db.add(sav)
    db.flush()
    return sav


def _post(db, user, card, day, amount, merchant="GYM"):
    db.add(models.CreditCardTransaction(
        card_id=card.id, user_id=user.id, date=date(2026, 11, day), amount=D(amount),
        merchant=merchant, source=models.CardTransactionSource.bank_sync,
    ))


# -- 1. savings-funded one-offs -------------------------------------------

def test_a_savings_funded_purchase_leaves_leftover_unchanged(db_session, monkeypatch):
    _freeze_today(monkeypatch, AS_OF)
    user, checking = _seed(db_session, "fundfull", remaining=D("0"))
    sav = _savings(db_session, user)
    db_session.add(models.PlannedExpense(
        user_id=user.id, name="Car", amount=D("20000.00"), expected_date=date(2026, 11, 25),
        account_id=checking.id, funding_account_id=sav.id,
    ))

    snap = _snapshot(db_session, user, checking, as_of=AS_OF)
    summary = build_month_summary(db_session, user.id, 2026, 11)

    assert snap.leftover == BASE_LEFTOVER
    assert snap.left_to_spend == BASE_LEFTOVER
    assert summary.left_over == BASE_LEFTOVER
    assert summary.one_off_out_total == D("20000.00")
    assert summary.one_off_in_total == D("20000.00")


def test_a_partly_funded_purchase_moves_leftover_by_the_remainder(db_session, monkeypatch):
    _freeze_today(monkeypatch, AS_OF)
    user, checking = _seed(db_session, "fundpart", remaining=D("0"))
    sav = _savings(db_session, user)
    db_session.add(models.PlannedExpense(
        user_id=user.id, name="Car", amount=D("20000.00"), expected_date=date(2026, 11, 25),
        account_id=checking.id, funding_account_id=sav.id, funding_amount=D("15000.00"),
    ))

    snap = _snapshot(db_session, user, checking, as_of=AS_OF)

    assert snap.leftover == BASE_LEFTOVER - D("5000.00")
    assert snap.left_to_spend == BASE_LEFTOVER - D("5000.00")


def test_funding_lands_in_the_month_the_forecast_books_it(db_session, monkeypatch):
    """funding_lead_days pulls the transfer into October: October gains it,
    November carries the purchase -- the same days the forecast walks."""
    _freeze_today(monkeypatch, date(2026, 10, 1))
    user, checking = _seed(db_session, "fundlead", remaining=D("0"))
    sav = _savings(db_session, user)
    db_session.add(models.PlannedExpense(
        user_id=user.id, name="Car", amount=D("20000.00"), expected_date=date(2026, 11, 3),
        account_id=checking.id, funding_account_id=sav.id, funding_lead_days=7,
    ))
    db_session.commit()

    oct_ = build_month_summary(db_session, user.id, 2026, 10)
    nov = build_month_summary(db_session, user.id, 2026, 11)

    assert oct_.one_off_in_total == D("20000.00") and oct_.one_off_out_total == 0
    assert nov.one_off_out_total == D("20000.00") and nov.one_off_in_total == 0


def test_a_settled_card_routed_funded_purchase_nets_once(db_session, monkeypatch):
    """Charged to a card and funded from savings: the purchase and its funding
    cancel in Leftover, and the posted card charge is added back once, so
    Left to Spend doesn't move either."""
    _freeze_today(monkeypatch, AS_OF)
    user, checking = _seed(db_session, "fundcard", remaining=D("0"))
    sav = _savings(db_session, user)
    card = _card(db_session, user)
    _post(db_session, user, card, 18, "20000.00", merchant="CAR DEALER")
    db_session.add(models.PlannedExpense(
        user_id=user.id, name="Car", amount=D("20000.00"), expected_date=date(2026, 11, 18),
        account_id=checking.id, funding_account_id=sav.id, card_id=card.id,
        settled_on=date(2026, 11, 18), actual_amount=D("20000.00"),
    ))

    snap = _snapshot(db_session, user, checking, as_of=AS_OF)

    assert snap.leftover == BASE_LEFTOVER
    assert snap.left_to_spend == BASE_LEFTOVER


# -- 2. weekly / overridden card bills -------------------------------------

def test_a_weekly_card_bill_comes_off_left_to_spend_once(db_session, monkeypatch):
    """Mondays in Nov 2026: 2, 9, 16, 23, 30. Three have posted by the 20th."""
    _freeze_today(monkeypatch, AS_OF)
    user, checking = _seed(db_session, "wkcard", remaining=D("0"))
    card = _card(db_session, user)
    _expense(db_session, user, checking, "Gym", "10.00",
             frequency=models.RecurringFrequency.weekly, day_of_month=0, card_id=card.id)
    for day in (2, 9, 16):
        _post(db_session, user, card, day, "10.00")

    snap = _snapshot(db_session, user, checking, as_of=AS_OF)

    assert snap.leftover == BASE_LEFTOVER - D("50.00")
    assert snap.left_to_spend == snap.leftover


def test_safety_margin_subtracts_the_weekly_card_bills_still_to_come(db_session, monkeypatch):
    """Safety Margin = low - (card bills this month not yet charged). Two
    Mondays (23rd, 30th) are still to come."""
    _freeze_today(monkeypatch, AS_OF)
    plain, plain_checking = _seed(db_session, "wkplain", remaining=D("0"))
    user, checking = _seed(db_session, "wkmargin", remaining=D("0"))
    card = _card(db_session, user)
    _expense(db_session, user, checking, "Gym", "10.00",
             frequency=models.RecurringFrequency.weekly, day_of_month=0, card_id=card.id)

    baseline = _snapshot(db_session, plain, plain_checking, as_of=AS_OF)
    snap = _snapshot(db_session, user, checking, as_of=AS_OF)

    assert snap.safety_margin == baseline.safety_margin - D("20.00")


def test_weekly_and_biweekly_card_bills_are_on_every_months_list():
    """The forecast's Safety Margin walk leaves exactly these out of the next
    card payoff, so it must agree with the snapshot's card-bill total."""
    for freq in (models.RecurringFrequency.weekly, models.RecurringFrequency.biweekly):
        item = models.RecurringItem(frequency=freq)
        assert is_card_bill_in_month(item, date(2026, 11, 1))


def test_an_entered_statement_amount_on_a_card_bill_nets_out(db_session, monkeypatch):
    _freeze_today(monkeypatch, AS_OF)
    user, checking = _seed(db_session, "ovcard", remaining=D("0"))
    card = _card(db_session, user)
    item = _expense(db_session, user, checking, "Streaming", "20.00", day_of_month=12, card_id=card.id)
    db_session.add(models.BillAmountOverride(
        user_id=user.id, recurring_item_id=item.id, due_date=date(2026, 11, 12),
        actual_amount=D("23.50"),
    ))
    _post(db_session, user, card, 12, "23.50", merchant="STREAMING")

    snap = _snapshot(db_session, user, checking, as_of=AS_OF)

    assert snap.leftover == BASE_LEFTOVER - D("23.50")
    assert snap.left_to_spend == snap.leftover


# -- 3. Social Security boost with a mid-month pay stub --------------------

def _stub(db, user, as_of: date, under: Decimal):
    """A pay stub dated `as_of` whose YTD gross sits `under` below the base."""
    user.ss_bonus_ytd = None
    user.ss_withheld_ytd = ((WAGE_BASE - under) * D("0.062")).quantize(D("0.01"))
    user.ss_withheld_ytd_as_of = as_of
    db.commit()


def _items(db, user):
    return db.query(models.RecurringItem).filter_by(user_id=user.id).all()


def test_a_stub_after_a_paycheck_in_the_month_does_not_redraw_it(db_session, monkeypatch):
    """Stub dated Nov 20 already holds the Nov 13 check. The Nov 30 check is
    the one that crosses, and gets only the part above the base -- exactly
    as the forecast books it."""
    today = _freeze_today(monkeypatch, AS_OF)
    user, checking = _seed(db_session, "stubmid", remaining=D("0"))
    under = D("1000.00")
    _stub(db_session, user, date(2026, 11, 20), under)
    left = WAGE_BASE - (user.ss_withheld_ytd / D("0.062")).quantize(D("0.01"))
    partial = ((GROSS - left) * D("0.062")).quantize(D("0.01"))

    boosts = ss_paycheck_boosts(db_session, user, _items(db_session, user), 2026, 11, today=today)
    forecast = _forecast_paychecks(db_session, user, checking, today, date(2026, 11, 30))

    assert list(boosts.values()) == [partial]
    assert [d for (_id, d) in boosts] == [date(2026, 11, 30)]
    assert forecast == [(date(2026, 11, 30), NET + partial)]


def test_a_month_before_the_stub_gets_no_boost(db_session, monkeypatch):
    """Stub dated Nov 30, base not met yet: browsing back to October or
    November must not boost anything, and December's first check crosses."""
    today = _freeze_today(monkeypatch, date(2026, 11, 30))
    user, checking = _seed(db_session, "stubbefore", remaining=D("0"))
    _stub(db_session, user, date(2026, 11, 30), D("1000.00"))
    left = WAGE_BASE - (user.ss_withheld_ytd / D("0.062")).quantize(D("0.01"))
    partial = ((GROSS - left) * D("0.062")).quantize(D("0.01"))
    items = _items(db_session, user)

    assert ss_paycheck_boosts(db_session, user, items, 2026, 10, today=today) == {}
    assert ss_paycheck_boosts(db_session, user, items, 2026, 11, today=today) == {}
    dec = ss_paycheck_boosts(db_session, user, items, 2026, 12, today=today)
    mid_month = next(i for i in items if i.day_of_month == 15)
    assert dec[(mid_month.id, date(2026, 12, 15))] == partial


# A stub only says where the base stood on its own date. Moving the walk
# start past it is right only while the stub shows the base NOT yet met, and
# only for its own year (found re-reviewing c16b15d, 2026-11).

def test_a_stub_above_the_base_keeps_the_months_earlier_boosts(db_session, monkeypatch):
    """Stub dated Nov 20 shows the base already passed: the Nov 13 check
    (paid for the 15th) really was boosted, so it keeps its boost alongside
    Nov 30, and October keeps both of its boosts too."""
    today = _freeze_today(monkeypatch, AS_OF)
    user, checking = _seed(db_session, "stubover", remaining=D("0"))
    _stub(db_session, user, date(2026, 11, 20), D("-500.00"))
    items = _items(db_session, user)
    mid, last = (next(i for i in items if i.day_of_month == d) for d in (15, 0))

    nov = ss_paycheck_boosts(db_session, user, items, 2026, 11, today=today)
    octo = ss_paycheck_boosts(db_session, user, items, 2026, 10, today=today)
    forecast = _forecast_paychecks(db_session, user, checking, today, date(2026, 11, 30))

    assert nov == {(mid.id, date(2026, 11, 15)): BOOST, (last.id, date(2026, 11, 30)): BOOST}
    assert octo == {(mid.id, date(2026, 10, 15)): BOOST, (last.id, date(2026, 10, 31)): BOOST}
    assert forecast == [(date(2026, 11, 30), NET + BOOST)]


def test_a_next_year_stub_leaves_december_boosts_intact(db_session, monkeypatch):
    """A January 2027 stub says nothing about 2026: December still counts
    the year's received paychecks against the 2026 base, as it did before
    the stub was entered. January itself still reads the stub."""
    today = _freeze_today(monkeypatch, date(2027, 1, 20))
    user, checking = _seed(db_session, "stubnext", remaining=D("0"))
    items = _items(db_session, user)
    mid, last = (next(i for i in items if i.day_of_month == d) for d in (15, 0))
    # Two paychecks received in 2026 already used up the (small) test base.
    for day, item in ((15, mid), (30, last)):
        db_session.add(models.Transaction(
            user_id=user.id, account_id=checking.id, date=date(2026, 10, day), amount=NET,
            description="Paycheck", is_actual=True, recurring_item_id=item.id,
        ))
    _stub(db_session, user, date(2027, 1, 15), D("10000.00"))

    dec = ss_paycheck_boosts(db_session, user, items, 2026, 12, today=today)
    jan = ss_paycheck_boosts(db_session, user, items, 2027, 1, today=today)

    assert dec == {(mid.id, date(2026, 12, 15)): BOOST, (last.id, date(2026, 12, 31)): BOOST}
    assert jan == {}
