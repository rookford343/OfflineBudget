"""A card's statement due date that has just passed.

Two shapes, both seen the day after a due date:

* Paid statement: the card's feed marked it paid (balance_due 0) but still
  reports the paid statement's due date until the next statement arrives.
  Nothing more is owed on that date, so the forecast must not put a flat
  estimate (or anything else) there; the next cycle belongs on the
  FOLLOWING due date, once.
* Unpaid statement: balance_due still stands and the payment has not posted.
  The forecast walks the last week (the Transactions page's pending list,
  and the bridge behind every start=today forecast), so the real payoff
  belongs on its real due date, locked -- not rolled a month forward as
  "stale", which left only the card's subscription estimate on the date.

Plus the pending-debit interplay: a payment pending at the bank counts once.

All figures are invented; the repo is public."""
from datetime import date, datetime, timedelta
from decimal import Decimal

from backend import models
from backend.services.forecast_engine import AUTO_ANCHOR_NOTE, build_forecast, has_unsettled_projection

TODAY = date(2027, 3, 26)
DUE = date(2027, 3, 25)  # yesterday


def _freeze(monkeypatch):
    class _FixedDate(date):
        @classmethod
        def today(cls):
            return TODAY
    monkeypatch.setattr("backend.services.forecast_engine.date", _FixedDate)


def _setup(db):
    user = models.User(username="duepassed", hashed_password="x", display_name="the user")
    db.add(user)
    db.flush()
    account = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking,
                             current_balance=Decimal("5000.00"))
    db.add(account)
    db.flush()
    return user, account


def _paid_chase(db, user, **kw):
    fields = dict(name="Chase Sapphire", credit_limit=Decimal("9000.00"), statement_day=28, due_day=25,
                  is_active=True, balance_due=Decimal("0"), current_balance=Decimal("1200.00"),
                  next_payment_date=DUE, monthly_spend_estimate=Decimal("1000.00"))
    fields.update(kw)
    card = models.CreditCard(user_id=user.id, **fields)
    db.add(card)
    db.flush()
    return card


def _unpaid_apple(db, user, account):
    card = models.CreditCard(user_id=user.id, name="Apple Card", credit_limit=Decimal("2000.00"),
                             statement_day=31, due_day=25, is_active=True, balance_due=Decimal("150.00"),
                             current_balance=Decimal("160.00"), next_payment_date=DUE,
                             monthly_spend_estimate=Decimal("0"))
    db.add(card)
    db.flush()
    _subscription(db, user, account, card, "50.00", day=30)
    return card


def _subscription(db, user, account, card, amount, day):
    db.add(models.RecurringItem(
        user_id=user.id, account_id=account.id, card_id=card.id, name=f"Sub {card.name}",
        amount=Decimal(amount), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=day, start_date=date(2026, 1, 1),
    ))
    db.flush()


def _pending(db, user, account, amount, description):
    connection = models.BankConnection(user_id=user.id, provider="plaid", access_url_encrypted="tok",
                                       plaid_item_id=f"item-{description}")
    db.add(connection)
    db.flush()
    db.add(models.BankConnectionAccountLink(connection_id=connection.id, simplefin_account_id=f"p-{description}",
                                            simplefin_account_name="Checking", local_account_id=account.id,
                                            is_active=True))
    db.add(models.AccountPendingTransaction(
        user_id=user.id, account_id=account.id, external_id=f"plaid:{description}", date=TODAY,
        amount=Decimal(amount), description=description, synced_at=datetime(2027, 1, 1),
    ))
    db.flush()


def _card_lines(entries, card_name):
    return [(e.date, t.name, t.amount) for e in entries for t in e.transactions
            if t.name.endswith(f": {card_name}")]


def test_paid_statement_due_date_gets_nothing(db_session, monkeypatch):
    _freeze(monkeypatch)
    user, account = _setup(db_session)
    _paid_chase(db_session, user)
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, TODAY - timedelta(days=7), TODAY)
    assert _card_lines(entries, "Chase Sapphire") == []


def test_paid_statement_next_cycle_planned_once_on_following_due_date(db_session, monkeypatch):
    _freeze(monkeypatch)
    user, account = _setup(db_session)
    _paid_chase(db_session, user)
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, TODAY - timedelta(days=7), date(2027, 4, 30))
    assert _card_lines(entries, "Chase Sapphire") == [
        (date(2027, 4, 25), "CC Estimate: Chase Sapphire", Decimal("-1200.00")),
    ]


def test_paid_statement_on_subscription_card_gets_nothing(db_session, monkeypatch):
    """Same rule for a card estimated from its subscriptions: a charge
    billed into the paid statement is already paid."""
    _freeze(monkeypatch)
    user, account = _setup(db_session)
    card = _paid_chase(db_session, user, monthly_spend_estimate=Decimal("0"), current_balance=Decimal("0"))
    _subscription(db_session, user, account, card, "40.00", day=10)
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, TODAY - timedelta(days=7), TODAY)
    assert _card_lines(entries, "Chase Sapphire") == []


def test_unpaid_statement_payoff_lands_on_its_due_date(db_session, monkeypatch):
    _freeze(monkeypatch)
    user, account = _setup(db_session)
    _unpaid_apple(db_session, user, account)
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, TODAY - timedelta(days=7), TODAY)
    lines = [(e.date, t.name, t.amount, t.is_cc_locked) for e in entries for t in e.transactions
             if t.name.endswith(": Apple Card")]
    assert lines == [(DUE, "CC Payment: Apple Card", Decimal("-150.00"), True)]


def test_unpaid_statement_is_counted_by_a_start_today_forecast(db_session, monkeypatch):
    """The start=today walk bridges through the last week, so the unposted
    payoff comes out of today's balance once, and is not planned again."""
    _freeze(monkeypatch)
    user, account = _setup(db_session)
    _unpaid_apple(db_session, user, account)
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, TODAY, date(2027, 4, 30))
    assert entries[0].projected_balance == Decimal("4850.00")
    assert _card_lines(entries, "Apple Card") == [
        (date(2027, 4, 25), "CC Estimate: Apple Card", Decimal("-60.00")),
    ]


def test_pending_full_payment_of_a_paid_statement_counts_once(db_session, monkeypatch):
    _freeze(monkeypatch)
    user, account = _setup(db_session)
    _paid_chase(db_session, user)
    _pending(db_session, user, account, "-900.00", "CHASE CREDIT CRD AUTOPAY")
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, TODAY - timedelta(days=7), TODAY)
    assert _card_lines(entries, "Chase Sapphire") == []
    pending = [(e.date, t.amount) for e in entries for t in e.transactions if t.name.startswith("Pending: ")]
    assert pending == [(TODAY, Decimal("-900.00"))]
    assert entries[-1].projected_balance == Decimal("4100.00")


def test_pending_payoff_replaces_the_unpaid_statement_payoff(db_session, monkeypatch):
    _freeze(monkeypatch)
    user, account = _setup(db_session)
    _unpaid_apple(db_session, user, account)
    _pending(db_session, user, account, "-150.00", "APPLECARD GSBANK PAYMENT")
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, TODAY - timedelta(days=7), TODAY)
    assert _card_lines(entries, "Apple Card") == []
    pending = [(e.date, t.amount) for e in entries for t in e.transactions if t.name.startswith("Pending: ")]
    assert pending == [(TODAY, Decimal("-150.00"))]
    assert entries[-1].projected_balance == Decimal("4850.00")


# --- Review fixes: posted-after-window payments, past estimates, auto anchor ---

APPLE_PAY = "APPLECARD GSBANK PAYMENT"


def _actual(db, user, account, amount, when, description=APPLE_PAY):
    db.add(models.Transaction(user_id=user.id, account_id=account.id, date=when, amount=Decimal(amount),
                              description=description, is_actual=True))
    db.flush()


def _anchor(db, user, account, balance, note=AUTO_ANCHOR_NOTE):
    db.add(models.ForecastDayCheckpoint(user_id=user.id, account_id=account.id, date=TODAY,
                                        actual_balance=Decimal(balance), note=note))
    db.flush()


def test_payment_posted_today_is_not_also_planned_by_the_bridge(db_session, monkeypatch):
    """The start=today bridge ends yesterday, so it never saw today's posted
    payment and kept the payoff -- counted twice with current_balance."""
    _freeze(monkeypatch)
    user, account = _setup(db_session)
    account.current_balance = Decimal("4850.00")
    _unpaid_apple(db_session, user, account)
    _actual(db_session, user, account, "-150.00", TODAY)
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, TODAY, TODAY)
    assert entries[0].projected_balance == Decimal("4850.00")


def test_payment_posting_after_the_bridge_is_not_also_planned(db_session, monkeypatch):
    _freeze(monkeypatch)
    user, account = _setup(db_session)
    _unpaid_apple(db_session, user, account)
    _actual(db_session, user, account, "-150.00", TODAY + timedelta(days=1))
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, TODAY, TODAY + timedelta(days=3))
    assert entries[-1].projected_balance == Decimal("4850.00")


def test_no_card_estimate_is_placed_before_today(db_session, monkeypatch):
    """The next statement has arrived (due next month), so this month's paid
    slot looks unclaimed again; an estimate must not land on a past date."""
    _freeze(monkeypatch)
    user, account = _setup(db_session)
    _paid_chase(db_session, user, balance_due=Decimal("1000.00"), current_balance=Decimal("1000.00"),
                next_payment_date=date(2027, 4, 25))
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, TODAY - timedelta(days=7), date(2027, 4, 30))
    assert _card_lines(entries, "Chase Sapphire") == [
        (date(2027, 4, 25), "CC Payment: Chase Sapphire", Decimal("-1000.00")),
    ]


def test_unposted_overdue_payoff_survives_todays_auto_anchor(db_session, monkeypatch):
    """The auto anchor is the posted balance, which doesn't have the unpaid
    payoff out of it: the payoff is re-planned on today, after the anchor."""
    _freeze(monkeypatch)
    user, account = _setup(db_session)
    _unpaid_apple(db_session, user, account)
    _anchor(db_session, user, account, "5000.00")
    db_session.commit()

    today_only = build_forecast(db_session, user.id, account.id, TODAY, TODAY)
    assert today_only[0].projected_balance == Decimal("4850.00")

    week = build_forecast(db_session, user.id, account.id, TODAY - timedelta(days=7), TODAY)
    assert week[-1].projected_balance == Decimal("4850.00")
    assert [(d, n, a) for d, n, a in _card_lines(week, "Apple Card")] == [
        (TODAY, "CC Payment: Apple Card", Decimal("-150.00")),
    ]


def test_hand_entered_anchor_is_not_reduced_by_the_overdue_payoff(db_session, monkeypatch):
    _freeze(monkeypatch)
    user, account = _setup(db_session)
    _unpaid_apple(db_session, user, account)
    _anchor(db_session, user, account, "4850.00", note="typed by the user")
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, TODAY, TODAY)
    assert entries[0].projected_balance == Decimal("4850.00")


def test_overdue_replan_and_pending_snapshot_count_once(db_session, monkeypatch):
    _freeze(monkeypatch)
    user, account = _setup(db_session)
    _unpaid_apple(db_session, user, account)
    _pending(db_session, user, account, "-150.00", APPLE_PAY)
    _anchor(db_session, user, account, "5000.00")
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, TODAY - timedelta(days=7), TODAY)
    assert entries[-1].projected_balance == Decimal("4850.00")
    assert _card_lines(entries, "Apple Card") == []


def test_overdue_replan_and_payment_sent_marker_count_once(db_session, monkeypatch):
    _freeze(monkeypatch)
    user, account = _setup(db_session)
    card = _unpaid_apple(db_session, user, account)
    card.payment_sent_pending_sync = True
    card.payment_sent_amount = Decimal("150.00")
    _anchor(db_session, user, account, "5000.00")
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, TODAY - timedelta(days=7), TODAY)
    assert entries[-1].projected_balance == Decimal("4850.00")


def test_overdue_replan_skips_a_posted_payment(db_session, monkeypatch):
    _freeze(monkeypatch)
    user, account = _setup(db_session)
    account.current_balance = Decimal("4850.00")
    _unpaid_apple(db_session, user, account)
    _actual(db_session, user, account, "-150.00", TODAY)
    _anchor(db_session, user, account, "4850.00")
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, TODAY - timedelta(days=7), TODAY)
    assert entries[-1].projected_balance == Decimal("4850.00")
    assert _card_lines(entries, "Apple Card") == []


def test_overdue_replan_does_not_hold_back_todays_anchor(db_session, monkeypatch):
    """Re-planned after the anchor, so a re-sync must still be free to
    refresh today's anchor (has_unsettled_projection)."""
    _freeze(monkeypatch)
    user, account = _setup(db_session)
    _unpaid_apple(db_session, user, account)
    _anchor(db_session, user, account, "5000.00")
    db_session.commit()

    assert has_unsettled_projection(db_session, user.id, account.id, TODAY) is False
