"""Pending card-payment debits on checking count against the forecast today.

Plaid gives the app checking's POSTED balance. A card autopay can sit pending
at the bank for a day or more while the card's own feed already shows the
statement paid, so nothing plans that payment any more and the forecast
overstated checking by the payment until it posted. Plaid sync now keeps a
snapshot of checking's pending list (AccountPendingTransaction); the forecast
subtracts the card-matching debits in it from today's balance, after today's
balance anchor so the anchor (the posted figure) can't erase them.

All figures are invented; the repo is public."""
from datetime import date, datetime, timedelta
from decimal import Decimal

from backend import models
from backend.services.forecast_engine import build_forecast

AUTOPAY = "CHASE CREDIT CRD AUTOPAY 1234"


def _user(db, username="pendingdebits"):
    user = models.User(username=username, hashed_password="x", display_name="the user")
    db.add(user)
    db.flush()
    return user


def _checking(db, user, balance="1000.00"):
    account = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking,
                             current_balance=Decimal(balance))
    db.add(account)
    db.flush()
    return account


def _card(db, user, **kw):
    defaults = dict(name="Chase Sapphire", credit_limit=Decimal("5000.00"), statement_day=28, due_day=25,
                    is_active=True, balance_due=Decimal("0"), current_balance=Decimal("0"))
    defaults.update(kw)
    card = models.CreditCard(user_id=user.id, **defaults)
    db.add(card)
    db.flush()
    return card


def _pending(db, user, account, amount, description=AUTOPAY, ext="plaid:p1", when=None):
    db.add(models.AccountPendingTransaction(
        user_id=user.id, account_id=account.id, external_id=ext, date=when or date.today(),
        amount=Decimal(amount), description=description, synced_at=datetime(2026, 1, 1),
    ))
    db.flush()


def _anchor(db, user, account, balance, when=None):
    db.add(models.ForecastDayCheckpoint(user_id=user.id, account_id=account.id, date=when or date.today(),
                                        actual_balance=Decimal(balance), note="auto"))
    db.flush()


def _today(db, user, account, start=None, end=None):
    today = date.today()
    entries = build_forecast(db, user.id, account.id, start or today, end or today)
    return next(e for e in entries if e.date == today), entries


def test_card_matching_pending_debit_lowers_todays_checking(db_session):
    user = _user(db_session)
    account = _checking(db_session, user)
    _card(db_session, user)
    _pending(db_session, user, account, "-300.00")
    db_session.commit()

    entry, _ = _today(db_session, user, account)
    assert entry.projected_balance == Decimal("700.00")
    lines = [(t.name, t.amount) for t in entry.transactions]
    assert (f"Pending: {AUTOPAY}", Decimal("-300.00")) in lines


def test_non_card_pending_debit_is_ignored(db_session):
    user = _user(db_session)
    account = _checking(db_session, user)
    _card(db_session, user)
    _pending(db_session, user, account, "-40.00", description="GROCERY MART 55")
    db_session.commit()

    entry, _ = _today(db_session, user, account)
    assert entry.projected_balance == Decimal("1000.00")
    assert entry.transactions == []


def test_pending_credit_is_ignored(db_session):
    user = _user(db_session)
    account = _checking(db_session, user)
    _card(db_session, user)
    _pending(db_session, user, account, "50.00", description="CHASE CREDIT CRD REFUND")
    db_session.commit()

    entry, _ = _today(db_session, user, account)
    assert entry.projected_balance == Decimal("1000.00")


def test_pending_debit_on_a_savings_account_is_ignored(db_session):
    user = _user(db_session)
    savings = models.Account(user_id=user.id, name="Savings", type=models.AccountType.savings,
                             current_balance=Decimal("1000.00"))
    db_session.add(savings)
    db_session.flush()
    _card(db_session, user)
    _pending(db_session, user, savings, "-300.00")
    db_session.commit()

    entry, _ = _today(db_session, user, savings)
    assert entry.projected_balance == Decimal("1000.00")


def test_the_cards_payoff_is_not_also_injected(db_session):
    """The card's feed hasn't marked the statement paid yet, so balance_due
    still stands with a due date ahead. The pending debit IS that payment;
    planning it again on the due date would take it out of checking twice."""
    user = _user(db_session)
    account = _checking(db_session, user)
    today = date.today()
    _card(db_session, user, balance_due=Decimal("300.00"), current_balance=Decimal("300.00"),
          next_payment_date=today + timedelta(days=3))
    _pending(db_session, user, account, "-300.00")
    db_session.commit()

    entry, entries = _today(db_session, user, account, end=today + timedelta(days=10))
    assert entry.projected_balance == Decimal("700.00")
    payoffs = [(e.date, t.amount) for e in entries for t in e.transactions if t.name.startswith("CC ")]
    assert payoffs == []
    assert entries[-1].projected_balance == Decimal("700.00")


def test_a_partial_pending_payment_leaves_the_rest_of_the_payoff(db_session):
    user = _user(db_session)
    account = _checking(db_session, user)
    today = date.today()
    _card(db_session, user, balance_due=Decimal("300.00"), current_balance=Decimal("300.00"),
          next_payment_date=today + timedelta(days=3))
    _pending(db_session, user, account, "-100.00")
    db_session.commit()

    _, entries = _today(db_session, user, account, end=today + timedelta(days=10))
    payoffs = [(e.date, t.amount) for e in entries for t in e.transactions if t.name == "CC Payment: Chase Sapphire"]
    assert payoffs == [(today + timedelta(days=3), Decimal("-200.00"))]
    assert entries[-1].projected_balance == Decimal("700.00")


def test_marker_and_pending_debit_count_once_marker_larger(db_session):
    user = _user(db_session)
    account = _checking(db_session, user)
    _card(db_session, user, payment_sent_pending_sync=True, payment_sent_amount=Decimal("300.00"))
    _pending(db_session, user, account, "-250.00")
    db_session.commit()

    entry, _ = _today(db_session, user, account)
    assert entry.projected_balance == Decimal("700.00")


def test_marker_and_pending_debit_count_once_pending_larger(db_session):
    user = _user(db_session)
    account = _checking(db_session, user)
    _card(db_session, user, payment_sent_pending_sync=True, payment_sent_amount=Decimal("200.00"))
    _pending(db_session, user, account, "-300.00")
    db_session.commit()

    entry, _ = _today(db_session, user, account)
    assert entry.projected_balance == Decimal("700.00")


def test_todays_anchor_does_not_erase_the_pending_debit(db_session):
    """Sync anchors today to the POSTED balance, which by definition doesn't
    include the pending debit. The walk applies a day's anchor after that
    day's lines, so the subtraction has to land after the anchor."""
    user = _user(db_session)
    account = _checking(db_session, user)
    _card(db_session, user)
    _pending(db_session, user, account, "-300.00")
    _anchor(db_session, user, account, "1000.00")
    db_session.commit()

    today = date.today()
    entry, entries = _today(db_session, user, account)
    assert entry.projected_balance == Decimal("700.00")
    # A window that opens in the past walks through the anchor too.
    entry, _ = _today(db_session, user, account, start=today - timedelta(days=5), end=today + timedelta(days=2))
    assert entry.projected_balance == Decimal("700.00")
    # And a window that opens in the future carries it in through its bridge.
    later = build_forecast(db_session, user.id, account.id, today + timedelta(days=1), today + timedelta(days=1))
    assert later[0].projected_balance == Decimal("700.00")


def test_todays_anchor_does_not_erase_the_payment_sent_marker(db_session):
    """Same flaw, same fix, for the hand-set payment-sent marker: it used to
    be subtracted from the opening seed, so today's anchor overwrote it."""
    user = _user(db_session)
    account = _checking(db_session, user)
    _card(db_session, user, payment_sent_pending_sync=True, payment_sent_amount=Decimal("300.00"))
    _anchor(db_session, user, account, "1000.00")
    db_session.commit()

    entry, _ = _today(db_session, user, account)
    assert entry.projected_balance == Decimal("700.00")


def test_no_double_count_once_the_debit_posts(db_session):
    """After it posts, the snapshot no longer lists it and the posted balance
    already includes it: today is just the posted balance."""
    user = _user(db_session)
    account = _checking(db_session, user, balance="700.00")
    _card(db_session, user)
    db_session.add(models.Transaction(
        user_id=user.id, account_id=account.id, date=date.today(), amount=Decimal("-300.00"),
        description=AUTOPAY, is_actual=True,
    ))
    _anchor(db_session, user, account, "700.00")
    db_session.commit()

    entry, _ = _today(db_session, user, account)
    assert entry.projected_balance == Decimal("700.00")
    assert not [t for t in entry.transactions if t.name.startswith("Pending:")]


def test_pending_line_does_not_block_todays_anchor(db_session):
    """The pending line is bank-reported, not a projection, so it must not
    make has_unsettled_projection skip today's anchor."""
    from backend.services.forecast_engine import has_unsettled_projection

    user = _user(db_session)
    account = _checking(db_session, user)
    _card(db_session, user)
    _pending(db_session, user, account, "-300.00")
    db_session.commit()

    assert has_unsettled_projection(db_session, user.id, account.id, date.today()) is False


def test_safety_margin_floor_sees_the_lower_balance(db_session):
    """budget_snapshot's floor reads the same walk, so it needs nothing of
    its own: once the payoff dip ends at the next income, the lower balance
    is what the floor sees."""
    from backend.services.budget_snapshot import _lookahead_minimum

    user = _user(db_session)
    account = _checking(db_session, user)
    _card(db_session, user)
    today = date.today()
    pay = today + timedelta(days=10)
    db_session.add(models.RecurringItem(
        user_id=user.id, account_id=account.id, name="Paycheck", type=models.RecurringType.income,
        amount=Decimal("100.00"), frequency=models.RecurringFrequency.monthly, day_of_month=pay.day,
        start_date=date(today.year - 1, 1, 1), is_active=True, include_in_forecast=True,
    ))
    db_session.commit()
    before, _ = _lookahead_minimum(db_session, user.id, account.id, today)

    _pending(db_session, user, account, "-300.00")
    db_session.commit()
    after, low_day = _lookahead_minimum(db_session, user.id, account.id, today)
    # Before: the floor is the flat balance ahead of payday. After: today
    # through payday is the payoff dip (barred from being the floor, like a
    # posted payoff), so the floor is payday itself -- 100 higher for the
    # paycheck, 300 lower for the pending payment.
    assert after == before + Decimal("100.00") - Decimal("300.00")
    assert low_day is not None and low_day > today
