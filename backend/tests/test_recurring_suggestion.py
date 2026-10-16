"""Which recurring bill an imported transaction is linked to.

A link tells the forecast the bill is paid, so a wrong link silently drops a
real bill from the projection. Found 2026-10-16: the matcher accepted a
candidate sharing no words with the transaction (its best score started at
-1, so 0 won), and "pay"/"autopay" -> "payment" made the generic word
"payment" count as a match. A Duke payment linked to a doctor's bill, an
Apple Card payment to House Cleaning, and a Zelle transfer to Citizens
Energy. Meanwhile the real Duke bill never matched: its payment ran 5 days
after the due date and at the confirmed bill amount, not the planned one.
"""
from datetime import date
from decimal import Decimal

import pytest

from backend import models
from backend.services.csv_parser import ParsedRow
from backend.services.import_service import build_preview


def _user_with_bills(db):
    user = models.User(username="matcher", hashed_password="x", display_name="M")
    db.add(user)
    db.flush()
    acct = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking,
                          current_balance=Decimal("1000"))
    db.add(acct)
    db.flush()
    items = {}
    for name, amount, day, typ in [
        ("Duke Electric", "180.00", 8, models.RecurringType.expense),
        ("Pediatrician (annual)", "300.00", 15, models.RecurringType.expense),
        ("House Cleaning", "200.00", 0, models.RecurringType.expense),
        ("Citizens Energy", "200.00", 17, models.RecurringType.expense),
        ("Honda CR-V Payment", "672.00", 7, models.RecurringType.expense),
        ("Paycheck 2", "5000.00", 0, models.RecurringType.income),
    ]:
        item = models.RecurringItem(user_id=user.id, account_id=acct.id, name=name, amount=Decimal(amount),
                                    type=typ, frequency=models.RecurringFrequency.monthly,
                                    day_of_month=day, start_date=date(2026, 1, 1))
        db.add(item)
        db.flush()
        items[name] = item
    db.add(models.BillAmountOverride(user_id=user.id, recurring_item_id=items["Duke Electric"].id,
                                     due_date=date(2026, 10, 8), actual_amount=Decimal("250.00")))
    db.commit()
    return user, items


def _suggested(db, user, description, amount, on):
    row = ParsedRow(date=on, description=description, amount=Decimal(amount), external_id="x")
    return build_preview(db, user, [row])[0].suggested_recurring_item_name


@pytest.mark.parametrize("description,amount,on", [
    pytest.param("Zelle payment to JOHN SMITH JPM99", "-200.00", date(2026, 9, 14), id="zelle_not_citizens_energy"),
    pytest.param("APPLECARD GSBANK PAYMENT 10000000", "-190.00", date(2026, 9, 28), id="apple_payment_not_house_cleaning"),
    pytest.param("Zelle payment to Jane Doe", "-672.00", date(2026, 10, 7), id="generic_payment_word_not_honda"),
])
def test_no_link_without_name_evidence(db_session, description, amount, on):
    user, _ = _user_with_bills(db_session)
    assert _suggested(db_session, user, description, amount, on) is None


def test_duke_payment_links_to_duke_at_its_confirmed_amount_days_after_due(db_session):
    user, _ = _user_with_bills(db_session)
    assert _suggested(db_session, user, "DUKEENERGY BILL PAY XXXXXXXX1111", "-250.00", date(2026, 10, 13)) \
        == "Duke Electric"


def test_payroll_still_links_to_the_paycheck(db_session):
    user, _ = _user_with_bills(db_session)
    assert _suggested(db_session, user, "ACME CORP PAYROLL PPD ID: 1234", "5400.00", date(2026, 9, 30)) \
        == "Paycheck 2"


def _link_history(db, user, item, description, on):
    acct = db.query(models.Account).filter_by(user_id=user.id).first()
    db.add(models.Transaction(user_id=user.id, account_id=acct.id, date=on, amount=-item.amount,
                              description=description, is_actual=True, recurring_item_id=item.id))
    db.commit()


def test_payee_history_links_a_bill_whose_name_shares_no_words(db_session):
    """PROG SO EASTERN pays 'Chevy Insurance': no shared word, but every past
    Progressive payment is linked to that bill, which is evidence enough."""
    user, items = _user_with_bills(db_session)
    chevy = models.RecurringItem(user_id=user.id, account_id=items["Duke Electric"].account_id,
                                 name="Chevy Insurance", amount=Decimal("150.00"),
                                 type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
                                 day_of_month=2, start_date=date(2026, 1, 1))
    db_session.add(chevy)
    db_session.commit()
    _link_history(db_session, user, chevy, "PROG SO EASTERN INS PREM XXXXX0000", date(2026, 9, 1))
    assert _suggested(db_session, user, "PROG SO EASTERN INS PREM XXXXX0000 WEB", "-150.00", date(2026, 10, 1)) \
        == "Chevy Insurance"


def test_a_bill_charged_to_a_card_never_matches_a_checking_payment(db_session):
    user, items = _user_with_bills(db_session)
    card = models.CreditCard(user_id=user.id, name="Visa", credit_limit=Decimal("1000"), statement_day=1, due_day=20)
    db_session.add(card)
    db_session.flush()
    items["Citizens Energy"].card_id = card.id
    db_session.commit()
    _link_history(db_session, user, items["Citizens Energy"], "CITIZENS ENERGY PAYMENT", date(2026, 9, 17))
    assert _suggested(db_session, user, "CITIZENS ENERGY PAYMENT", "-200.00", date(2026, 10, 17)) is None


def test_an_annual_bill_only_matches_in_its_month(db_session):
    user, items = _user_with_bills(db_session)
    items["Pediatrician (annual)"].frequency = models.RecurringFrequency.yearly
    items["Pediatrician (annual)"].month_of_year = 7
    db_session.commit()
    assert _suggested(db_session, user, "PEDIATRICIAN OFFICE", "-300.00", date(2026, 10, 15)) is None
    assert _suggested(db_session, user, "PEDIATRICIAN OFFICE", "-300.00", date(2026, 7, 15)) == "Pediatrician (annual)"
