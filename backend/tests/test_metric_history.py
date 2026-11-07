"""The headline-metric collector behind change history (services/metric_history.py).

Reuses test_parity_headline's invented fixture. "Today" is pinned to 2026-11-02.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal

from backend import models
from backend.services.available_to_spend import available_to_spend
from backend.services.budget_snapshot import _cc_basis_note, compute_budget_snapshot
from backend.services.card_payment_model import card_payments
from backend.services.explain import replay
from backend.services.metric_history import (
    METRIC_KEYS,
    collect_headline_metrics,
    collect_sources,
    latest_snapshot,
    prune_history,
    record_for_users,
    record_if_calc_changed,
    record_snapshot,
)
from backend.services import metric_history
from backend.services.calc_version import CALC_VERSION
from backend.services.month_summary import build_month_summary
from backend.services.pending import checking_balance_with_pending
from backend.tests.test_parity_headline import TODAY, _headline_fixture, _pin_today, _seed

D = Decimal


def _by_key(readings):
    return {r.key: r for r in readings}


def test_collect_returns_every_headline_in_order(db_session, monkeypatch):
    _pin_today(monkeypatch, TODAY)
    user, _checking = _headline_fixture(db_session)
    readings = collect_headline_metrics(db_session, user, TODAY)
    cards = db_session.query(models.CreditCard).order_by(models.CreditCard.id).all()
    assert [r.key for r in readings] == list(METRIC_KEYS) + [f"card_payment:{c.id}" for c in cards]
    assert METRIC_KEYS == (
        "leftover", "left_to_spend", "spendable_week", "spendable_today",
        "safety_margin", "safety_margin_week", "safety_margin_today", "next_month_minimum",
        "lookahead_minimum", "available_to_spend", "checking_balance",
    )


def test_every_reading_replays_to_its_value(db_session, monkeypatch):
    _pin_today(monkeypatch, TODAY)
    user, _checking = _headline_fixture(db_session)
    readings = collect_headline_metrics(db_session, user, TODAY)
    assert readings
    for r in readings:
        assert replay(r.explain) == r.value, r.key
        assert r.explain.result == r.value, r.key


def test_readings_equal_their_surfaces(db_session, monkeypatch):
    _pin_today(monkeypatch, TODAY)
    user, checking = _headline_fixture(db_session)
    got = _by_key(collect_headline_metrics(db_session, user, TODAY))
    snap = compute_budget_snapshot(db_session, user, checking.id, as_of=TODAY)

    assert got["leftover"].value == build_month_summary(db_session, user.id, 2026, 11).left_over
    assert got["leftover"].value == snap.leftover
    assert got["left_to_spend"].value == snap.left_to_spend
    assert got["spendable_week"].value == snap.left_to_spend_weekly
    assert got["spendable_today"].value == snap.spendable_today
    # Each pair differs, so a swapped field would fail above.
    for a, b in (("spendable_week", "spendable_today"), ("safety_margin_week", "safety_margin_today"),
                 ("lookahead_minimum", "next_month_minimum")):
        assert got[a].value != got[b].value, (a, b)
    assert got["safety_margin"].value == snap.safety_margin
    assert got["safety_margin_week"].value == snap.safety_margin_weekly
    assert got["safety_margin_today"].value == snap.safety_margin_today
    assert got["lookahead_minimum"].value == snap.lookahead_minimum
    assert got["next_month_minimum"].value == snap.next_month_minimum
    assert got["available_to_spend"].value == available_to_spend(db_session, user, TODAY).available
    assert got["checking_balance"].value == checking_balance_with_pending(db_session, checking, TODAY)
    visa = db_session.query(models.CreditCard).filter_by(name="Test Visa").one()
    mc = db_session.query(models.CreditCard).filter_by(name="Test Mastercard").one()
    assert got[f"card_payment:{visa.id}"].value == D("400.00")
    assert got[f"card_payment:{mc.id}"].value == D("250.00")


def test_card_payment_reading_names_due_date_and_basis(db_session, monkeypatch):
    _pin_today(monkeypatch, TODAY)
    user, checking = _headline_fixture(db_session)
    got = _by_key(collect_headline_metrics(db_session, user, TODAY))
    visa = db_session.query(models.CreditCard).filter_by(name="Test Visa").one()
    reading = got[f"card_payment:{visa.id}"]
    assert reading.label == "Test Visa next payment"
    rows = reading.explain.rows
    assert rows[0].label == "Next payment, due Nov 5"
    payment = min(
        (p for p in card_payments(
            db_session, user, checking, TODAY, date(2027, 1, 16),
            include_unbilled_card_bills=True, today=TODAY) if p.card_id == visa.id),
        key=lambda p: p.due,
    )
    assert rows[0].note == _cc_basis_note(payment)


def test_inactive_card_has_no_reading(db_session, monkeypatch):
    _pin_today(monkeypatch, TODAY)
    user, _checking = _headline_fixture(db_session)
    mc = db_session.query(models.CreditCard).filter_by(name="Test Mastercard").one()
    mc.is_active = False
    db_session.commit()
    keys = [r.key for r in collect_headline_metrics(db_session, user, TODAY)]
    assert f"card_payment:{mc.id}" not in keys
    assert len([k for k in keys if k.startswith("card_payment:")]) == 1


def test_no_primary_checking_collects_nothing(db_session):
    user = models.User(username="nochecking", hashed_password="x", display_name="No Checking")
    db_session.add(user)
    db_session.commit()
    assert collect_headline_metrics(db_session, user, TODAY) == []


def test_sources_list_pending_rows_and_high_water_ids(db_session, monkeypatch):
    _pin_today(monkeypatch, TODAY)
    user, _checking = _headline_fixture(db_session)
    visa = db_session.query(models.CreditCard).filter_by(name="Test Visa").one()
    empty = collect_sources(db_session, user, TODAY)
    assert empty["card_pending"] == []
    assert empty["checking_pending"] == []
    assert empty["max_card_txn_id"] == 0

    db_session.add(models.CardPendingTransaction(
        user_id=user.id, card_id=visa.id, external_id="p-1", date=TODAY,
        amount=D("250.00"), merchant="Example Insurance Co.", synced_at=datetime(2026, 11, 2, 8, 0),
    ))
    db_session.commit()
    sources = collect_sources(db_session, user, TODAY)
    assert sources["card_pending"] == [{
        "card_id": visa.id, "card": "Test Visa", "external_id": "p-1",
        "merchant": "Example Insurance Co.", "amount": "250.00",
    }]
    assert sources["checking_pending"] == []  # no live Plaid link

    txn = models.Transaction(
        user_id=user.id, account_id=_checking.id, date=TODAY, amount=D("-12.00"),
        description="Example Cafe", is_actual=True,
    )
    planned = models.Transaction(
        user_id=user.id, account_id=_checking.id, date=TODAY, amount=D("-5.00"),
        description="Planned thing", is_actual=False,
    )
    ctxn = models.CreditCardTransaction(
        card_id=visa.id, user_id=user.id, date=TODAY, amount=D("9.00"), merchant="Example Shop",
        source=models.CardTransactionSource.bank_sync,
    )
    db_session.add_all([txn, ctxn])
    db_session.commit()
    db_session.add(planned)
    db_session.commit()
    sources = collect_sources(db_session, user, TODAY)
    assert sources["max_txn_id"] == txn.id  # the planned row is newer but not actual
    assert sources["max_card_txn_id"] == ctxn.id
    assert planned.id > txn.id


def test_next_month_minimum_explain_is_static_and_replays(db_session, monkeypatch):
    _pin_today(monkeypatch, TODAY)
    user, checking = _headline_fixture(db_session)
    snap = compute_budget_snapshot(db_session, user, checking.id, as_of=TODAY)
    ex = snap.explain["next_month_minimum"]
    assert ex.title.startswith("Lowest point in ")
    assert replay(ex) == snap.next_month_minimum
    assert ex.rows[0].note.startswith("Lowest projected checking balance next month")
    assert "$" not in ex.rows[0].note


def test_checking_balance_with_live_pending_rows(db_session, monkeypatch):
    _pin_today(monkeypatch, TODAY)
    user, checking = _headline_fixture(db_session)
    conn = models.BankConnection(
        user_id=user.id, provider="plaid", access_url_encrypted="tok", plaid_item_id="item-1",
    )
    db_session.add(conn)
    db_session.flush()
    db_session.add(models.BankConnectionAccountLink(
        connection_id=conn.id, simplefin_account_id="a-1", simplefin_account_name="Checking",
        local_account_id=checking.id, is_active=True,
    ))
    db_session.add_all([
        models.AccountPendingTransaction(
            user_id=user.id, account_id=checking.id, external_id="c-1", date=TODAY,
            amount=D("40.00"), description="Example Deposit", synced_at=datetime(2026, 11, 2, 8, 0),
        ),
        models.AccountPendingTransaction(
            user_id=user.id, account_id=checking.id, external_id="d-1", date=TODAY,
            amount=D("-15.50"), description="Example Market", synced_at=datetime(2026, 11, 2, 8, 0),
        ),
    ])
    db_session.commit()

    reading = _by_key(collect_headline_metrics(db_session, user, TODAY))["checking_balance"]
    assert reading.value == checking_balance_with_pending(db_session, checking, TODAY)
    assert reading.value == D("3000.00") + D("24.50")
    assert replay(reading.explain) == reading.value
    pending_row = reading.explain.rows[1]
    assert pending_row.label == "Pending"
    assert pending_row.amount == D("24.50")
    assert {(c.label, c.amount) for c in pending_row.children} == {
        ("Example Deposit", D("40.00")), ("Example Market", D("-15.50")),
    }
    sources = collect_sources(db_session, user, TODAY)
    assert sorted(sources["checking_pending"], key=lambda e: e["external_id"]) == [
        {"account_id": checking.id, "account": checking.name, "external_id": "c-1",
         "description": "Example Deposit", "amount": "40.00"},
        {"account_id": checking.id, "account": checking.name, "external_id": "d-1",
         "description": "Example Market", "amount": "-15.50"},
    ]


NOW = datetime(2026, 11, 2, 12, 0)


def _count(db):
    return db.query(models.MetricSnapshot).count()


def test_record_stores_every_reading(db_session, monkeypatch):
    _pin_today(monkeypatch, TODAY)
    user, _ = _headline_fixture(db_session)
    snap = record_snapshot(db_session, user, "sync", as_of=TODAY, now=NOW)
    assert snap is not None
    assert snap.calc_version == CALC_VERSION
    assert snap.trigger == "sync"
    assert len(snap.readings) == len(collect_headline_metrics(db_session, user, TODAY))
    assert _count(db_session) == 1


def test_identical_sync_is_not_stored_twice(db_session, monkeypatch):
    _pin_today(monkeypatch, TODAY)
    user, _ = _headline_fixture(db_session)
    assert record_snapshot(db_session, user, "sync", as_of=TODAY, now=NOW) is not None
    assert record_snapshot(db_session, user, "sync", as_of=TODAY, now=NOW) is None
    assert _count(db_session) == 1


def test_email_is_always_stored(db_session, monkeypatch):
    _pin_today(monkeypatch, TODAY)
    user, _ = _headline_fixture(db_session)
    record_snapshot(db_session, user, "sync", as_of=TODAY, now=NOW)
    assert record_snapshot(db_session, user, "email", as_of=TODAY, now=NOW) is not None
    assert _count(db_session) == 2


def test_changed_pending_is_stored(db_session, monkeypatch):
    _pin_today(monkeypatch, TODAY)
    user, _ = _headline_fixture(db_session)
    visa = db_session.query(models.CreditCard).order_by(models.CreditCard.id).first()
    record_snapshot(db_session, user, "sync", as_of=TODAY, now=NOW)
    db_session.add(models.CardPendingTransaction(
        user_id=user.id, card_id=visa.id, external_id="p-9", date=TODAY,
        amount=D("12.00"), merchant="Example Cafe", synced_at=datetime(2026, 11, 2, 8, 0),
    ))
    db_session.commit()
    assert record_snapshot(db_session, user, "sync", as_of=TODAY, now=NOW) is not None
    assert _count(db_session) == 2


def test_prune_keeps_thirteen_months(db_session, monkeypatch):
    _pin_today(monkeypatch, TODAY)
    user, _ = _headline_fixture(db_session)
    readings = collect_headline_metrics(db_session, user, TODAY)
    record_snapshot(db_session, user, "email", as_of=TODAY, now=NOW - timedelta(days=397), readings=readings)
    keep = record_snapshot(db_session, user, "email", as_of=TODAY, now=NOW - timedelta(days=395), readings=readings)
    assert prune_history(db_session, NOW) == 1
    rows = db_session.query(models.MetricSnapshot).all()
    assert [r.id for r in rows] == [keep.id]
    assert db_session.query(models.MetricReading).count() == len(readings)


def test_record_for_users_never_raises(db_session, monkeypatch, caplog):
    _pin_today(monkeypatch, TODAY)
    first, _ = _headline_fixture(db_session)
    second, _ = _seed(db_session, "other", remaining=D("0"))
    db_session.commit()  # the first user's failure rolls back, so the second must be committed
    real = metric_history.collect_headline_metrics

    def flaky(db, user, as_of):
        if user.id == first.id:
            raise RuntimeError("collector down")
        return real(db, user, as_of)

    monkeypatch.setattr(metric_history, "collect_headline_metrics", flaky)
    with caplog.at_level("ERROR"):
        record_for_users(db_session, [first.id, second.id], "sync")
    stored = db_session.query(models.MetricSnapshot).all()
    assert [s.user_id for s in stored] == [second.id]
    assert f"user {first.id}" in caplog.text


def test_user_without_checking_records_nothing(db_session):
    user = models.User(username="nochecking", hashed_password="x", display_name="NC")
    db_session.add(user)
    db_session.commit()
    assert record_snapshot(db_session, user, "sync", as_of=TODAY, now=NOW) is None
    assert _count(db_session) == 0


def test_calc_change_records_once(db_session, monkeypatch):
    _pin_today(monkeypatch, TODAY)
    user, _ = _headline_fixture(db_session)
    snap = record_snapshot(db_session, user, "sync", as_of=TODAY, now=NOW)
    snap.calc_version = CALC_VERSION - 1
    db_session.commit()
    record_if_calc_changed(db_session)
    assert latest_snapshot(db_session, user.id).trigger == "calc_change"
    assert _count(db_session) == 2
    record_if_calc_changed(db_session)
    assert _count(db_session) == 2


def test_calc_change_skips_user_without_snapshots(db_session, monkeypatch):
    _pin_today(monkeypatch, TODAY)
    _headline_fixture(db_session)
    record_if_calc_changed(db_session)
    assert _count(db_session) == 0


def test_sync_all_records_after_settling(db_session, monkeypatch):
    from backend.services import bank_sync_service
    calls = []
    monkeypatch.setattr(bank_sync_service, "settle_after_sync", lambda db, ids: calls.append("settle"))
    monkeypatch.setattr(
        bank_sync_service, "record_for_users",
        lambda db, ids, trigger: calls.append(("record", trigger)),
    )
    bank_sync_service.sync_all(db_session)
    assert calls == ["settle", ("record", "sync")]
