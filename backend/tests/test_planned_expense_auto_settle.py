"""Auto-settling a planned one-off once its real charge shows up.

A PlannedExpense only left the forecast when the user settled it by hand. A
card-routed one-off is projected as its own "<name> (via <card>)" line on the
card's payoff date, while the real charge -- first as a pending card charge
(already inside the cycle estimate's `pending`) and later as a posted card
transaction -- is counted by the card's own payoff/estimate line. Until the
user remembered to settle it, the same money came off checking twice. A
checking-routed one-off had the same problem against real checking
transactions: nothing in the forecast suppresses a planned line against an
actual that already moved the balance.

auto_settle_planned_expenses() closes the plan against the real charge after
each bank sync. All figures here are synthetic.
"""
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

from backend import models
from backend.services.bank_sync_service import sync_all
from backend.services.forecast_engine import build_forecast
from backend.services.planned_auto_settle import auto_settle_planned_expenses
from backend.services.simplefin_client import SimpleFinTransaction

TODAY = date(2026, 10, 8)
SYNCED_AT = datetime(2026, 10, 8, 6, 0)


def _freeze_today(monkeypatch, fixed: date = TODAY) -> None:
    class _FixedDate(date):
        @classmethod
        def today(cls):
            return fixed
    monkeypatch.setattr("backend.services.forecast_engine.date", _FixedDate)


def _seed(db):
    user = models.User(username="autosettle", hashed_password="x", display_name="Auto")
    db.add(user)
    db.flush()
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("5000.00"),
    )
    # statement_day=15, due_day=1: a charge on 10/8 closes 10/15 and is paid 11/1.
    card = models.CreditCard(
        user_id=user.id, name="Visa", credit_limit=Decimal("5000.00"),
        statement_day=15, due_day=1, current_balance=Decimal("0.00"),
    )
    db.add_all([account, card])
    db.commit()
    return user, account, card


def _planned(db, user, *, name="Insurance", amount="250.00", expected=TODAY,
             card=None, account=None, direction=models.PlannedDirection.outflow, **kw):
    pe = models.PlannedExpense(
        user_id=user.id, name=name, amount=Decimal(amount), expected_date=expected,
        card_id=card.id if card else None, account_id=account.id if account else None,
        direction=direction, **kw,
    )
    db.add(pe)
    db.commit()
    return pe


def _pending_card(db, user, card, amount="250.00", day=TODAY, merchant="INSURANCE CO", ext="p1"):
    db.add(models.CardPendingTransaction(
        user_id=user.id, card_id=card.id, external_id=ext, date=day,
        amount=Decimal(amount), merchant=merchant, synced_at=SYNCED_AT,
    ))
    card.pending_charges = (card.pending_charges or Decimal("0")) + Decimal(amount)
    card.pending_charges_updated_at = SYNCED_AT
    db.commit()


def _posted_card(db, user, card, amount="250.00", day=TODAY, merchant="INSURANCE CO"):
    db.add(models.CreditCardTransaction(
        user_id=user.id, card_id=card.id, date=day, amount=Decimal(amount), merchant=merchant,
    ))
    db.commit()


def _posted_checking(db, user, account, amount, day=TODAY, description="DEPOSIT"):
    db.add(models.Transaction(
        user_id=user.id, account_id=account.id, date=day, amount=Decimal(amount),
        description=description, is_actual=True,
    ))
    db.commit()


def _names_on(entries, d):
    return [t.name for e in entries if e.date == d for t in e.transactions]


def _total_on(entries, d):
    return sum((t.amount for e in entries if e.date == d for t in e.transactions), Decimal("0"))


# --- card-routed outflows -------------------------------------------------

def test_exact_pending_card_charge_settles_the_plan_and_drops_one_copy(db_session, monkeypatch):
    """The real case shape: planned $250 on the card for day D, then a pending
    $250 charge on that card dated D. Before: the payoff day carries the
    cycle estimate (which already holds the pending $250) AND the planned
    "(via Visa)" line. After: only the estimate -- exactly one copy less."""
    _freeze_today(monkeypatch)
    user, account, card = _seed(db_session)
    # $100 already posted this cycle, so the card projects a cycle estimate
    # (posted + pending) on its 11/1 payoff.
    card.current_balance = Decimal("100.00")
    card.next_payment_date = date(2026, 11, 1)
    db_session.commit()
    pe = _planned(db_session, user, card=card)
    _pending_card(db_session, user, card)
    payoff = date(2026, 11, 1)

    before = build_forecast(db_session, user.id, account.id, TODAY, date(2026, 11, 30))
    assert "Insurance (via Visa)" in _names_on(before, payoff)
    assert _total_on(before, payoff) == Decimal("-600.00"), "estimate (100 + 250 pending) plus the plan: 250 twice"

    settled = auto_settle_planned_expenses(db_session, user.id)
    db_session.commit()

    assert [s.planned_expense_id for s in settled] == [pe.id]
    db_session.refresh(pe)
    assert pe.settled_on == TODAY
    assert pe.actual_amount == Decimal("250.00")
    assert pe.amount == Decimal("250.00"), "the estimate is kept beside the actual"

    after = build_forecast(db_session, user.id, account.id, TODAY, date(2026, 11, 30))
    assert "Insurance (via Visa)" not in _names_on(after, payoff)
    assert _total_on(after, payoff) - _total_on(before, payoff) == Decimal("250.00")
    assert _total_on(after, payoff) == Decimal("-350.00"), "the pending charge is still paid off once"


def test_posted_card_charge_settles_the_plan(db_session):
    user, account, card = _seed(db_session)
    pe = _planned(db_session, user, card=card, expected=date(2026, 10, 10))
    _posted_card(db_session, user, card, amount="249.40", day=date(2026, 10, 12))

    auto_settle_planned_expenses(db_session, user.id)
    db_session.commit()
    db_session.refresh(pe)
    assert pe.settled_on == date(2026, 10, 12)
    assert pe.actual_amount == Decimal("249.40")


def test_amount_more_than_a_dollar_off_does_not_settle(db_session):
    user, account, card = _seed(db_session)
    pe = _planned(db_session, user, card=card)
    _pending_card(db_session, user, card, amount="251.01")

    assert auto_settle_planned_expenses(db_session, user.id) == []
    db_session.refresh(pe)
    assert pe.settled_on is None


def test_charge_outside_the_date_window_does_not_settle(db_session):
    """Window is [expected - 7 days, expected + 14 days]: the edges count,
    one day past either edge does not."""
    user, account, card = _seed(db_session)
    early = _planned(db_session, user, name="Early", card=card, expected=date(2026, 10, 10))
    late = _planned(db_session, user, name="Late", amount="80.00", card=card, expected=date(2026, 10, 10))
    _posted_card(db_session, user, card, amount="250.00", day=date(2026, 10, 2))   # 8 days early
    _posted_card(db_session, user, card, amount="80.00", day=date(2026, 10, 25))   # 15 days late

    assert auto_settle_planned_expenses(db_session, user.id) == []

    _posted_card(db_session, user, card, amount="250.00", day=date(2026, 10, 3))   # exactly 7 early
    _posted_card(db_session, user, card, amount="80.00", day=date(2026, 10, 24))   # exactly 14 late
    settled = auto_settle_planned_expenses(db_session, user.id)
    db_session.commit()
    assert sorted(s.planned_expense_id for s in settled) == sorted([early.id, late.id])


def test_one_charge_settles_only_one_of_two_matching_plans(db_session):
    """Each real charge closes at most one plan: the closer date wins."""
    user, account, card = _seed(db_session)
    near = _planned(db_session, user, name="Near", card=card, expected=date(2026, 10, 9))
    far = _planned(db_session, user, name="Far", card=card, expected=date(2026, 10, 14))
    _pending_card(db_session, user, card, day=date(2026, 10, 8))

    settled = auto_settle_planned_expenses(db_session, user.id)
    db_session.commit()
    assert [s.planned_expense_id for s in settled] == [near.id]
    db_session.refresh(far)
    assert far.settled_on is None


def test_closer_amount_beats_closer_date(db_session):
    user, account, card = _seed(db_session)
    pe = _planned(db_session, user, card=card, expected=date(2026, 10, 10))
    _posted_card(db_session, user, card, amount="250.90", day=date(2026, 10, 10))
    _posted_card(db_session, user, card, amount="250.00", day=date(2026, 10, 15))

    auto_settle_planned_expenses(db_session, user.id)
    db_session.refresh(pe)
    assert pe.actual_amount == Decimal("250.00")
    assert pe.settled_on == date(2026, 10, 15)


def test_a_charge_that_already_settled_a_plan_is_not_reused_after_it_posts(db_session):
    """Sync 1 settles plan A against the pending row. Sync 2: the pending row
    has posted (new row, later date). A second, still-open plan for the same
    amount must not claim that same money again."""
    user, account, card = _seed(db_session)
    a = _planned(db_session, user, name="A", card=card, expected=date(2026, 10, 8))
    _pending_card(db_session, user, card, day=date(2026, 10, 8))
    auto_settle_planned_expenses(db_session, user.id)
    db_session.commit()
    db_session.refresh(a)
    assert a.settled_on == date(2026, 10, 8)

    b = _planned(db_session, user, name="B", card=card, expected=date(2026, 10, 9))
    db_session.query(models.CardPendingTransaction).delete()
    _posted_card(db_session, user, card, day=date(2026, 10, 10))

    assert auto_settle_planned_expenses(db_session, user.id) == []
    db_session.refresh(b)
    assert b.settled_on is None


def test_card_payments_never_match(db_session):
    """A card-routed planned INFLOW (a refund) matches a credit on the card,
    but a payment to the card is not a refund."""
    user, account, card = _seed(db_session)
    pe = _planned(db_session, user, name="Refund", card=card, direction=models.PlannedDirection.inflow)
    _posted_card(db_session, user, card, amount="-250.00", merchant="PAYMENT THANK YOU")
    assert auto_settle_planned_expenses(db_session, user.id) == []

    _posted_card(db_session, user, card, amount="-250.00", merchant="INSURANCE CO REFUND")
    auto_settle_planned_expenses(db_session, user.id)
    db_session.refresh(pe)
    assert pe.settled_on == TODAY
    assert pe.actual_amount == Decimal("250.00")


def test_a_charge_side_card_payment_row_never_matches_a_planned_charge(db_session):
    """Some issuers list the payment with a positive (charge-side) amount."""
    user, account, card = _seed(db_session)
    pe = _planned(db_session, user, card=card)
    _posted_card(db_session, user, card, amount="250.00", merchant="AUTOMATIC PAYMENT - THANK")
    assert auto_settle_planned_expenses(db_session, user.id) == []
    db_session.refresh(pe)
    assert pe.settled_on is None


def test_direction_must_agree(db_session):
    """A $250 refund on the card is not the planned $250 charge."""
    user, account, card = _seed(db_session)
    pe = _planned(db_session, user, card=card)
    _posted_card(db_session, user, card, amount="-250.00", merchant="INSURANCE CO REFUND")
    assert auto_settle_planned_expenses(db_session, user.id) == []
    db_session.refresh(pe)
    assert pe.settled_on is None


def test_charge_on_a_different_card_does_not_match(db_session):
    user, account, card = _seed(db_session)
    other = models.CreditCard(user_id=user.id, name="Amex", credit_limit=Decimal("1000.00"),
                              statement_day=20, due_day=10)
    db_session.add(other)
    db_session.commit()
    pe = _planned(db_session, user, card=card)
    _posted_card(db_session, user, other)
    assert auto_settle_planned_expenses(db_session, user.id) == []
    db_session.refresh(pe)
    assert pe.settled_on is None


# --- checking-routed one-offs ---------------------------------------------

def test_checking_planned_inflow_settles_against_a_matching_deposit(db_session, monkeypatch):
    """Nothing in the forecast suppressed a checking planned line against a
    real deposit that already landed: a payout arriving two days early
    sat in the balance AND stayed projected on its expected date."""
    _freeze_today(monkeypatch)
    user, account, card = _seed(db_session)
    pe = _planned(db_session, user, name="Payout", amount="400.00", account=account,
                  expected=date(2026, 10, 10), direction=models.PlannedDirection.inflow)
    _posted_checking(db_session, user, account, "400.00", day=TODAY, description="MARKETPLACE PAYOUT")

    before = build_forecast(db_session, user.id, account.id, TODAY, date(2026, 10, 31))
    assert "Payout" in _names_on(before, date(2026, 10, 10))

    auto_settle_planned_expenses(db_session, user.id)
    db_session.commit()
    db_session.refresh(pe)
    assert pe.settled_on == TODAY
    assert pe.actual_amount == Decimal("400.00")

    after = build_forecast(db_session, user.id, account.id, TODAY, date(2026, 10, 31))
    assert "Payout" not in _names_on(after, date(2026, 10, 10))


def test_checking_planned_outflow_settles_against_a_pending_debit(db_session):
    user, account, card = _seed(db_session)
    pe = _planned(db_session, user, name="Contractor", amount="600.00", account=account)
    db_session.add(models.AccountPendingTransaction(
        user_id=user.id, account_id=account.id, external_id="ap1", date=TODAY,
        amount=Decimal("-600.00"), description="CONTRACTOR LLC", synced_at=SYNCED_AT,
    ))
    db_session.commit()

    auto_settle_planned_expenses(db_session, user.id)
    db_session.refresh(pe)
    assert pe.settled_on == TODAY
    assert pe.actual_amount == Decimal("600.00")


def test_checking_card_payments_and_transfers_never_match(db_session):
    user, account, card = _seed(db_session)
    pe = _planned(db_session, user, name="Big purchase", amount="250.00", account=account)
    _posted_checking(db_session, user, account, "-250.00", description="VISA AUTOPAY")
    _posted_checking(db_session, user, account, "-250.00", description="ONLINE TRANSFER TO SAVINGS")
    assert auto_settle_planned_expenses(db_session, user.id) == []
    db_session.refresh(pe)
    assert pe.settled_on is None


def test_funded_plan_is_left_for_the_user(db_session):
    """Settling a savings-funded plan also drops its projected funding
    transfer, and nothing records whether that transfer really happened --
    so it is never auto-settled. It still claims its charge, so the charge
    can't settle some other plan instead."""
    user, account, card = _seed(db_session)
    savings = models.Account(user_id=user.id, name="Savings", type=models.AccountType.savings)
    db_session.add(savings)
    db_session.commit()
    funded = _planned(db_session, user, name="Car", amount="250.00", account=account,
                      funding_account_id=savings.id)
    other = _planned(db_session, user, name="Other", amount="250.00", account=account,
                     expected=date(2026, 10, 9))
    _posted_checking(db_session, user, account, "-250.00", description="DEALER")

    assert auto_settle_planned_expenses(db_session, user.id) == []
    db_session.refresh(funded)
    db_session.refresh(other)
    assert funded.settled_on is None
    assert other.settled_on is None


def test_never_unsettles_and_ignores_other_users(db_session):
    user, account, card = _seed(db_session)
    pe = _planned(db_session, user, card=card, settled_on=date(2026, 10, 1),
                  actual_amount=Decimal("240.00"))
    stranger = models.User(username="other", hashed_password="x", display_name="O")
    db_session.add(stranger)
    db_session.commit()
    _pending_card(db_session, user, card)

    assert auto_settle_planned_expenses(db_session, stranger.id) == []
    assert auto_settle_planned_expenses(db_session, user.id) == []
    db_session.refresh(pe)
    assert pe.settled_on == date(2026, 10, 1)
    assert pe.actual_amount == Decimal("240.00")


# --- wiring -----------------------------------------------------------------

def test_sync_all_settles_a_plan_once_the_card_feed_lists_its_charge(db_session):
    from tests.test_bank_sync_service import _make_card_connection
    user, card, connection, link = _make_card_connection(db_session)
    pe = _planned(db_session, user, card=card)
    feed = [SimpleFinTransaction(id="p1", posted=datetime(2026, 10, 8), amount=Decimal("-250.00"),
                                 description="INSURANCE CO", pending=True)]
    with patch("backend.services.bank_sync_service.decrypt", return_value="https://access.url"), \
         patch("backend.services.bank_sync_service.fetch_transactions",
               return_value=(feed, Decimal("-250.00"), None)):
        sync_all(db_session)

    db_session.refresh(pe)
    assert pe.settled_on == TODAY
    assert pe.actual_amount == Decimal("250.00")


def test_one_users_auto_settle_failure_does_not_stop_the_next(db_session):
    from backend.services import planned_auto_settle
    user, account, card = _seed(db_session)
    pe = _planned(db_session, user, card=card)
    _pending_card(db_session, user, card)
    real = planned_auto_settle.auto_settle_planned_expenses

    def flaky(db, user_id):
        if user_id == 999:
            raise RuntimeError("boom")
        return real(db, user_id)

    with patch.object(planned_auto_settle, "auto_settle_planned_expenses", side_effect=flaky):
        planned_auto_settle.settle_after_sync(db_session, [999, user.id, user.id])
    db_session.refresh(pe)
    assert pe.settled_on == TODAY
