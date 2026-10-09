"""Auto-clear paid card statements + stale-statement warning.

Root cause (confirmed live): CreditCard.balance_due is a hand-entered
last-statement amount that bank sync never touches. Once a statement is
paid, balance_due keeps carrying the old statement total forever --
inflating Left to Spend (budget_snapshot.py) and making forecast_engine.py
roll the same payment forward as if it were still owed.

reconcile_statement_payment proves payment from the card's own
CreditCardTransaction history (payments/refunds post as negative amounts)
rather than trusting any outside signal, and only ever clears on FULL
coverage -- a partial payment is left alone so a later, real payoff can't
be double-subtracted.
"""
import pytest
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch
from backend import models
from backend.schemas import ForecastEntry
from backend.services.bank_sync_service import sync_connection
from backend.services.budget_snapshot import compute_budget_snapshot
from backend.services.simplefin_client import SimpleFinTransaction
from backend.services.statement_reconcile import (
    reconcile_all_cards,
    reconcile_statement_payment,
    statement_stale_reason,
)


def _enable_sync_auto_clear(monkeypatch):
    """The sync hook ships disabled (bank_sync_service.AUTO_CLEAR_STATEMENTS_IN_SYNC);
    these tests exercise the wiring itself, so they switch it on."""
    monkeypatch.setattr("backend.services.bank_sync_service.AUTO_CLEAR_STATEMENTS_IN_SYNC", True)

def _fake_quarter_min(amount: str, on: date):
    """Stands in for build_forecast() -- isolates these tests from
    forecast_engine's own correctness (its own suite covers that)."""
    return [ForecastEntry(date=on, projected_balance=Decimal(amount), transactions=[])]


def _make_card(db, *, username="dan", **overrides):
    user = models.User(username=username, hashed_password="x", display_name="the user")
    db.add(user)
    db.flush()
    defaults = dict(
        user_id=user.id, name="Chase Sapphire", credit_limit=Decimal("29000.00"),
        statement_day=28, due_day=25,
        current_balance=Decimal("0.00"), balance_due=Decimal("0.00"),
    )
    defaults.update(overrides)
    card = models.CreditCard(**defaults)
    db.add(card)
    db.commit()
    return user, card


def _credit(db, card, user_id, *, amount, on):
    db.add(models.CreditCardTransaction(
        card_id=card.id, user_id=user_id, date=on, amount=amount, merchant="Payment",
    ))


def test_full_payment_clears_balance_due_and_advances_next_payment_date(db_session):
    """Chase's exact live case: statement closed 8/28, due 9/25 at $6,945.00.
    A $6,900.00 autopay plus a $45.00 refund sum to exactly the statement --
    full coverage clears it and rolls the next cycle to 10/25."""
    user, card = _make_card(
        db_session, statement_day=28, due_day=25,
        next_payment_date=date(2026, 9, 25), balance_due=Decimal("6945.00"),
        current_balance=Decimal("0.00"),
    )
    _credit(db_session, card, user.id, amount=Decimal("-45.00"), on=date(2026, 9, 4))
    _credit(db_session, card, user.id, amount=Decimal("-6900.00"), on=date(2026, 9, 25))
    db_session.commit()

    cleared = reconcile_statement_payment(db_session, card, date(2026, 9, 30))

    assert cleared is True
    db_session.refresh(card)
    assert card.balance_due == Decimal("0")
    assert card.next_payment_date == date(2026, 10, 25)
    assert card.balance_due_updated_at is not None


@pytest.mark.parametrize("balance_due,credit,credit_on,entered_at", [
    # The close date is 8/28 (the occurrence strictly before 9/25's
    # next_payment_date); a credit ON it belongs to the prior cycle.
    pytest.param("6945.00", "-6945.00", date(2026, 8, 28), None, id="credit_on_close_date"),
    # A partial payment must not reduce balance_due: that would double-subtract
    # once a later real payoff supersedes it. statement_stale_reason covers it.
    pytest.param("6945.00", "-3000.00", date(2026, 9, 10), None, id="partial_payment"),
    # Rule 1: a credit after the close but before balance_due was last
    # entered is already reflected in the entered figure.
    pytest.param("6945.00", "-6945.00", date(2026, 9, 5), datetime(2026, 9, 10, 12, 0), id="credit_before_statement_entered"),
    # Rule 1 is strict (date > entered date): a same-day credit may already be
    # in the entered figure, so it's excluded; the stale warning covers it.
    pytest.param("500.00", "-500.00", date(2026, 9, 10), datetime(2026, 9, 10, 12, 0), id="credit_on_day_statement_entered"),
])
def test_credits_that_must_not_clear_the_statement(db_session, balance_due, credit, credit_on, entered_at):
    user, card = _make_card(
        db_session, statement_day=28, due_day=25,
        next_payment_date=date(2026, 9, 25), balance_due=Decimal(balance_due),
        balance_due_updated_at=entered_at,
    )
    _credit(db_session, card, user.id, amount=Decimal(credit), on=credit_on)
    db_session.commit()

    assert reconcile_statement_payment(db_session, card, date(2026, 9, 30)) is False
    db_session.refresh(card)
    assert card.balance_due == Decimal(balance_due)
    assert card.next_payment_date == date(2026, 9, 25)


def test_no_credits_makes_no_change(db_session):
    user, card = _make_card(
        db_session, statement_day=28, due_day=25,
        next_payment_date=date(2026, 9, 25), balance_due=Decimal("6945.00"),
    )
    db_session.commit()

    cleared = reconcile_statement_payment(db_session, card, date(2026, 9, 30))

    assert cleared is False
    db_session.refresh(card)
    assert card.balance_due == Decimal("6945.00")


def test_idempotent_second_call_is_a_no_op(db_session):
    user, card = _make_card(
        db_session, statement_day=28, due_day=25,
        next_payment_date=date(2026, 9, 25), balance_due=Decimal("6945.00"),
    )
    _credit(db_session, card, user.id, amount=Decimal("-6945.00"), on=date(2026, 9, 25))
    db_session.commit()

    first = reconcile_statement_payment(db_session, card, date(2026, 9, 30))
    db_session.refresh(card)
    cleared_at_first = card.balance_due_updated_at
    second = reconcile_statement_payment(db_session, card, date(2026, 9, 30))

    assert first is True
    assert second is False
    db_session.refresh(card)
    assert card.balance_due == Decimal("0")
    assert card.balance_due_updated_at == cleared_at_first


def test_another_cards_credits_do_not_count(db_session):
    user, card = _make_card(
        db_session, statement_day=28, due_day=25,
        next_payment_date=date(2026, 9, 25), balance_due=Decimal("6945.00"),
    )
    other_card = models.CreditCard(
        user_id=user.id, name="Other Card", credit_limit=Decimal("5000.00"),
        statement_day=28, due_day=25, current_balance=Decimal("0"), balance_due=Decimal("0"),
    )
    db_session.add(other_card)
    db_session.flush()
    _credit(db_session, other_card, user.id, amount=Decimal("-6945.00"), on=date(2026, 9, 25))
    db_session.commit()

    cleared = reconcile_statement_payment(db_session, card, date(2026, 9, 30))

    assert cleared is False
    db_session.refresh(card)
    assert card.balance_due == Decimal("6945.00")


def test_another_users_credits_do_not_count(db_session):
    user, card = _make_card(
        db_session, username="dan", statement_day=28, due_day=25,
        next_payment_date=date(2026, 9, 25), balance_due=Decimal("6945.00"),
    )
    other_user, other_card = _make_card(
        db_session, username="other", statement_day=28, due_day=25,
        next_payment_date=date(2026, 9, 25), balance_due=Decimal("6945.00"),
    )
    # Scoping bug would be: a query that filters by card_id alone without
    # user_id would still be safe here since card_id differs -- so instead
    # directly prove the user_id filter by writing a credit against THIS
    # card's id but tagged with the OTHER user's id (can't happen via the
    # real app, but proves the query really filters on user_id and not just
    # card_id, per the brief's explicit scoping requirement).
    _credit(db_session, card, other_user.id, amount=Decimal("-6945.00"), on=date(2026, 9, 25))
    db_session.commit()

    cleared = reconcile_statement_payment(db_session, card, date(2026, 9, 30))

    assert cleared is False
    db_session.refresh(card)
    assert card.balance_due == Decimal("6945.00")


# v1's test_next_payment_date_none_falls_back_to_today was removed in v2:
# a missing next_payment_date now refuses to reconcile at all (rule 2), see
# test_missing_next_payment_date_never_clears below.


def test_reconcile_preserves_payment_sent_pending_sync_clearing(db_session):
    """balance_due changing (clearing) must still flip a stale
    payment_sent_pending_sync marker, reusing
    routers.credit_cards._clear_pending_if_balance_due_changed exactly as
    update_card/record_payment already do."""
    user, card = _make_card(
        db_session, statement_day=28, due_day=25,
        next_payment_date=date(2026, 9, 25), balance_due=Decimal("6945.00"),
        payment_sent_pending_sync=True, payment_sent_amount=Decimal("6945.00"),
    )
    _credit(db_session, card, user.id, amount=Decimal("-6945.00"), on=date(2026, 9, 25))
    db_session.commit()

    cleared = reconcile_statement_payment(db_session, card, date(2026, 9, 30))

    assert cleared is True
    db_session.refresh(card)
    assert card.payment_sent_pending_sync is False
    assert card.payment_sent_amount is None


def test_reconcile_all_cards_returns_names_of_cleared_cards(db_session):
    user = models.User(username="multi", hashed_password="x", display_name="the user")
    db_session.add(user)
    db_session.flush()
    paid = models.CreditCard(
        user_id=user.id, name="Paid Off Card", credit_limit=Decimal("5000"),
        statement_day=28, due_day=25, current_balance=Decimal("0"),
        balance_due=Decimal("500.00"), next_payment_date=date(2026, 9, 25),
        is_active=True,
    )
    unpaid = models.CreditCard(
        user_id=user.id, name="Still Owed Card", credit_limit=Decimal("5000"),
        statement_day=28, due_day=25, current_balance=Decimal("0"),
        balance_due=Decimal("500.00"), next_payment_date=date(2026, 9, 25),
        is_active=True,
    )
    db_session.add_all([paid, unpaid])
    db_session.flush()
    _credit(db_session, paid, user.id, amount=Decimal("-500.00"), on=date(2026, 9, 10))
    db_session.commit()

    cleared_names = reconcile_all_cards(db_session, date(2026, 9, 30))

    assert cleared_names == ["Paid Off Card"]
    db_session.refresh(paid)
    db_session.refresh(unpaid)
    assert paid.balance_due == Decimal("0")
    assert unpaid.balance_due == Decimal("500.00")


# ── statement_stale_reason ────────────────────────────────────────────────────

@pytest.mark.parametrize("next_payment,balance_due,current,as_of,expected", [
    pytest.param(date(2026, 9, 25), "6945.00", "0.00", date(2026, 9, 20), "balance_below_statement", id="balance_below_statement"),
    pytest.param(date(2026, 9, 25), "500.00", "5000.00", date(2026, 9, 30), "due_date_passed", id="due_date_passed"),
    pytest.param(date(2026, 10, 25), "500.00", "5000.00", date(2026, 9, 20), None, id="healthy"),
    pytest.param(date(2026, 8, 25), "0", "100.00", date(2026, 9, 20), None, id="nothing_due"),
])
def test_stale_reason(db_session, next_payment, balance_due, current, as_of, expected):
    user, card = _make_card(
        db_session, statement_day=28, due_day=25,
        next_payment_date=next_payment, balance_due=Decimal(balance_due),
        current_balance=Decimal(current), pending_charges=Decimal("0"),
    )
    assert statement_stale_reason(card, as_of) == expected


# ── budget_snapshot's Left to Spend note ──────────────────────────────────────

def test_left_to_spend_note_flags_a_stale_card_with_no_digits(db_session):
    """When a card is stale, its Left to Spend card child swaps the usual
    formula-shape note for the stale-statement warning -- still digit-free,
    since ExplainChild.note renders unmasked on the frontend."""
    user, card = _make_card(
        db_session, statement_day=28, due_day=25,
        next_payment_date=date(2026, 9, 25), balance_due=Decimal("6945.00"),
        current_balance=Decimal("0.00"), pending_charges=Decimal("0"),
    )
    checking = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("1000.00"),
    )
    db_session.add(checking)
    db_session.commit()

    with patch(
        "backend.services.budget_snapshot.build_forecast",
        return_value=_fake_quarter_min("1000.00", date(2026, 9, 25)),
    ):
        snap = compute_budget_snapshot(db_session, user, checking.id, as_of=date(2026, 9, 20))

    card_row = next(r for r in snap.explain["left_to_spend"].rows if r.label == "New card spending")
    child = next(c for c in card_row.children if c.label == card.name)
    assert child.note == "statement looks stale, update it on Credit Cards"
    assert not any(ch.isdigit() for ch in child.note)


# ── bank sync wiring ──────────────────────────────────────────────────────────

def _make_card_connection(db, username="danreconcile"):
    user = models.User(username=username, hashed_password="x", display_name="the user")
    db.add(user)
    db.flush()
    card = models.CreditCard(
        user_id=user.id, name="Visa", credit_limit=Decimal("5000.00"),
        statement_day=28, due_day=25, current_balance=Decimal("0.00"),
        balance_due=Decimal("500.00"), next_payment_date=date(2026, 9, 25),
    )
    db.add(card)
    db.flush()
    connection = models.BankConnection(user_id=user.id, access_url_encrypted="ciphertext")
    db.add(connection)
    db.flush()
    link = models.BankConnectionAccountLink(
        connection_id=connection.id, simplefin_account_id="card-1",
        simplefin_account_name="Visa", local_credit_card_id=card.id,
    )
    db.add(link)
    db.commit()
    return user, card, connection, link


def test_bank_sync_calls_reconcile_after_a_card_sync(db_session, monkeypatch):
    """Wiring: a card sync that brings in real activity should attempt
    reconciliation. A full-coverage payment already sitting in
    CreditCardTransaction history (from a prior import) clears balance_due
    as a side effect of this sync."""
    _enable_sync_auto_clear(monkeypatch)
    # The sync reconciles against the real date.today(), so the card's dates
    # are relative to it (v1 hard-coded 9/25, which rule 2 would start
    # refusing as stale once the real clock passed late October).
    from datetime import timedelta
    from backend.services.forecast_engine import _next_occurrence_on_or_after
    user, card, connection, link = _make_card_connection(db_session)
    today = date.today()
    npd = today + timedelta(days=3)
    card.next_payment_date = npd
    card.due_day = npd.day
    card.statement_day = (today - timedelta(days=20)).day
    db_session.add(models.CreditCardTransaction(
        card_id=card.id, user_id=user.id, date=today - timedelta(days=5),
        amount=Decimal("-500.00"), merchant="Payment",
    ))
    db_session.commit()

    txns = [SimpleFinTransaction(id="c1", posted=datetime.combine(today, datetime.min.time()), amount=Decimal("-4.50"), description="Starbucks")]
    with patch("backend.services.bank_sync_service.decrypt", return_value="https://access.url"), \
         patch("backend.services.bank_sync_service.fetch_transactions", return_value=(txns, Decimal("4.50"), None)):
        sync_connection(db_session, connection)

    db_session.refresh(card)
    # The $500 statement is fully covered by the $500 credit already on record.
    assert card.balance_due == Decimal("0")
    assert card.next_payment_date == _next_occurrence_on_or_after(npd.day, npd + timedelta(days=1))


def test_bank_sync_survives_a_reconcile_failure(db_session, monkeypatch):
    """A reconcile_statement_payment exception must be logged and swallowed
    -- it must never fail the sync it rides along with."""
    _enable_sync_auto_clear(monkeypatch)
    user, card, connection, link = _make_card_connection(db_session)
    txns = [SimpleFinTransaction(id="c1", posted=datetime(2026, 9, 11), amount=Decimal("-4.50"), description="Starbucks")]

    with patch("backend.services.bank_sync_service.decrypt", return_value="https://access.url"), \
         patch("backend.services.bank_sync_service.fetch_transactions", return_value=(txns, Decimal("4.50"), None)), \
         patch("backend.services.bank_sync_service.reconcile_statement_payment", side_effect=RuntimeError("boom")):
        imported, skipped = sync_connection(db_session, connection)

    assert imported == 1  # the sync itself still completed
    db_session.refresh(connection)
    assert connection.status == models.BankConnectionStatus.active
    db_session.refresh(card)
    assert card.balance_due == Decimal("500.00")  # unreconciled, but untouched/intact


# ── v2 rules ──────────────────────────────────────────────────────────────────
# v1 counted every credit after the statement close. That double-counts a
# payment already reflected in a hand-entered (or record_payment-reduced)
# balance_due, and can wipe a freshly re-entered statement using the
# previous statement's late-posting payment. v2 only counts credits dated
# after the day the statement was last entered, refuses stale due dates, and keeps
# the advanced due date from landing in the past.

from datetime import timedelta
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from backend.dependencies import get_db, get_current_user
from backend.routers import credit_cards as credit_cards_router_module
from backend.services.forecast_engine import _next_occurrence_on_or_after


def test_chase_live_case_with_freshness_stamp_still_clears(db_session):
    """Statement entered 9/02; refund 9/04 and autopay 9/25 both land after
    that day, so they still prove full payment."""
    user, card = _make_card(
        db_session, statement_day=28, due_day=25,
        next_payment_date=date(2026, 9, 25), balance_due=Decimal("6945.00"),
        balance_due_updated_at=datetime(2026, 9, 2, 14, 0),
    )
    _credit(db_session, card, user.id, amount=Decimal("-45.00"), on=date(2026, 9, 4))
    _credit(db_session, card, user.id, amount=Decimal("-6900.00"), on=date(2026, 9, 25))
    db_session.commit()

    assert reconcile_statement_payment(db_session, card, date(2026, 9, 30)) is True
    db_session.refresh(card)
    assert card.balance_due == Decimal("0")
    assert card.next_payment_date == date(2026, 10, 25)


def test_stale_due_date_never_clears_even_with_ample_credits(db_session):
    """Rule 2: a due date more than 35 days in the past (live: Apple Card at
    5/25) is not trustworthy enough to reconcile against."""
    user, card = _make_card(
        db_session, statement_day=28, due_day=25,
        next_payment_date=date(2026, 5, 25), balance_due=Decimal("287.00"),
    )
    _credit(db_session, card, user.id, amount=Decimal("-5000.00"), on=date(2026, 5, 10))
    _credit(db_session, card, user.id, amount=Decimal("-5000.00"), on=date(2026, 9, 10))
    db_session.commit()

    assert reconcile_statement_payment(db_session, card, date(2026, 9, 30)) is False
    db_session.refresh(card)
    assert card.balance_due == Decimal("287.00")
    assert card.next_payment_date == date(2026, 5, 25)
    assert card.balance_due_updated_at is None


def test_due_date_exactly_35_days_back_is_still_allowed(db_session):
    user, card = _make_card(
        db_session, statement_day=28, due_day=26,
        next_payment_date=date(2026, 8, 26), balance_due=Decimal("500.00"),
    )
    _credit(db_session, card, user.id, amount=Decimal("-500.00"), on=date(2026, 8, 20))
    db_session.commit()

    assert reconcile_statement_payment(db_session, card, date(2026, 9, 30)) is True


def test_missing_next_payment_date_never_clears(db_session):
    """Rule 2: with no due date there's no statement to anchor to."""
    user, card = _make_card(
        db_session, statement_day=28, due_day=25,
        next_payment_date=None, balance_due=Decimal("500.00"),
    )
    _credit(db_session, card, user.id, amount=Decimal("-500.00"), on=date(2026, 9, 29))
    db_session.commit()

    assert reconcile_statement_payment(db_session, card, date(2026, 9, 30)) is False
    db_session.refresh(card)
    assert card.balance_due == Decimal("500.00")
    assert card.next_payment_date is None


def test_advanced_due_date_never_lands_in_the_past(db_session):
    """Rule 3: old due 8/25, today 9/28. The next 25th after 8/25 is 9/25,
    already past, so it rolls to the next 25th on/after today."""
    user, card = _make_card(
        db_session, statement_day=28, due_day=25,
        next_payment_date=date(2026, 8, 25), balance_due=Decimal("500.00"),
    )
    _credit(db_session, card, user.id, amount=Decimal("-500.00"), on=date(2026, 8, 20))
    db_session.commit()

    assert reconcile_statement_payment(db_session, card, date(2026, 9, 28)) is True
    db_session.refresh(card)
    assert card.next_payment_date == date(2026, 10, 25)


@pytest.fixture()
def cards_client(db_session):
    user = models.User(username="dan", hashed_password="x", display_name="the user")
    db_session.add(user)
    db_session.commit()
    app = FastAPI()
    app.include_router(credit_cards_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app), user


def test_c1_reentered_statement_is_not_cleared_by_the_previous_payment(cards_client, db_session):
    """Reviewer C1. Statement A ($500, due 9/25, closed 8/28) is paid by a
    credit that posts late on 9/29 -- after the NEXT close (9/28). It clears
    A. the user then enters statement B ($450) via update_card. v1 counted the
    9/29 credit again against B's window (> 9/28) and wiped B. It must not."""
    client, user = cards_client
    card = models.CreditCard(
        user_id=user.id, name="Visa", credit_limit=Decimal("5000"),
        statement_day=28, due_day=25, current_balance=Decimal("450.00"),
        balance_due=Decimal("500.00"), next_payment_date=date(2026, 9, 25),
    )
    db_session.add(card)
    db_session.flush()
    _credit(db_session, card, user.id, amount=Decimal("-500.00"), on=date(2026, 9, 29))
    db_session.commit()

    assert reconcile_statement_payment(db_session, card, date(2026, 9, 30)) is True
    db_session.commit()
    db_session.refresh(card)
    assert card.next_payment_date == date(2026, 10, 25)

    resp = client.patch(f"/credit-cards/{card.id}", json={"balance_due": "450.00"})
    assert resp.status_code == 200

    assert reconcile_statement_payment(db_session, card, date(2026, 10, 2)) is False
    db_session.refresh(card)
    assert card.balance_due == Decimal("450.00")


def _card_sync_fixture(db, user, card):
    connection = models.BankConnection(user_id=user.id, access_url_encrypted="ciphertext")
    db.add(connection)
    db.flush()
    db.add(models.BankConnectionAccountLink(
        connection_id=connection.id, simplefin_account_id="card-1",
        simplefin_account_name="Visa", local_credit_card_id=card.id,
    ))
    db.commit()
    return connection


def test_c2_record_payment_then_synced_copy_does_not_clear_the_remainder(cards_client, db_session, monkeypatch):
    """Reviewer C2. A manual record_payment reduces balance_due; the bank
    later syncs the same payment in as a card credit. That credit is already
    reflected in the reduced balance_due, so it must not clear the rest.
    Dates are relative to the real clock because record_payment stamps
    utcnow() and the sync reconciles against date.today()."""
    _enable_sync_auto_clear(monkeypatch)
    client, user = cards_client
    today = date.today()
    npd = today + timedelta(days=5)
    checking = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("5000.00"),
    )
    card = models.CreditCard(
        user_id=user.id, name="Visa", credit_limit=Decimal("5000"),
        statement_day=(today - timedelta(days=15)).day, due_day=npd.day,
        current_balance=Decimal("1000.00"), balance_due=Decimal("1000.00"),
        next_payment_date=npd,
    )
    db_session.add_all([checking, card])
    db_session.commit()
    connection = _card_sync_fixture(db_session, user, card)

    paid_on = today - timedelta(days=1)
    resp = client.post(f"/credit-cards/{card.id}/payment", json={
        "checking_account_id": checking.id, "amount": "600.00", "date": paid_on.isoformat(),
    })
    assert resp.status_code == 201
    db_session.refresh(card)
    assert card.balance_due == Decimal("400.00")

    # SimpleFIN reports a card credit as a positive amount.
    txns = [SimpleFinTransaction(
        id="pay-1", posted=datetime.combine(paid_on, datetime.min.time()),
        amount=Decimal("600.00"), description="PAYMENT THANK YOU",
    )]
    with patch("backend.services.bank_sync_service.decrypt", return_value="https://access.url"), \
         patch("backend.services.bank_sync_service.fetch_transactions", return_value=(txns, Decimal("-400.00"), None)):
        imported, _ = sync_connection(db_session, connection)

    assert imported == 1
    db_session.refresh(card)
    assert card.balance_due == Decimal("400.00")
    assert card.next_payment_date == npd


def test_reconcile_db_failure_rolls_back_only_the_reconcile(db_session, monkeypatch):
    """Rule 4. A DB-level failure inside reconcile (here a failed flush,
    which on its own would leave the session needing a rollback) must roll
    back only the reconcile's writes. The sync's imported transaction,
    current_balance and last_synced_at still commit."""
    _enable_sync_auto_clear(monkeypatch)
    user, card, connection, link = _make_card_connection(db_session, username="danisolate")

    def _failing_reconcile(db, c, today):
        c.balance_due = Decimal("0")
        c.name = None  # NOT NULL -> IntegrityError on flush
        db.flush()

    txns = [SimpleFinTransaction(id="c1", posted=datetime(2026, 9, 11), amount=Decimal("-4.50"), description="Coffee")]
    with patch("backend.services.bank_sync_service.decrypt", return_value="https://access.url"), \
         patch("backend.services.bank_sync_service.fetch_transactions", return_value=(txns, Decimal("-1074.64"), None)), \
         patch("backend.services.bank_sync_service.reconcile_statement_payment", side_effect=_failing_reconcile):
        imported, _ = sync_connection(db_session, connection)

    assert imported == 1
    db_session.expire_all()
    connection = db_session.get(models.BankConnection, connection.id)
    assert connection.status == models.BankConnectionStatus.active
    assert connection.last_error is None
    link = db_session.get(models.BankConnectionAccountLink, link.id)
    assert link.last_synced_at is not None
    card = db_session.get(models.CreditCard, card.id)
    assert card.name == "Visa"
    assert card.balance_due == Decimal("500.00")
    assert card.current_balance == Decimal("1074.64")
    assert db_session.query(models.CreditCardTransaction).filter_by(external_id="c1").count() == 1


# ── new_statement_due ─────────────────────────────────────────────────────────

def test_new_statement_due_after_a_close_following_a_clear(db_session):
    user, card = _make_card(
        db_session, statement_day=28, due_day=25,
        next_payment_date=date(2026, 10, 25), balance_due=Decimal("0"),
        balance_due_updated_at=datetime(2026, 9, 26, 9, 0),
        current_balance=Decimal("1200.00"), pending_charges=Decimal("0"),
    )
    assert statement_stale_reason(card, date(2026, 9, 30)) == "new_statement_due"
    # The close hasn't happened yet on 9/27.
    assert statement_stale_reason(card, date(2026, 9, 27)) is None


@pytest.mark.parametrize("pending,expected", [
    pytest.param("40.00", "new_statement_due", id="counts_pending_charges"),
    pytest.param("0", None, id="not_shown_with_nothing_owed"),
])
def test_new_statement_due(db_session, pending, expected):
    user, card = _make_card(
        db_session, statement_day=28, due_day=25,
        next_payment_date=date(2026, 10, 25), balance_due=Decimal("0"),
        balance_due_updated_at=datetime(2026, 9, 26, 9, 0),
        current_balance=Decimal("0"), pending_charges=Decimal(pending),
    )
    assert statement_stale_reason(card, date(2026, 9, 30)) == expected


def test_resaving_unchanged_zero_balance_due_dismisses_new_statement_due(cards_client, db_session):
    client, user = cards_client
    today = date.today()
    card = models.CreditCard(
        user_id=user.id, name="Visa", credit_limit=Decimal("5000"),
        statement_day=(today - timedelta(days=2)).day, due_day=25,
        current_balance=Decimal("1200.00"), balance_due=Decimal("0"),
        balance_due_updated_at=datetime.utcnow() - timedelta(days=5),
    )
    db_session.add(card)
    db_session.commit()

    assert client.get(f"/credit-cards/{card.id}").json()["statement_stale_reason"] == "new_statement_due"

    resp = client.patch(f"/credit-cards/{card.id}", json={"balance_due": "0"})
    assert resp.status_code == 200
    assert resp.json()["statement_stale_reason"] is None


def test_reconcile_db_failure_isolated_when_nothing_else_was_written_first(db_session, monkeypatch):
    """Same as above, but the sync writes nothing before the savepoint opens
    (no new transactions, and a stale card balance feed that's ignored).
    pysqlite only auto-BEGINs before DML, so the SAVEPOINT is the first
    statement of the transaction -- the rollback must still leave the
    connection usable and the sync's own bookkeeping committed."""
    _enable_sync_auto_clear(monkeypatch)
    user, card, connection, link = _make_card_connection(db_session, username="danisolate2")
    card.balance_as_of = datetime(2026, 9, 20)
    db_session.commit()

    def _failing_reconcile(db, c, today):
        c.name = None
        db.flush()

    with patch("backend.services.bank_sync_service.decrypt", return_value="https://access.url"), \
         patch("backend.services.bank_sync_service.fetch_transactions", return_value=([], Decimal("-999.00"), datetime(2026, 9, 1))), \
         patch("backend.services.bank_sync_service.reconcile_statement_payment", side_effect=_failing_reconcile):
        sync_connection(db_session, connection)

    db_session.expire_all()
    assert db_session.get(models.BankConnection, connection.id).status == models.BankConnectionStatus.active
    assert db_session.get(models.BankConnectionAccountLink, link.id).last_synced_at is not None
    card = db_session.get(models.CreditCard, card.id)
    assert card.name == "Visa"
    assert card.current_balance == Decimal("0.00")


def test_c2_same_day_record_payment_and_synced_copy_does_not_clear(cards_client, db_session):
    """C2 on a single day: record_payment of $600 today against $1000 leaves
    $400; the bank's copy of that $600 is also dated today. It's already in
    the $400, so reconcile must not clear. Uses the UTC date for "today"
    because that's the date record_payment's utcnow() stamp carries."""
    client, user = cards_client
    today = datetime.utcnow().date()
    npd = today + timedelta(days=5)
    checking = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("5000.00"),
    )
    card = models.CreditCard(
        user_id=user.id, name="Visa", credit_limit=Decimal("5000"),
        statement_day=(today - timedelta(days=15)).day, due_day=npd.day,
        current_balance=Decimal("1000.00"), balance_due=Decimal("1000.00"),
        next_payment_date=npd,
    )
    db_session.add_all([checking, card])
    db_session.commit()

    resp = client.post(f"/credit-cards/{card.id}/payment", json={
        "checking_account_id": checking.id, "amount": "600.00", "date": today.isoformat(),
    })
    assert resp.status_code == 201
    _credit(db_session, card, user.id, amount=Decimal("-600.00"), on=today)
    db_session.commit()

    assert reconcile_statement_payment(db_session, card, today) is False
    db_session.refresh(card)
    assert card.balance_due == Decimal("400.00")


def test_sync_hook_is_off_by_default_and_never_clears(db_session):
    """Shipped state: AUTO_CLEAR_STATEMENTS_IN_SYNC is False until the
    posting-lag case (a manual partial payment whose bank copy posts a day
    later) is closed, so a sync must leave balance_due alone even when credits
    on file would fully cover it."""
    from datetime import timedelta
    from backend.services import bank_sync_service
    assert bank_sync_service.AUTO_CLEAR_STATEMENTS_IN_SYNC is False
    user, card, connection, link = _make_card_connection(db_session)
    today = date.today()
    npd = today + timedelta(days=3)
    card.next_payment_date = npd
    card.due_day = npd.day
    card.statement_day = (today - timedelta(days=20)).day
    db_session.add(models.CreditCardTransaction(
        card_id=card.id, user_id=user.id, date=today - timedelta(days=5),
        amount=Decimal("-500.00"), merchant="Payment",
    ))
    db_session.commit()
    before = card.balance_due

    txns = [SimpleFinTransaction(id="c1", posted=datetime.combine(today, datetime.min.time()), amount=Decimal("-4.50"), description="Starbucks")]
    with patch("backend.services.bank_sync_service.decrypt", return_value="https://access.url"), \
         patch("backend.services.bank_sync_service.fetch_transactions", return_value=(txns, Decimal("4.50"), None)):
        sync_connection(db_session, connection)

    db_session.refresh(card)
    assert before > 0
    assert card.balance_due == before
