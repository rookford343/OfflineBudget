from datetime import date, timedelta
from decimal import Decimal
from backend import models
from backend.services.forecast_engine import suggest_transfer


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


def _risk(at_risk=True, d=None, amount="-500.00", threshold="0"):
    return {
        "at_risk": at_risk,
        "date": d or date(2026, 9, 15),
        "amount": Decimal(amount) if at_risk else None,
        "threshold": Decimal(threshold),
    }


def test_no_suggestion_when_not_at_risk(db_session):
    user = _make_user(db_session)
    checking, _ = _make_accounts(db_session, user)
    db_session.commit()

    result = suggest_transfer(db_session, user, checking.id, _risk(at_risk=False))

    assert result == {"amount": None, "date": None, "from_account_id": None, "already_planned": False}


def test_suggestion_rounds_up_to_default_increment(db_session):
    user = _make_user(db_session)
    checking, savings = _make_accounts(db_session, user, num_savings=1)
    db_session.commit()

    # shortfall = threshold(0) - amount(-500) = 500 -> rounds up to 1000 (default increment)
    result = suggest_transfer(db_session, user, checking.id, _risk(amount="-500.00", threshold="0"))

    assert result["amount"] == Decimal("1000.00")
    assert result["from_account_id"] == savings[0].id
    assert result["already_planned"] is False
    assert result["date"] == date(2026, 9, 15) - timedelta(days=3)


def test_suggestion_rounds_up_to_custom_increment(db_session):
    user = _make_user(db_session, transfer_increment=Decimal("500.00"))
    checking, _ = _make_accounts(db_session, user, num_savings=1)
    db_session.commit()

    # shortfall = 500 -> exactly one 500 increment, no rounding needed
    result = suggest_transfer(db_session, user, checking.id, _risk(amount="-500.00", threshold="0"))

    assert result["amount"] == Decimal("500.00")


def test_suggestion_leaves_from_account_unset_when_ambiguous(db_session):
    user = _make_user(db_session)
    checking, savings = _make_accounts(db_session, user, num_savings=2)
    db_session.commit()

    result = suggest_transfer(db_session, user, checking.id, _risk())

    assert result["from_account_id"] is None


def test_suggestion_leaves_from_account_unset_when_no_savings(db_session):
    user = _make_user(db_session)
    checking, _ = _make_accounts(db_session, user, num_savings=0)
    db_session.commit()

    result = suggest_transfer(db_session, user, checking.id, _risk())

    assert result["from_account_id"] is None


def test_already_planned_suppresses_a_new_suggestion(db_session):
    user = _make_user(db_session)
    checking, savings = _make_accounts(db_session, user, num_savings=1)
    db_session.flush()
    db_session.add(models.PlannedTransfer(
        user_id=user.id, from_account_id=savings[0].id, to_account_id=checking.id,
        amount=Decimal("1000.00"), target_date=date(2026, 9, 13),
        status=models.PlannedTransferStatus.pending,
    ))
    db_session.commit()

    result = suggest_transfer(db_session, user, checking.id, _risk(d=date(2026, 9, 15)))

    assert result["already_planned"] is True
    assert result["amount"] is None


def test_verified_transfer_does_not_suppress_a_new_suggestion(db_session):
    """A verified transfer means the real transaction already happened and
    is reflected in actuals -- a NEW risk near the same date needs its own
    new suggestion, not silent suppression by old, already-resolved history."""
    user = _make_user(db_session)
    checking, savings = _make_accounts(db_session, user, num_savings=1)
    db_session.flush()
    db_session.add(models.PlannedTransfer(
        user_id=user.id, from_account_id=savings[0].id, to_account_id=checking.id,
        amount=Decimal("1000.00"), target_date=date(2026, 9, 13),
        status=models.PlannedTransferStatus.verified,
    ))
    db_session.commit()

    result = suggest_transfer(db_session, user, checking.id, _risk(d=date(2026, 9, 15)))

    assert result["already_planned"] is False
