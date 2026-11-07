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
    _history_cause,
    diff_explanations,
    explain_change,
    headline,
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


PREV_AT = datetime(2026, 11, 2, 7, 0)
BETWEEN = datetime(2026, 11, 2, 9, 0)   # a row created between the two snapshots
CUR_AT = datetime(2026, 11, 2, 12, 0)


def _snap(db, user, *, as_of=date(2026, 11, 2), calc_version=12, sources=None, readings=None,
          taken_at=PREV_AT):
    snap = models.MetricSnapshot(
        user_id=user.id, taken_at=taken_at, trigger="sync",
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
    cur = _snap(db, user, readings={key: (cur_val, cur_ex or flat)},
                **{"taken_at": CUR_AT, **(cur_kw or {})})
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
        merchant="Grocery Store", created_at=BETWEEN,
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
    # The posted row was created between the snapshots, so it cancels the new pending row.
    assert [c.text for c in _causes(db_session, user, "left_to_spend", prev2, cur2)] == ["inputs changed"]


def test_unmatched_posted_and_dropped_pending_are_named(db_session):
    user, _chk, visa, _mc = _world(db_session)
    posted = models.CreditCardTransaction(
        card_id=visa.id, user_id=user.id, date=date(2026, 11, 2), amount=D("42.00"),
        merchant="Example Cafe", created_at=BETWEEN,
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
        description="Coffee Stand", is_actual=True, created_at=BETWEEN,
    )
    planned = models.Transaction(
        user_id=user.id, account_id=chk.id, date=date(2026, 11, 9), amount=D("-999.00"),
        description="Planned Thing", is_actual=False, created_at=BETWEEN,
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


def test_old_dated_import_between_snapshots_is_not_a_cause(db_session):
    user, chk, _v, _m = _world(db_session)
    db_session.add_all([
        # Imported between the snapshots but dated months ago: not why today moved.
        models.Transaction(user_id=user.id, account_id=chk.id, date=date(2026, 6, 14), amount=D("-31.00"),
                           description="Old Import", is_actual=True, created_at=BETWEEN),
        models.Transaction(user_id=user.id, account_id=chk.id, date=date(2026, 11, 2), amount=D("-20.00"),
                           description="Coffee Stand", is_actual=True, created_at=BETWEEN),
    ])
    db_session.commit()
    prev, cur = _pair(db_session, user, "checking_balance")
    texts = [c.text for c in _causes(db_session, user, "checking_balance", prev, cur)]
    assert texts == ["new Example Checking transaction: Coffee Stand $20.00"]


def test_current_month_card_row_created_between_snapshots_is_a_cause(db_session):
    user, _chk, visa, _mc = _world(db_session)
    db_session.add_all([
        models.CreditCardTransaction(card_id=visa.id, user_id=user.id, date=date(2026, 11, 1),
                                     amount=D("42.00"), merchant="Example Cafe", created_at=BETWEEN),
        # Dated before the previous reading's month: outside the window.
        models.CreditCardTransaction(card_id=visa.id, user_id=user.id, date=date(2026, 10, 31),
                                     amount=D("9.00"), merchant="Too Old", created_at=BETWEEN),
    ])
    db_session.commit()
    prev, cur = _pair(db_session, user, "left_to_spend")
    assert [c.text for c in _causes(db_session, user, "left_to_spend", prev, cur)] == [
        "new Visa transaction: Example Cafe $42.00"]


def test_rows_created_outside_the_snapshot_window_are_not_causes(db_session):
    """A row created before the previous snapshot is not new even when its id is
    above the stored high-water mark (ids are reused after a clear-all), and a
    row created after the current snapshot is not new yet. A NULL created_at is skipped."""
    user, chk, visa, _mc = _world(db_session)
    db_session.add_all([
        models.CreditCardTransaction(card_id=visa.id, user_id=user.id, date=date(2026, 11, 2),
                                     amount=D("11.00"), merchant="Before", created_at=datetime(2026, 11, 2, 6, 0)),
        models.CreditCardTransaction(card_id=visa.id, user_id=user.id, date=date(2026, 11, 2),
                                     amount=D("12.00"), merchant="After", created_at=datetime(2026, 11, 2, 13, 0)),
        models.CreditCardTransaction(card_id=visa.id, user_id=user.id, date=date(2026, 11, 2),
                                     amount=D("13.00"), merchant="NoStamp", created_at=None),
    ])
    db_session.commit()
    # Every row's id sits inside the stored high-water range, as after id reuse.
    prev, cur = _pair(db_session, user, "left_to_spend",
                      prev_kw={"sources": _sources(max_card_txn=0)},
                      cur_kw={"sources": _sources(max_card_txn=99)})
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


# ── A pending charge that posts as several rows ──────────────────────────────

def _card_rows(db, user, card, *amounts):
    rows = [
        models.CreditCardTransaction(card_id=card.id, user_id=user.id, date=date(2026, 11, 2),
                                     amount=D(a), merchant=f"Split Shop {n}", created_at=BETWEEN)
        for n, a in enumerate(amounts, 1)
    ]
    db.add_all(rows)
    db.commit()


def _card_texts(db, user, prev_pending, cur_pending):
    prev, cur = _pair(
        db, user, "left_to_spend",
        prev_kw={"sources": _sources(card_pending=prev_pending)},
        cur_kw={"sources": _sources(card_pending=cur_pending)},
    )
    return [c.text for c in _causes(db, user, "left_to_spend", prev, cur)]


def test_split_posting_is_not_reported_twice(db_session):
    user, _chk, visa, _mc = _world(db_session)
    _card_rows(db_session, user, visa, "25.00", "35.00")
    texts = _card_texts(db_session, user, [_pend(visa.id, "Visa", "p1", "Big Store", "60.00")], [])
    assert texts == ["inputs changed"]


def test_split_leaves_remainder_as_new_transaction(db_session):
    user, _chk, visa, _mc = _world(db_session)
    _card_rows(db_session, user, visa, "25.00", "35.00", "10.00")
    texts = _card_texts(db_session, user, [_pend(visa.id, "Visa", "p1", "Big Store", "60.00")], [])
    assert texts == ["new Visa transaction: Split Shop 3 $10.00"]


def test_exact_match_beats_split(db_session):
    user, _chk, visa, _mc = _world(db_session)
    _card_rows(db_session, user, visa, "30.00", "20.00")
    texts = _card_texts(db_session, user, [
        _pend(visa.id, "Visa", "p1", "Small Store", "30.00"),
        _pend(visa.id, "Visa", "p2", "Large Store", "50.00"),
    ], [])
    assert texts == [
        "pending Visa charge dropped: Large Store $50.00",
        "new Visa transaction: Split Shop 2 $20.00",
    ]


def test_new_pending_is_never_split_matched(db_session):
    user, _chk, visa, _mc = _world(db_session)
    _card_rows(db_session, user, visa, "25.00", "35.00")
    texts = _card_texts(db_session, user, [], [_pend(visa.id, "Visa", "p1", "Big Store", "60.00")])
    assert texts == [
        "new pending Visa charge: Big Store $60.00",
        "new Visa transactions: Split Shop 1 $25.00, Split Shop 2 $35.00",
    ]


def test_split_rows_on_another_card_do_not_pair(db_session):
    user, _chk, visa, mc = _world(db_session)
    _card_rows(db_session, user, mc, "25.00", "35.00")
    texts = _card_texts(db_session, user, [_pend(visa.id, "Visa", "p1", "Big Store", "60.00")], [])
    assert texts == [
        "pending Visa charge dropped: Big Store $60.00",
        "new Mastercard transactions: Split Shop 1 $25.00, Split Shop 2 $35.00",
    ]


def test_split_search_is_capped_per_owner(db_session):
    user, _chk, visa, _mc = _world(db_session)
    _card_rows(db_session, user, visa, "25.00", "35.00", *["1.00"] * 11)
    texts = _card_texts(db_session, user, [_pend(visa.id, "Visa", "p1", "Big Store", "60.00")], [])
    assert texts[0] == "pending Visa charge dropped: Big Store $60.00"


def test_split_cap_boundary_is_twelve_owner_rows(db_session):
    user, _chk, visa, _mc = _world(db_session)
    _card_rows(db_session, user, visa, "25.00", "35.00", *["1.00"] * 10)  # 12 rows: searched
    texts = _card_texts(db_session, user, [_pend(visa.id, "Visa", "p1", "Big Store", "60.00")], [])
    assert texts == ["new Visa transactions: Split Shop 3 $1.00, Split Shop 4 $1.00, Split Shop 5 $1.00, "
                     "Split Shop 6 $1.00, Split Shop 7 $1.00, Split Shop 8 $1.00, Split Shop 9 $1.00, "
                     "Split Shop 10 $1.00, Split Shop 11 $1.00, Split Shop 12 $1.00"]


def test_split_cap_boundary_thirteen_rows_is_not_searched(db_session):
    user, _chk, visa, _mc = _world(db_session)
    _card_rows(db_session, user, visa, "25.00", "35.00", *["1.00"] * 11)  # 13 rows: skipped
    texts = _card_texts(db_session, user, [_pend(visa.id, "Visa", "p1", "Big Store", "60.00")], [])
    assert texts[0] == "pending Visa charge dropped: Big Store $60.00"


def test_split_parts_must_share_the_pending_sign(db_session):
    user, _chk, visa, _mc = _world(db_session)
    _card_rows(db_session, user, visa, "80.00", "-20.00")  # sums to 60.00 but one is a refund
    texts = _card_texts(db_session, user, [_pend(visa.id, "Visa", "p1", "Big Store", "60.00")], [])
    assert texts[0] == "pending Visa charge dropped: Big Store $60.00"


def _derived_pair(db, user, *, parent_in_prev=True, calc=(12, 12), pending=None):
    """safety_margin_week whose receipt has a 'safety_margin' row; the parent's own
    receipt moved on its 'Next month lowest' line."""
    week = lambda v: _ex(_row("start", "safety_margin", v))  # noqa: E731
    parent = lambda v: _ex(_row("start", "Next month lowest", v))  # noqa: E731
    prev_readings = {"safety_margin_week": ("100.00", week("400.00"))}
    if parent_in_prev:
        prev_readings["safety_margin"] = ("400.00", parent("400.00"))
    prev = _snap(db, user, readings=prev_readings, calc_version=calc[0])
    cur = _snap(db, user, taken_at=CUR_AT, calc_version=calc[1],
                sources=_sources(card_pending=pending or ()), readings={
                    "safety_margin_week": ("50.00", week("200.00")),
                    "safety_margin": ("200.00", parent("200.00")),
                })
    return (next(r for r in prev.readings if r.metric_key == "safety_margin_week"),
            next(r for r in cur.readings if r.metric_key == "safety_margin_week"))


def test_derived_figure_shows_its_parents_causes(db_session):
    user, _chk, _v, _m = _world(db_session)
    prev, cur = _derived_pair(db_session, user)
    causes = _causes(db_session, user, "safety_margin_week", prev, cur)
    assert [(c.text, c.amount) for c in causes] == [("Next month lowest changed", None)]
    assert all("safety_margin" not in c.text for c in causes)


def test_derived_figure_inherits_grouped_cause_without_amounts_and_dedupes(db_session):
    user, _chk, visa, _mc = _world(db_session)
    pending = [_pend(visa.id, "Visa", "p1", "Big Store", "60.00")]
    prev, cur = _derived_pair(db_session, user, pending=pending)
    causes = _causes(db_session, user, "safety_margin_week", prev, cur)
    # The week figure already has the source cause itself; the parent's copy is not repeated.
    assert [c.head for c in causes].count("new pending Visa charge") == 1
    assert [c.text for c in causes][-1] == "Next month lowest changed"


def test_inherited_grouped_cause_keeps_names_and_drops_amounts():
    from backend.services.metric_diff import _inherited
    g = Cause("g: A $1.00", None, head="g", items=("A $1.00",), rows=(("A", D("1.00")),))
    out = _history_cause(_inherited(g))
    assert out.text == "g: A" and out.head == "g"
    assert [(i.name, i.amount) for i in out.items] == [("A", None)]


def test_derived_figure_keeps_its_own_line_when_parent_reading_is_missing(db_session):
    user, _chk, _v, _m = _world(db_session)
    prev, cur = _derived_pair(db_session, user, parent_in_prev=False)
    causes = _causes(db_session, user, "safety_margin_week", prev, cur)
    assert [(c.short, c.amount) for c in causes] == [("safety_margin changed", D("-200.00"))]


def test_line_cause_headline_has_no_amount():
    from backend.services.metric_diff import _line_cause
    for change, tail in ((LineChange("CC Estimate: Apple Card", None, D("50")), "added"),
                         (LineChange("CC Estimate: Apple Card", D("50"), None), "removed"),
                         (LineChange("CC Estimate: Apple Card", D("50"), D("20")), "changed")):
        c = _line_cause(change)
        assert headline([c]) == f"CC Estimate: Apple Card {tail}"
        assert "$" in c.text and "$" not in headline([c])


def test_split_posting_on_checking_is_not_reported_twice(db_session):
    user, chk, _v, _m = _world(db_session)
    pending = {"account_id": chk.id, "account": "Example Checking", "external_id": "c1",
               "description": "Utility Co", "amount": "-60.00"}
    db_session.add_all([
        models.Transaction(user_id=user.id, account_id=chk.id, date=date(2026, 11, 2), amount=D(a),
                           description=f"Utility Part {n}", is_actual=True, created_at=BETWEEN)
        for n, a in enumerate(("-25.00", "-35.00"), 1)
    ])
    db_session.commit()
    prev, cur = _pair(
        db_session, user, "checking_balance",
        prev_kw={"sources": _sources(checking_pending=[pending])},
        cur_kw={"sources": _sources()},
    )
    assert [c.text for c in _causes(db_session, user, "checking_balance", prev, cur)] == [
        "inputs changed"]


def test_grouped_cause_carries_head_and_items(db_session):
    user, _chk, visa, _mc = _world(db_session)
    items = [("p1", "Example Insurance Co.", "250.00"), ("p2", "Grocery Store", "100.00")]
    prev, cur = _pair(
        db_session, user, "safety_margin",
        cur_kw={"sources": _sources(card_pending=[_pend(visa.id, "Visa", *i) for i in items])},
    )
    schemas_cause = _causes(db_session, user, "safety_margin", prev, cur)[0]
    out = _history_cause(schemas_cause)
    assert out.head == "new pending Visa charges"
    assert [(i.name, i.amount) for i in out.items] == [
        ("Example Insurance Co.", D("250.00")), ("Grocery Store", D("100.00"))]
    assert schemas_cause.text.startswith("new pending Visa charges: ")


def test_headline_for_a_grouped_first_cause():
    c = Cause("new pending Visa charges: A $1.00", None, head="new pending Visa charges",
              items=("A $1.00",), rows=(("A", D("1.00")),))
    assert headline([c]) == "New pending Visa charges"


def test_headline_for_a_line_cause_and_more():
    causes = [Cause("Paycheck +$5.00", D("5"), short="Paycheck changed"),
              Cause("Rent −$2.00", D("-2"), short="Rent changed"), Cause("new month (Dec)", None)]
    assert headline(causes) == "Paycheck changed + 2 more"


def test_headline_counts_causes_not_items():
    g = Cause("g: a, b, c", None, head="g", items=("a", "b", "c"),
              rows=(("a", D("1")), ("b", D("1")), ("c", D("1"))))
    assert headline([g, Cause("x", None)]) == "G + 1 more"


def test_headline_fallback():
    assert headline([]) == "Inputs changed"
