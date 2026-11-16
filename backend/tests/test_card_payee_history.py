"""Card-side twin of test_recurring_suggestion.py's
test_payee_history_links_a_bill_whose_name_shares_no_words.

Before this fix, import_service._payee_history only queried checking
Transaction rows (models.Transaction.recurring_item_id.isnot(None)), so a
card-linked floating item could never accumulate match evidence from its
own payee history -- history_hits was always 0 for card items, the same
blind-spot shape test_recurring_suggestion.py already covers for the
checking side. _payee_history now also folds in CreditCardTransaction rows
with recurring_item_id set."""
from datetime import date
from decimal import Decimal
from backend import models
from backend.services.csv_parser import ParsedRow
from backend.services.import_service import build_preview

D = Decimal


def _user_with_card_item(db):
    user = models.User(username="cardmatcher", hashed_password="x", display_name="C")
    db.add(user)
    db.flush()
    acct = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking)
    card = models.CreditCard(user_id=user.id, name="Visa", credit_limit=D("1000"), statement_day=1, due_day=20)
    db.add_all([acct, card])
    db.flush()
    item = models.RecurringItem(
        user_id=user.id, account_id=acct.id, card_id=card.id, name="Test Haircut",
        amount=D("45.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=15,
        start_date=date(2026, 1, 1), is_floating=True,
    )
    db.add(item)
    db.commit()
    return user, card, item


def _link_card_history(db, user, card, item, merchant, on):
    db.add(models.CreditCardTransaction(
        card_id=card.id, user_id=user.id, recurring_item_id=item.id,
        date=on, amount=item.amount, merchant=merchant,
    ))
    db.commit()


def test_card_payee_history_links_a_bill_whose_name_shares_no_words(db_session):
    """SNIPSNAP STUDIO shares no word with "Test Haircut", but a past
    CreditCardTransaction already linked to it is evidence enough -- same
    as the checking-side Progressive/Chevy Insurance case."""
    user, card, item = _user_with_card_item(db_session)
    _link_card_history(db_session, user, card, item, "SNIPSNAP STUDIO #4", date(2026, 10, 12))

    row = ParsedRow(date=date(2026, 11, 10), description="SNIPSNAP STUDIO #4", amount=D("-45.00"), external_id="x")
    out = build_preview(db_session, user, [row], card_id=card.id)

    assert out[0].suggested_recurring_item_name == "Test Haircut"


def test_card_without_history_or_name_evidence_is_not_suggested(db_session):
    """Regression guard: without the linked history row above, the same
    no-shared-word description must NOT match -- proves the test above is
    exercising the history path, not some other evidence."""
    user, card, _item = _user_with_card_item(db_session)

    row = ParsedRow(date=date(2026, 11, 10), description="SNIPSNAP STUDIO #4", amount=D("-45.00"), external_id="x")
    out = build_preview(db_session, user, [row], card_id=card.id)

    assert out[0].suggested_recurring_item_name is None
