"""Plain-language causes for a change between two readings (services/metric_diff.py).

Snapshots are built by hand with invented figures; no live data.
"""
import json
from datetime import date, datetime
from decimal import Decimal

from backend import models, schemas
from backend.services.metric_diff import (
    Cause,
    LineChange,
    diff_explanations,
    explain_change,
    signed_money,
    summarize,
)

D = Decimal


def _ex(*rows, title="Example"):
    return schemas.Explanation(title=title, result=D("0"), rows=list(rows))


def _row(op, label, amount, children=(), info=()):
    return schemas.ExplainRow(
        op=op, label=label, amount=D(amount),
        children=[schemas.ExplainChild(label=l, amount=D(a)) for l, a in children],
        informational_children=[schemas.ExplainChild(label=l, amount=D(a)) for l, a in info],
    )


def _sources(card_pending=(), checking_pending=(), max_txn=0, max_card_txn=0):
    return {
        "card_pending": list(card_pending), "checking_pending": list(checking_pending),
        "max_txn_id": max_txn, "max_card_txn_id": max_card_txn,
    }


def _pend(card_id, card, ext, merchant, amount):
    return {"card_id": card_id, "card": card, "external_id": ext, "merchant": merchant, "amount": amount}


def _world(db):
    user = models.User(username="diffuser", hashed_password="x", display_name="Diff User")
    db.add(user)
    db.flush()
    checking = models.Account(
        user_id=user.id, name="Example Checking", type=models.AccountType.checking,
        current_balance=D("1000.00"),
    )
    db.add(checking)
    cards = []
    for name in ("Visa", "Mastercard"):
        card = models.CreditCard(
            user_id=user.id, name=name, credit_limit=D("5000.00"), statement_day=20, due_day=10,
            is_active=True, current_balance=D("0"), balance_due=D("0"),
        )
        db.add(card)
        cards.append(card)
    db.commit()
    return user, checking, cards[0], cards[1]


def _snap(db, user, *, as_of=date(2026, 11, 2), calc_version=12, sources=None, readings=None):
    snap = models.MetricSnapshot(
        user_id=user.id, taken_at=datetime(2026, 11, 2, 7, 0), trigger="sync",
        calc_version=calc_version, as_of=as_of,
        sources_json=json.dumps(sources or _sources(), sort_keys=True),
    )
    snap.readings = [
        models.MetricReading(
            metric_key=key, label=key, value=D(value), explain_json=explain.model_dump_json(),
        )
        for key, (value, explain) in (readings or {}).items()
    ]
    db.add(snap)
    db.commit()
    return snap


def _pair(db, user, key, *, prev_kw=None, cur_kw=None, prev_val="100.00", cur_val="100.00",
          prev_ex=None, cur_ex=None):
    flat = _ex(_row("start", "Base", "100.00"))
    prev = _snap(db, user, readings={key: (prev_val, prev_ex or flat)}, **(prev_kw or {}))
    cur = _snap(db, user, readings={key: (cur_val, cur_ex or flat)}, **(cur_kw or {}))
    return prev.readings[0], cur.readings[0]


def _causes(db, user, key, prev, cur):
    return explain_change(db, user.id, key, prev, cur)


def test_signed_money_uses_real_minus():
    assert signed_money(D("50")) == "+$50.00"
    assert signed_money(D("-400")) == "−$400.00"
    assert signed_money(D("-1234.5")) == "−1,234.50"[:1] + "$1,234.50"


def test_spec_example_reads_exactly(db_session):
    user, _chk, visa, _mc = _world(db_session)
    items = [("p1", "Example Insurance Co.", "250.00"), ("p2", "Grocery Store", "100.00"),
             ("p3", "Online Shop", "50.00")]
    prev, cur = _pair(
        db_session, user, "safety_margin",
        cur_kw={"sources": _sources(card_pending=[_pend(visa.id, "Visa", *i) for i in items])},
        prev_val="500.00", cur_val="100.00",
    )
    causes = _causes(db_session, user, "safety_margin", prev, cur)
    assert summarize("Safety Margin", D("-400.00"), "since 7:00 AM", causes, max_items=3) == (
        "Safety Margin −$400.00 since 7:00 AM: new pending Visa charges: "
        "Example Insurance Co. $250.00, Grocery Store $100.00, Online Shop $50.00")


def test_single_item_is_singular(db_session):
    user, _chk, visa, _mc = _world(db_session)
    prev, cur = _pair(
        db_session, user, "left_to_spend",
        cur_kw={"sources": _sources(card_pending=[_pend(visa.id, "Visa", "p1", "Grocery Store", "100.00")])},
    )
    assert [c.text for c in _causes(db_session, user, "left_to_spend", prev, cur)] == [
        "new pending Visa charge: Grocery Store $100.00"]


def test_pending_that_posted_is_not_a_cause(db_session):
    user, _chk, visa, _mc = _world(db_session)
    prev_sources = _sources(card_pending=[_pend(visa.id, "Visa", "p1", "Grocery Store", "100.00")])
    posted = models.CreditCardTransaction(
        card_id=visa.id, user_id=user.id, date=date(2026, 11, 2), amount=D("100.00"),
        merchant="Grocery Store",
    )
    db_session.add(posted)
    db_session.commit()
    cur_sources = _sources(max_card_txn=posted.id)
    prev, cur = _pair(db_session, user, "left_to_spend",
                      prev_kw={"sources": prev_sources}, cur_kw={"sources": cur_sources})
    assert [c.text for c in _causes(db_session, user, "left_to_spend", prev, cur)] == ["inputs changed"]

    # A new pending row that also posted between the snapshots: drop both.
    prev2, cur2 = _pair(
        db_session, user, "left_to_spend",
        prev_kw={"sources": _sources()},
        cur_kw={"sources": _sources(
            card_pending=[_pend(visa.id, "Visa", "p9", "Grocery Store", "100.00")],
            max_card_txn=posted.id)},
    )
    # prev max is 0 here, so the posted row is in range and cancels the new pending row.
    assert [c.text for c in _causes(db_session, user, "left_to_spend", prev2, cur2)] == ["inputs changed"]


def test_unmatched_posted_and_dropped_pending_are_named(db_session):
    user, _chk, visa, _mc = _world(db_session)
    posted = models.CreditCardTransaction(
        card_id=visa.id, user_id=user.id, date=date(2026, 11, 2), amount=D("42.00"),
        merchant="Example Cafe",
    )
    db_session.add(posted)
    db_session.commit()
    prev, cur = _pair(
        db_session, user, "left_to_spend",
        prev_kw={"sources": _sources(card_pending=[_pend(visa.id, "Visa", "p1", "Hotel", "300.00")])},
        cur_kw={"sources": _sources(max_card_txn=posted.id)},
    )
    assert [c.text for c in _causes(db_session, user, "left_to_spend", prev, cur)] == [
        "pending Visa charge dropped: Hotel $300.00",
        "new Visa transaction: Example Cafe $42.00",
    ]


def test_new_month_is_one_cause(db_session):
    user, _chk, visa, _mc = _world(db_session)
    prev, cur = _pair(
        db_session, user, "left_to_spend",
        prev_kw={"as_of": date(2026, 10, 31)}, cur_kw={"as_of": date(2026, 11, 1)},
        prev_ex=_ex(_row("start", "Base", "100.00")), cur_ex=_ex(_row("start", "Base", "900.00")),
    )
    assert [c.text for c in _causes(db_session, user, "left_to_spend", prev, cur)] == ["new month (Nov)"]


def test_calc_change_is_named(db_session):
    user, _chk, _v, _m = _world(db_session)
    prev, cur = _pair(
        db_session, user, "available_to_spend",
        prev_kw={"calc_version": 11}, cur_kw={"calc_version": 12},
    )
    causes = _causes(db_session, user, "available_to_spend", prev, cur)
    assert causes[0].text == (
        "calculation changed (v11 → v12: Available to Spend counts balance-only cards "
        "like Left to Spend)")


def test_child_lines_replace_their_row(db_session):
    user, _chk, _v, _m = _world(db_session)
    old = _ex(_row("start", "Income", "1000.00"),
              _row("subtract", "Bills", "300.00",
                   children=[("Recurring bills this month", "200.00"), ("Rent", "100.00")]))
    new = _ex(_row("start", "Income", "1000.00"),
              _row("subtract", "Bills", "350.00",
                   children=[("Recurring bills this month", "250.00"), ("Rent", "100.00")]),
              _row("result", "Left", "650.00"))
    assert diff_explanations(old, new) == [
        LineChange("Recurring bills this month", D("200.00"), D("250.00"))]
    prev, cur = _pair(db_session, user, "left_to_spend", prev_ex=old, cur_ex=new)
    assert [c.text for c in _causes(db_session, user, "left_to_spend", prev, cur)] == [
        "Recurring bills this month +$50.00"]


def test_rows_added_removed_and_tiny_changes(db_session):
    old = _ex(_row("start", "A", "10.00"), _row("add", "Gone", "5.00"),
              _row("subtract", "Tiny", "1.000"), _row("divide", "Days", "7"))
    new = _ex(_row("start", "A", "70.00"), _row("add", "Fresh", "3.00"),
              _row("subtract", "Tiny", "1.004"), _row("divide", "Days", "8"))
    got = diff_explanations(old, new)
    assert LineChange("A", D("10.00"), D("70.00")) in got
    assert LineChange("Gone", D("5.00"), None) in got
    assert LineChange("Fresh", None, D("3.00")) in got
    assert len(got) == 3


def test_line_changes_order_and_text(db_session):
    user, _chk, _v, _m = _world(db_session)
    old = _ex(_row("start", "A", "10.00"), _row("add", "Gone", "5.00"))
    new = _ex(_row("start", "A", "70.00"), _row("add", "Fresh", "3.00"))
    prev, cur = _pair(db_session, user, "left_to_spend", prev_ex=old, cur_ex=new)
    assert [c.text for c in _causes(db_session, user, "left_to_spend", prev, cur)] == [
        "A +$60.00", "Gone removed ($5.00)", "Fresh added ($3.00)"]


def test_card_source_only_feeds_its_own_card(db_session):
    user, _chk, visa, mc = _world(db_session)
    sources = _sources(card_pending=[_pend(visa.id, "Visa", "p1", "Grocery Store", "100.00")])
    prev, cur = _pair(db_session, user, f"card_payment:{mc.id}", cur_kw={"sources": sources})
    assert [c.text for c in _causes(db_session, user, f"card_payment:{mc.id}", prev, cur)] == [
        "inputs changed"]
    prev, cur = _pair(db_session, user, f"card_payment:{visa.id}", cur_kw={"sources": sources})
    assert _causes(db_session, user, f"card_payment:{visa.id}", prev, cur)[0].text.startswith(
        "new pending Visa charge")


def test_card_source_does_not_feed_checking_balance(db_session):
    user, _chk, visa, _mc = _world(db_session)
    sources = _sources(card_pending=[_pend(visa.id, "Visa", "p1", "Grocery Store", "100.00")])
    prev, cur = _pair(db_session, user, "checking_balance", cur_kw={"sources": sources})
    assert [c.text for c in _causes(db_session, user, "checking_balance", prev, cur)] == [
        "inputs changed"]


def test_checking_rows_use_account_name_and_actual_filter(db_session):
    user, chk, _v, _m = _world(db_session)
    pending = {"account_id": chk.id, "account": "Example Checking", "external_id": "c1",
               "description": "Utility Co", "amount": "-80.00"}
    posted = models.Transaction(
        user_id=user.id, account_id=chk.id, date=date(2026, 11, 2), amount=D("-20.00"),
        description="Coffee Stand", is_actual=True,
    )
    planned = models.Transaction(
        user_id=user.id, account_id=chk.id, date=date(2026, 11, 9), amount=D("-999.00"),
        description="Planned Thing", is_actual=False,
    )
    db_session.add_all([posted, planned])
    db_session.commit()
    prev, cur = _pair(
        db_session, user, "checking_balance",
        cur_kw={"sources": _sources(checking_pending=[pending], max_txn=planned.id)},
    )
    texts = [c.text for c in _causes(db_session, user, "checking_balance", prev, cur)]
    assert "new pending Example Checking charge: Utility Co $80.00" in texts
    assert "new Example Checking transaction: Coffee Stand $20.00" in texts
    assert not any("Planned Thing" in t for t in texts)
    # Checking posted rows do not feed Left to Spend.
    prev, cur = _pair(db_session, user, "left_to_spend",
                      cur_kw={"sources": _sources(max_txn=planned.id)})
    assert [c.text for c in _causes(db_session, user, "left_to_spend", prev, cur)] == ["inputs changed"]


def test_causes_never_show_ids_or_field_names(db_session):
    user, chk, visa, _mc = _world(db_session)
    pend = [_pend(visa.id, "Visa", "ext-123456", "Grocery Store", "100.00")]
    cpend = [{"account_id": chk.id, "account": "Example Checking", "external_id": "ext-777",
              "description": "Utility Co", "amount": "-80.00"}]
    prev, cur = _pair(
        db_session, user, "safety_margin",
        prev_kw={"calc_version": 11},
        cur_kw={"sources": _sources(card_pending=pend, checking_pending=cpend)},
    )
    for c in _causes(db_session, user, "safety_margin", prev, cur):
        for banned in ("external_id", "card_id", "account_id", "ext-", "123456"):
            assert banned not in c.text


def test_summarize_caps_items(db_session):
    user, _chk, visa, _mc = _world(db_session)
    items = [("p1", "Example Insurance Co.", "250.00"), ("p2", "Grocery Store", "100.00"),
             ("p3", "Online Shop", "50.00")]
    prev, cur = _pair(
        db_session, user, "safety_margin",
        cur_kw={"sources": _sources(card_pending=[_pend(visa.id, "Visa", *i) for i in items])},
    )
    causes = _causes(db_session, user, "safety_margin", prev, cur)
    assert summarize("Safety Margin", D("-400.00"), "since 7:00 AM", causes, max_items=2) == (
        "Safety Margin −$400.00 since 7:00 AM: new pending Visa charges: "
        "Example Insurance Co. $250.00, Grocery Store $100.00 and 1 more")


def test_summarize_caps_across_groups():
    causes = [Cause("a: x, y", None, head="a", items=("x", "y")), Cause("line +$1.00", D("1"))]
    assert summarize("L", D("1"), "since now", causes, max_items=2) == (
        "L +$1.00 since now: a: x, y and 1 more")


def test_summarize_empty_label_omits_label_and_space():
    assert summarize("", D("-5"), "since 7:00 AM", [Cause("inputs changed", None)], max_items=3) == (
        "−$5.00 since 7:00 AM: inputs changed")


def test_no_causes_reads_inputs_changed(db_session):
    user, _chk, _v, _m = _world(db_session)
    prev, cur = _pair(db_session, user, "left_to_spend")
    assert [c.text for c in _causes(db_session, user, "left_to_spend", prev, cur)] == ["inputs changed"]
