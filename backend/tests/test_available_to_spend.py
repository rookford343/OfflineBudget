import calendar
from datetime import date
from decimal import Decimal
from backend import models
from backend.routers.spending import available_to_spend


def _seed(db):
    user = models.User(username="a", hashed_password="x", display_name="A")
    db.add(user); db.flush()
    acct = models.Account(user_id=user.id, name="Chk", type=models.AccountType.checking)
    card = models.CreditCard(user_id=user.id, name="Visa", credit_limit=Decimal("5000"),
                             statement_day=28, due_day=15)
    db.add_all([acct, card]); db.flush()
    db.add(models.RecurringItem(
        user_id=user.id, account_id=acct.id, name="Rent", amount=Decimal("1000.00"),
        type=models.RecurringType.income if False else models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=1,
        start_date=date(2026, 1, 1), is_active=True))
    db.add(models.RecurringItem(
        user_id=user.id, account_id=acct.id, name="Pay", amount=Decimal("5000.00"),
        type=models.RecurringType.income, frequency=models.RecurringFrequency.monthly,
        day_of_month=1, start_date=date(2026, 1, 1), is_active=True))
    db.commit()
    return user, acct, card


def _mid_month():
    t = date.today()
    return t.replace(day=min(15, calendar.monthrange(t.year, t.month)[1]))


def test_a_posted_recurring_bill_is_not_deducted_twice(db_session):
    """It is already inside Committed Bills; counting the posted transaction
    too subtracts the same money from the same income twice."""
    user, acct, card = _seed(db_session)
    item = db_session.query(models.RecurringItem).filter_by(name="Rent").first()
    db_session.add(models.Transaction(
        user_id=user.id, account_id=acct.id, date=_mid_month(),
        amount=Decimal("-1000.00"), description="RENT ACH", is_actual=True,
        recurring_item_id=item.id))
    db_session.commit()

    r = available_to_spend(db=db_session, user=user)
    assert r.spent_this_month == Decimal("0")
    assert r.available == Decimal("4000.00")   # 5000 income - 1000 committed


def test_card_spending_counts_toward_the_month(db_session):
    """Card charges were excluded entirely, so for a card-first household the
    figure omitted the larger half and a single week could exceed the month."""
    user, acct, card = _seed(db_session)
    db_session.add(models.CreditCardTransaction(
        card_id=card.id, user_id=user.id, date=_mid_month(),
        amount=Decimal("250.00"), merchant="Some Shop"))
    db_session.commit()

    assert available_to_spend(db=db_session, user=user).spent_this_month == Decimal("250.00")


def test_a_card_payoff_is_not_spending(db_session):
    """It settles charges already counted individually."""
    user, acct, card = _seed(db_session)
    db_session.add(models.CreditCardTransaction(
        card_id=card.id, user_id=user.id, date=_mid_month(),
        amount=Decimal("900.00"), merchant="AUTOMATIC PAYMENT - THANK YOU"))
    db_session.commit()

    assert available_to_spend(db=db_session, user=user).spent_this_month == Decimal("0")


def test_card_linked_recurring_charges_are_not_double_counted(db_session):
    """A subscription billed to a card sits in Committed Bills as well."""
    user, acct, card = _seed(db_session)
    today = date.today()
    db_session.add(models.RecurringItem(
        user_id=user.id, account_id=acct.id, card_id=card.id, name="Streaming",
        amount=Decimal("20.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=1,
        start_date=date(2026, 1, 1), is_active=True))
    db_session.add(models.CreditCardTransaction(
        card_id=card.id, user_id=user.id, date=today.replace(day=1),
        amount=Decimal("20.00"), merchant="Streaming"))
    db_session.commit()

    # The charge is cancelled by the committed subscription that predicted it.
    assert available_to_spend(db=db_session, user=user).spent_this_month == Decimal("0")


def test_discretionary_checking_still_counts(db_session):
    """The fix must not suppress ordinary unplanned spending."""
    user, acct, card = _seed(db_session)
    db_session.add(models.Transaction(
        user_id=user.id, account_id=acct.id, date=_mid_month(),
        amount=Decimal("-63.00"), description="COFFEE", is_actual=True))
    db_session.commit()

    assert available_to_spend(db=db_session, user=user).spent_this_month == Decimal("63.00")
