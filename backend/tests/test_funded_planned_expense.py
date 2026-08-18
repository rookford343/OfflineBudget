from datetime import date, timedelta
from decimal import Decimal
from backend import models
from backend.services.forecast_engine import build_forecast


def _seed(db):
    user = models.User(username="f", hashed_password="x", display_name="F")
    db.add(user); db.flush()
    chk = models.Account(user_id=user.id, name="Chk", type=models.AccountType.checking,
                         current_balance=Decimal("10000.00"))
    sav = models.Account(user_id=user.id, name="Sav", type=models.AccountType.savings,
                         current_balance=Decimal("30000.00"))
    db.add_all([chk, sav]); db.commit()
    return user, chk, sav


def _min_balance(db, user, acct, end):
    return min(r.projected_balance for r in build_forecast(db, user.id, acct.id, date.today(), end))


def _on(db, user, acct, target, end):
    for r in build_forecast(db, user.id, acct.id, date.today(), end):
        if r.date == target:
            return r.projected_balance
    return None


def test_funding_leg_lands_before_the_purchase_and_cancels_the_dip(db_session):
    """A $21,000 purchase from a $10,000 account is only sane if the money it
    draws on is shown arriving. Without the link, checking dives."""
    user, chk, sav = _seed(db_session)
    buy = date.today() + timedelta(days=30)
    db_session.add(models.PlannedExpense(
        user_id=user.id, account_id=chk.id, name="Rivian R2",
        amount=Decimal("21000.00"), expected_date=buy,
        direction=models.PlannedDirection.outflow,
        funding_account_id=sav.id, funding_lead_days=1))
    db_session.commit()

    end = buy + timedelta(days=5)
    assert _min_balance(db_session, user, chk, end) >= Decimal("0")
    # Money in the day before, out on the day: net zero across the pair.
    assert _on(db_session, user, chk, buy, end) == Decimal("10000.00")
    assert _on(db_session, user, chk, buy - timedelta(days=1), end) == Decimal("31000.00")


def test_the_funding_account_shows_the_withdrawal(db_session):
    """Forecasting savings has to show the money leaving, or the purchase is
    free from that side."""
    user, chk, sav = _seed(db_session)
    buy = date.today() + timedelta(days=30)
    db_session.add(models.PlannedExpense(
        user_id=user.id, account_id=chk.id, name="Rivian R2",
        amount=Decimal("21000.00"), expected_date=buy,
        direction=models.PlannedDirection.outflow,
        funding_account_id=sav.id, funding_lead_days=1))
    db_session.commit()

    end = buy + timedelta(days=5)
    assert _on(db_session, user, sav, buy, end) == Decimal("9000.00")


def test_moving_the_purchase_moves_its_funding(db_session):
    """The reason funding lives on the expense: Dan moved R2 from 09-15 to
    10-06 and its standalone $22,000 transfer stayed put, leaving three weeks
    of forecast showing money that was already spoken for."""
    user, chk, sav = _seed(db_session)
    first = date.today() + timedelta(days=20)
    pe = models.PlannedExpense(
        user_id=user.id, account_id=chk.id, name="Rivian R2",
        amount=Decimal("21000.00"), expected_date=first,
        direction=models.PlannedDirection.outflow,
        funding_account_id=sav.id, funding_lead_days=1)
    db_session.add(pe); db_session.commit()

    moved = first + timedelta(days=21)
    pe.expected_date = moved
    db_session.commit()

    end = moved + timedelta(days=5)
    # Nothing extra sits in checking during the window it used to cover.
    assert _on(db_session, user, chk, first, end) == Decimal("10000.00")
    assert _on(db_session, user, chk, moved - timedelta(days=1), end) == Decimal("31000.00")


def test_funding_amount_can_differ_from_the_purchase(db_session):
    """Transfers are usually round numbers: $22,000 moved for a $21,000 car."""
    user, chk, sav = _seed(db_session)
    buy = date.today() + timedelta(days=30)
    db_session.add(models.PlannedExpense(
        user_id=user.id, account_id=chk.id, name="Rivian R2",
        amount=Decimal("21000.00"), expected_date=buy,
        direction=models.PlannedDirection.outflow,
        funding_account_id=sav.id, funding_amount=Decimal("22000.00"),
        funding_lead_days=1))
    db_session.commit()

    end = buy + timedelta(days=5)
    assert _on(db_session, user, chk, buy, end) == Decimal("11000.00")   # 10k + 22k - 21k
    assert _on(db_session, user, sav, buy, end) == Decimal("8000.00")


def test_unfunded_purchase_is_unchanged(db_session):
    """The default path must not move: most one-offs come out of cash flow."""
    user, chk, sav = _seed(db_session)
    buy = date.today() + timedelta(days=30)
    db_session.add(models.PlannedExpense(
        user_id=user.id, account_id=chk.id, name="Small thing",
        amount=Decimal("500.00"), expected_date=buy,
        direction=models.PlannedDirection.outflow))
    db_session.commit()

    end = buy + timedelta(days=5)
    assert _on(db_session, user, chk, buy, end) == Decimal("9500.00")
    assert _on(db_session, user, sav, buy, end) == Decimal("30000.00")


def test_card_bills_are_not_drawn_from_a_savings_forecast(db_session):
    """CreditCard has no payment-account link, so every payoff was injected
    into whichever account was forecast -- Dan's savings ended at -$18,298.05
    after absorbing a Chase payoff and two monthly estimates."""
    user, chk, sav = _seed(db_session)
    db_session.add(models.CreditCard(
        user_id=user.id, name="Chase", credit_limit=Decimal("29000.00"),
        statement_day=28, due_day=25, current_balance=Decimal("9000.00"),
        balance_due=Decimal("9000.00"), monthly_spend_estimate=Decimal("5500.00"),
        next_payment_date=date.today() + timedelta(days=7), is_active=True))
    db_session.commit()

    end = date.today() + timedelta(days=90)
    assert _on(db_session, user, sav, date.today() + timedelta(days=89), end) == Decimal("30000.00")
    # The checking side must still see it, or the guard has gone too far.
    assert _min_balance(db_session, user, chk, end) < Decimal("10000.00")
