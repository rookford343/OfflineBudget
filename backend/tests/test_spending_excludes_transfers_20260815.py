"""Spending must count money that actually left the household -- nothing else
(Dan, 2026-08-15: transfers counted as spending, and card payoff showing up
under Merchants where it double-counts every charge it settles).

Measured on Dan's real data before the fix: July "spending" was $29,462.90,
of which $13,522.69 was a Chase autopay ($11,312.54), an Apple Card payment
($210.15), and two $1,000 self-transfers. 46% of the number was noise, and
the card payoff outranked his mortgage as the top "merchant".

The logic already existed in spendable_pacer.py and powered the Dashboard
correctly. spending_helpers.py -- behind the Spending page AND the weekly
email -- had its own path without it, so the same drift as
forecast_engine._fires_on vs summary_generator._fires_soon. These tests pin
the behaviour on the shared predicate both now call.
"""
from datetime import date
from decimal import Decimal
from backend import models
from backend.services.spending_helpers import (
    merchant_totals, category_totals_for_range,
    is_real_checking_spend, looks_like_internal_transfer,
)


def _setup(db):
    user = models.User(username="dan", hashed_password="x", display_name="Dan")
    db.add(user)
    db.flush()
    account = models.Account(user_id=user.id, name="Main Checking",
                             type=models.AccountType.checking, current_balance=Decimal("5000"))
    card = models.CreditCard(user_id=user.id, name="Chase Sapphire", credit_limit=Decimal("29000"),
                             statement_day=28, due_day=25, is_active=True)
    db.add_all([account, card])
    db.flush()
    return user, account, card


def _txn(db, user, account, desc, amount, when=date(2026, 7, 15)):
    t = models.Transaction(user_id=user.id, account_id=account.id, date=when,
                           amount=Decimal(amount), description=desc, is_actual=True)
    db.add(t)
    return t


# --- The predicate itself ------------------------------------------------

def test_card_payoff_is_not_spend():
    card = models.CreditCard(name="Chase Sapphire", credit_limit=Decimal("1"),
                             statement_day=28, due_day=25)
    assert is_real_checking_spend("CHASE CREDIT CRD AUTOPAY  PPD ID: 4760039224", [card]) is False


def test_apple_card_payment_is_not_spend():
    """"Apple Card" pays out as the single token APPLECARD."""
    card = models.CreditCard(name="Apple Card", credit_limit=Decimal("1"),
                             statement_day=31, due_day=25)
    assert is_real_checking_spend("APPLECARD GSBANK PAYMENT 16069006", [card]) is False


def test_internal_transfer_is_not_spend():
    assert looks_like_internal_transfer("Online Transfer to CHK ...0054 transaction#: 3029") is True
    assert is_real_checking_spend("Online Transfer to CHK ...0054", []) is False


def test_ordinary_purchases_are_still_spend():
    """The exclusions must not eat real spending. A card named 'Chase
    Sapphire' must not swallow 'PURCHASE', and a gym named '... PAYMENTS'
    must not read as a card payoff."""
    card = models.CreditCard(name="Chase Sapphire", credit_limit=Decimal("1"),
                             statement_day=28, due_day=25)
    for desc in ["POS PURCHASE TARGET #1234", "KROGER #5001", "MINDBODY PAYMENTS",
                 "DEBIT CARD PURCHASE ALDI"]:
        assert is_real_checking_spend(desc, [card]) is True, f"{desc} must count as spend"


# --- End to end ----------------------------------------------------------

def test_merchant_totals_excludes_payoff_and_transfer(db_session):
    user, account, card = _setup(db_session)
    _txn(db_session, user, account, "CHASE CREDIT CRD AUTOPAY  PPD ID: 476", "-11312.54")
    _txn(db_session, user, account, "Online Transfer to CHK ...0054", "-1000.00")
    _txn(db_session, user, account, "KROGER #5001", "-120.00")
    db_session.commit()

    rows = merchant_totals(db_session, user.id, date(2026, 7, 1), date(2026, 7, 31))
    names = [n for n, _, _ in rows]

    assert names == ["KROGER #5001"], f"only real spend should appear, got {names}"
    assert sum(t for _, t, _ in rows) == Decimal("120.00")


def test_category_totals_excludes_payoff_and_transfer(db_session):
    """The same exclusion has to apply to categories, or the Spending page's
    two halves disagree with each other."""
    user, account, card = _setup(db_session)
    groceries = models.Category(user_id=user.id, name="Groceries", type=models.CategoryType.expense)
    db_session.add(groceries)
    db_session.flush()

    _txn(db_session, user, account, "CHASE CREDIT CRD AUTOPAY", "-11312.54")
    _txn(db_session, user, account, "Online Transfer to SAV ...8452", "-500.00")
    t = _txn(db_session, user, account, "KROGER #5001", "-120.00")
    t.category_id = groceries.id
    db_session.commit()

    totals = category_totals_for_range(db_session, user.id, date(2026, 7, 1), date(2026, 7, 31))

    assert totals.get(groceries.id) == Decimal("120.00")
    assert sum(totals.values()) == Decimal("120.00"), (
        f"payoff/transfer leaked into an uncategorized bucket: {totals}"
    )


def test_a_refund_only_merchant_does_not_crash(db_session):
    """Latent KeyError surfaced 2026-08-15 on Dan's real July data: a merchant
    appearing ONLY as a refund lands in `totals` but never increments
    `counts`, which is guarded to charges. That 500'd the whole page."""
    user, account, card = _setup(db_session)
    db_session.add(models.CreditCardTransaction(
        user_id=user.id, card_id=card.id, date=date(2026, 7, 10),
        amount=Decimal("-45.00"), merchant="MICHAELS STORES 9951",
    ))
    db_session.commit()

    rows = merchant_totals(db_session, user.id, date(2026, 7, 1), date(2026, 7, 31))
    entry = next((r for r in rows if r[0] == "MICHAELS STORES 9951"), None)
    assert entry is not None
    assert entry[2] == 0, "a refund-only merchant has zero charges"


def test_a_real_refund_still_nets_against_its_charge(db_session):
    """Guard against over-correcting: netting behaviour must survive."""
    user, account, card = _setup(db_session)
    db_session.add_all([
        models.CreditCardTransaction(user_id=user.id, card_id=card.id, date=date(2026, 7, 5),
                                     amount=Decimal("100.00"), merchant="TARGET"),
        models.CreditCardTransaction(user_id=user.id, card_id=card.id, date=date(2026, 7, 9),
                                     amount=Decimal("-30.00"), merchant="TARGET"),
    ])
    db_session.commit()

    rows = merchant_totals(db_session, user.id, date(2026, 7, 1), date(2026, 7, 31))
    assert dict((n, t) for n, t, _ in rows)["TARGET"] == Decimal("70.00")
