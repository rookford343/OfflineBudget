"""A card payment that has left the card but not yet reached checking.

A card feed records the payment credit and resets balance_due to 0, but the
matching checking debit (holiday ACH delay) is neither posted nor pending.
The card-payment model reads "due date reached, nothing due" as paid and
plans no payoff, so checking still held money about to leave. The forecast
now keeps a "Payment in transit" line on today until a posted or pending
checking debit covers the card's recent payment credits.

All figures are invented; the repo is public."""
from datetime import date, datetime, timedelta
from decimal import Decimal

from backend import models
from backend.services.budget_snapshot import compute_budget_snapshot
from backend.services.forecast_engine import AUTO_ANCHOR_NOTE, build_forecast

TODAY = date(2026, 3, 20)
PAID = Decimal("2000.00")
AUTOPAY = "CHASE CREDIT CRD AUTOPAY 1234"
CARD_SIDE = "ONLINE PAYMENT - THANK YOU"


def _freeze_today(monkeypatch, fixed: date) -> None:
    class _FixedDate(date):
        @classmethod
        def today(cls):
            return fixed
    monkeypatch.setattr("backend.services.forecast_engine.date", _FixedDate)
    monkeypatch.setattr("backend.services.budget_snapshot.date", _FixedDate)


def _setup(db, monkeypatch, *, balance="5000.00", credit=PAID, merchant=CARD_SIDE,
           credit_date=TODAY - timedelta(days=2), **card_kw):
    _freeze_today(monkeypatch, TODAY)
    user = models.User(username="intransit", hashed_password="x", display_name="D")
    db.add(user)
    db.flush()
    account = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking,
                             current_balance=Decimal(balance))
    db.add(account)
    db.flush()
    fields = dict(name="Chase Sapphire", credit_limit=Decimal("10000.00"), statement_day=28,
                  due_day=25, is_active=True, balance_due=Decimal("0"),
                  current_balance=Decimal("0"), next_payment_date=TODAY - timedelta(days=2))
    fields.update(card_kw)
    card = models.CreditCard(user_id=user.id, **fields)
    db.add(card)
    db.flush()
    if credit is not None:
        db.add(models.CreditCardTransaction(card_id=card.id, user_id=user.id, date=credit_date,
                                            amount=-Decimal(credit), merchant=merchant))
    db.commit()
    return user, account, card


def _pending(db, user, account, amount):
    connection = models.BankConnection(user_id=user.id, provider="plaid", access_url_encrypted="tok",
                                       plaid_item_id="item-1")
    db.add(connection)
    db.flush()
    db.add(models.BankConnectionAccountLink(
        connection_id=connection.id, simplefin_account_id="p-chk", simplefin_account_name="Checking",
        local_account_id=account.id, is_active=True))
    db.add(models.AccountPendingTransaction(
        user_id=user.id, account_id=account.id, external_id="plaid:p1", date=TODAY,
        amount=Decimal(amount), description=AUTOPAY, synced_at=datetime(2026, 3, 20)))
    db.commit()


def _posted(db, user, account, amount, when=TODAY - timedelta(days=1)):
    db.add(models.Transaction(user_id=user.id, account_id=account.id, date=when, amount=Decimal(amount),
                              description=AUTOPAY, is_actual=True))
    db.commit()


def _days(db, user, account, include_unbilled=True):
    return build_forecast(db, user.id, account.id, TODAY, TODAY + timedelta(days=10),
                          include_unbilled_card_bills=include_unbilled)


def _lines(days, prefix="Payment in transit"):
    return [t for d in days for t in d.transactions if t.name.startswith(prefix)]


def _today(days):
    return next(d for d in days if d.date == TODAY)


def test_credit_with_no_debit_keeps_the_payment_in_the_forecast(db_session, monkeypatch):
    user, account, _ = _setup(db_session, monkeypatch)
    for unbilled in (True, False):
        days = _days(db_session, user, account, unbilled)
        lines = _lines(days)
        assert [(t.name, t.amount) for t in lines] == [("Payment in transit: Chase Sapphire", -PAID)]
        assert lines[0] in _today(days).transactions
        assert _today(days).projected_balance == Decimal("5000.00") - PAID


def test_balance_is_lower_by_the_payment_than_without_the_credit(db_session, monkeypatch):
    user, account, card = _setup(db_session, monkeypatch)
    with_line = _today(_days(db_session, user, account)).projected_balance
    db_session.query(models.CreditCardTransaction).delete()
    db_session.commit()
    without = _today(_days(db_session, user, account)).projected_balance
    assert without - with_line == PAID


def test_pending_debit_covers_the_credit(db_session, monkeypatch):
    user, account, _ = _setup(db_session, monkeypatch)
    _pending(db_session, user, account, "-2000.00")
    days = _days(db_session, user, account)
    assert _lines(days) == []
    # the bank's pending row is the one that subtracts, once
    assert [t.amount for t in _lines(days, "Pending")] == [-PAID]
    assert _today(days).projected_balance == Decimal("5000.00") - PAID


def test_posted_debit_covers_the_credit(db_session, monkeypatch):
    user, account, _ = _setup(db_session, monkeypatch, balance="3000.00")
    _posted(db_session, user, account, "-2000.00")
    days = _days(db_session, user, account)
    assert _lines(days) == []
    assert _today(days).projected_balance == Decimal("3000.00")


def test_partial_pending_debit_leaves_the_remainder(db_session, monkeypatch):
    user, account, _ = _setup(db_session, monkeypatch)
    _pending(db_session, user, account, "-500.00")
    days = _days(db_session, user, account)
    assert [t.amount for t in _lines(days)] == [Decimal("-1500.00")]
    assert _today(days).projected_balance == Decimal("5000.00") - PAID


def test_refund_credit_is_not_a_payment(db_session, monkeypatch):
    user, account, _ = _setup(db_session, monkeypatch, merchant="AMAZON REFUND")
    assert _lines(_days(db_session, user, account)) == []


def test_old_credit_is_ignored(db_session, monkeypatch):
    user, account, _ = _setup(db_session, monkeypatch, credit_date=TODAY - timedelta(days=11))
    assert _lines(_days(db_session, user, account)) == []


def test_credit_at_the_ten_day_edge_counts(db_session, monkeypatch):
    user, account, _ = _setup(db_session, monkeypatch, credit_date=TODAY - timedelta(days=10))
    assert len(_lines(_days(db_session, user, account))) == 1


def test_manual_marker_wins(db_session, monkeypatch):
    user, account, _ = _setup(db_session, monkeypatch, payment_sent_pending_sync=True,
                              payment_sent_amount=Decimal("1800.00"))
    days = _days(db_session, user, account)
    assert _lines(days) == []
    assert [t.amount for t in _lines(days, "Payment sent")] == [Decimal("-1800.00")]


def test_locked_payoff_does_not_also_inject_the_payment(db_session, monkeypatch):
    # nothing due: the model plans no payoff; only the in-transit line moves money
    user, account, _ = _setup(db_session, monkeypatch)
    days = _days(db_session, user, account)
    assert _lines(days, "CC Payment") == []
    assert sum(t.amount for t in _lines(days, "CC ")) == 0
    assert len(_lines(days)) == 1


def test_safety_margin_matches_once_the_money_has_left(db_session, monkeypatch):
    user, account, _ = _setup(db_session, monkeypatch)
    in_transit = compute_budget_snapshot(db_session, user, account.id, as_of=TODAY)
    assert in_transit.explain["safety_margin"] is not None

    # Same world, debit posted: checking already lower by the payment.
    db_session.query(models.CreditCardTransaction).delete()
    account.current_balance = Decimal("3000.00")
    db_session.commit()
    _posted(db_session, user, account, "-2000.00")
    db_session.add(models.CreditCardTransaction(
        card_id=db_session.query(models.CreditCard).first().id, user_id=user.id,
        date=TODAY - timedelta(days=2), amount=-PAID, merchant=CARD_SIDE))
    db_session.commit()
    posted = compute_budget_snapshot(db_session, user, account.id, as_of=TODAY)

    assert in_transit.safety_margin == posted.safety_margin
    # the payment is out of the margin either way (no other cash flows here)
    assert in_transit.safety_margin == Decimal("3000.00")


def _checkpoint(db, user, account, balance, note):
    db.add(models.ForecastDayCheckpoint(user_id=user.id, account_id=account.id, date=TODAY,
                                        actual_balance=Decimal(balance), note=note))
    db.commit()


def test_manual_anchor_keeps_the_in_transit_line(db_session, monkeypatch):
    # A hand-read balance still includes money that has not left the bank.
    user, account, _ = _setup(db_session, monkeypatch)
    _checkpoint(db_session, user, account, "5000.00", "read it off the app")
    days = _days(db_session, user, account)
    assert [t.amount for t in _lines(days)] == [-PAID]
    assert _today(days).projected_balance == Decimal("5000.00") - PAID


def test_auto_anchor_keeps_the_in_transit_line_and_matches_no_checkpoint(db_session, monkeypatch):
    user, account, _ = _setup(db_session, monkeypatch)
    plain = _today(_days(db_session, user, account)).projected_balance
    _checkpoint(db_session, user, account, "5000.00", AUTO_ANCHOR_NOTE)
    days = _days(db_session, user, account)
    assert [t.amount for t in _lines(days)] == [-PAID]
    assert _today(days).projected_balance == plain == Decimal("5000.00") - PAID


def test_unnamed_debit_with_ambiguous_card_still_covers(db_session, monkeypatch):
    # Two "Chase" cards: the wording pins neither, but it is a card payment of
    # the same amount, so the money has left and the line must go.
    user, account, _ = _setup(db_session, monkeypatch, balance="3000.00")
    db_session.add(models.CreditCard(user_id=user.id, name="Chase Freedom", credit_limit=Decimal("5000.00"),
                                     statement_day=28, due_day=25, is_active=True,
                                     balance_due=Decimal("0"), current_balance=Decimal("0")))
    db_session.commit()
    _posted(db_session, user, account, "-2000.00")
    assert _lines(_days(db_session, user, account)) == []


def test_ambiguous_debit_of_another_amount_does_not_cover(db_session, monkeypatch):
    user, account, _ = _setup(db_session, monkeypatch)
    db_session.add(models.CreditCard(user_id=user.id, name="Chase Freedom", credit_limit=Decimal("5000.00"),
                                     statement_day=28, due_day=25, is_active=True,
                                     balance_due=Decimal("0"), current_balance=Decimal("0")))
    db_session.commit()
    _posted(db_session, user, account, "-750.00")
    assert [t.amount for t in _lines(_days(db_session, user, account))] == [-PAID]


def test_debit_matched_to_another_card_does_not_cover(db_session, monkeypatch):
    user, account, _ = _setup(db_session, monkeypatch)
    db_session.add(models.CreditCard(user_id=user.id, name="Visa Rewards", credit_limit=Decimal("5000.00"),
                                     statement_day=28, due_day=25, is_active=True,
                                     balance_due=Decimal("0"), current_balance=Decimal("0")))
    db_session.commit()
    db_session.add(models.Transaction(user_id=user.id, account_id=account.id, date=TODAY - timedelta(days=1),
                                      amount=Decimal("-2000.00"), description="VISA CREDIT CRD AUTOPAY",
                                      is_actual=True))
    db_session.commit()
    assert [t.amount for t in _lines(_days(db_session, user, account))] == [-PAID]


def test_statement_still_due_is_charged_once_by_the_payoff(db_session, monkeypatch):
    # The card feed shows the credit but liabilities still show that statement:
    # the overdue payoff already charges it, so no in-transit line on top.
    user, account, _ = _setup(db_session, monkeypatch, balance_due=PAID,
                              next_payment_date=TODAY - timedelta(days=2))
    _checkpoint(db_session, user, account, "5000.00", AUTO_ANCHOR_NOTE)
    days = _days(db_session, user, account)
    assert _lines(days) == []
    charged = [t.amount for t in _today(days).transactions if t.is_cc_payment and t.amount < 0]
    assert charged == [-PAID]
    assert _today(days).projected_balance == Decimal("5000.00") - PAID


def test_older_payment_with_its_late_debit_does_not_cover_a_newer_credit(db_session, monkeypatch):
    user, account, card = _setup(db_session, monkeypatch, balance="3000.00")  # new credit, 2 days ago
    db_session.add(models.CreditCardTransaction(card_id=card.id, user_id=user.id,
                                                date=TODAY - timedelta(days=12), amount=-PAID, merchant=CARD_SIDE))
    db_session.commit()
    _posted(db_session, user, account, "-2000.00", when=TODAY - timedelta(days=6))
    assert [t.amount for t in _lines(_days(db_session, user, account))] == [-PAID]
