from datetime import date
from decimal import Decimal
from backend import models
from backend.services.summary_generator import generate_daily_summary


def _user_with_checking(db, username="carduser"):
    """A checking account is needed for the snapshot to compute at all --
    generate_daily_summary only builds one when a checking account exists,
    and the card figures are read off that snapshot."""
    user = models.User(username=username, hashed_password="x", display_name="Card")
    db.add(user)
    db.flush()
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("1000.00"),
    )
    db.add(account)
    db.flush()
    return user, account


def test_card_row_breaks_out_balance_upcoming_payoff_and_cycle_spend(db_session):
    """Dan's real Chase figures: a $10,618.22 balance is two different things
    stacked -- $6,945.00 of already-statemented debt that gets paid on the
    due date, and $3,673.22 of new spend since that statement closed. The
    email showed only the blended total, which says nothing actionable."""
    user, account = _user_with_checking(db_session)
    db_session.add(models.CreditCard(
        user_id=user.id, name="Chase Sapphire", credit_limit=Decimal("29000.00"),
        statement_day=28, due_day=25,
        current_balance=Decimal("10618.22"), balance_due=Decimal("6945.00"),
        pending_charges=Decimal("0"),
    ))
    db_session.commit()

    html, text = generate_daily_summary(db_session, user)

    for body in (html, text):
        assert "$10,618.22" in body, "current balance"
        assert "$6,945.00" in body, "upcoming payoff (balance_due)"
        assert "$3,673.22" in body, "spend so far this cycle"


def test_cycle_spend_includes_pending_charges(db_session):
    """pending_charges is spend that has happened but not posted -- it belongs
    in "spent this cycle", and budget_snapshot's new_spending_total already
    counts it that way. The email must not disagree with Left to Spend."""
    user, account = _user_with_checking(db_session)
    db_session.add(models.CreditCard(
        user_id=user.id, name="Visa", credit_limit=Decimal("10000.00"),
        statement_day=28, due_day=25,
        current_balance=Decimal("1000.00"), balance_due=Decimal("400.00"),
        pending_charges=Decimal("50.00"),
    ))
    db_session.commit()

    html, _ = generate_daily_summary(db_session, user)

    # 1000.00 - 400.00 + 50.00
    assert "$650.00" in html


def test_cycle_spend_going_negative_shows_zero_and_flags_stale_statement(db_session):
    """Dan's real Apple Card: $59.50 balance against a $180.32 balance_due
    whose next_payment_date still said May -- balance_due is manual-entry
    only, so it goes stale after a payment and drives the subtraction
    negative. A negative "spent this cycle" is really a staleness signal,
    so say that rather than rendering a number that reads like a bug."""
    user, account = _user_with_checking(db_session)
    db_session.add(models.CreditCard(
        user_id=user.id, name="Apple Card", credit_limit=Decimal("5000.00"),
        statement_day=31, due_day=25,
        current_balance=Decimal("59.50"), balance_due=Decimal("180.32"),
        pending_charges=Decimal("0"),
    ))
    db_session.commit()

    html, text = generate_daily_summary(db_session, user)

    for body in (html, text):
        assert "-$120.82" not in body and "−$120.82" not in body, "never render the negative"
        assert "stale" in body.lower(), "flag the stale statement figure"
