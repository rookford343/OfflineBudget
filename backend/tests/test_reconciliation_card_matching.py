"""Reconciliation matches card payments with the shared word-bounded
card_matching heuristic, so an everyday PURCHASE debit is never mistaken for
the payoff of a card whose name happens to start with "Chase"."""
from datetime import date
from decimal import Decimal
from backend import models
from backend.auth import hash_password
from backend.services.reconciliation_helper import compute_reconciliation


def _seed(db, *, with_recurring: bool):
    user = models.User(username="u", hashed_password=hash_password("pw-123456"), display_name="U")
    db.add(user)
    db.flush()
    acct = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking,
                          current_balance=Decimal("0"))
    card = models.CreditCard(user_id=user.id, name="Chase Sapphire", credit_limit=Decimal("1000"),
                             statement_day=1, due_day=25)
    db.add_all([acct, card])
    db.flush()
    if with_recurring:
        db.add(models.RecurringItem(user_id=user.id, account_id=acct.id, card_id=card.id,
                                    name="Card payment", amount=Decimal("100"),
                                    type=models.RecurringType.credit_card_payment,
                                    day_of_month=25, start_date=date(2026, 1, 1)))
    for desc, amt in (("POS PURCHASE GROCERY #1234", "-40"), ("CHASE CREDIT CRD AUTOPAY", "-100")):
        db.add(models.Transaction(user_id=user.id, account_id=acct.id, date=date(2026, 3, 10),
                                  amount=Decimal(amt), description=desc, is_actual=True))
    db.commit()
    return user, acct


def _matched_and_unmatched(db, user, acct):
    r = compute_reconciliation(db, user.id, acct.id, 2026, 3)
    return ({m.description for m in r.matched},
            {u.description for u in r.unmatched_transactions})


def test_purchase_debit_is_not_matched_to_a_chase_recurring_payment(db_session):
    user, acct = _seed(db_session, with_recurring=True)
    matched, unmatched = _matched_and_unmatched(db_session, user, acct)
    assert matched == {"CHASE CREDIT CRD AUTOPAY"}
    assert "POS PURCHASE GROCERY #1234" in unmatched


def test_card_autopay_without_a_recurring_item_still_groups_by_card(db_session):
    user, acct = _seed(db_session, with_recurring=False)
    matched, unmatched = _matched_and_unmatched(db_session, user, acct)
    assert "CHASE CREDIT CRD AUTOPAY" not in unmatched
    assert "POS PURCHASE GROCERY #1234" in unmatched
