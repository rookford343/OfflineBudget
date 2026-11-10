"""The statement view of change history: `math_lines`, `statement_headline`,
`statement_for` and GET /history/{key}/statement. Invented figures only."""
import json
from datetime import date, datetime
from decimal import Decimal

import pytest

from backend import models, schemas
from backend.services.metric_diff import Cause, math_lines, statement_for, statement_headline
from backend.tests.test_history_api import (  # noqa: F401 -- _pinned_zone is autouse once imported
    _client, _explain, _pinned_zone, _snap, _sources, _user,
)

D = Decimal


def _row(op, label, amount, kids=(), info=()):
    return schemas.ExplainRow(
        op=op, label=label, amount=D(amount),
        children=[schemas.ExplainChild(label=n, amount=D(a)) for n, a in kids],
        informational_children=[schemas.ExplainChild(label=n, amount=D(a)) for n, a in info],
    )


def _receipt(*rows, result="0"):
    return schemas.Explanation(title="T", result=D(result), rows=list(rows))


def _at(day, hour=12, month=11):
    return datetime(2026, month, day, hour, 0)


def _newest(db, user, key="leftover"):
    return (db.query(models.MetricReading).join(models.MetricSnapshot)
            .filter(models.MetricSnapshot.user_id == user.id, models.MetricReading.metric_key == key)
            .order_by(models.MetricSnapshot.taken_at.desc()).first())


def _statement(db, user, days=7):
    return statement_for(db, user.id, _newest(db, user), days)


def test_math_lines_sign_subtracted_rows_and_add_up():
    old = _receipt(_row("start", "Low", "2000"), _row("subtract", "Bills", "800"), _row("result", "Total", "1200"))
    new = _receipt(_row("start", "Low", "1900"), _row("subtract", "Bills", "800"), _row("result", "Total", "1100"))
    lines = math_lines(old, new)
    assert [(ln.label, ln.old, ln.new) for ln in lines] == [
        ("Low", D("2000"), D("1900")), ("Bills", D("-800"), D("-800"))]
    assert sum(ln.new for ln in lines) == D("1100")


def test_math_lines_skip_result_and_divide_rows():
    old = _receipt(_row("start", "Low", "700"), _row("divide", "Weeks", "4"), _row("result", "Total", "175"))
    assert [ln.label for ln in math_lines(old, old)] == ["Low"]


def test_math_lines_line_on_one_side():
    old = _receipt(_row("start", "Low", "100"), _row("add", "Gone", "30"))
    new = _receipt(_row("start", "Low", "100"), _row("add", "Fresh", "20"))
    assert [(ln.label, ln.old, ln.new) for ln in math_lines(old, new)] == [
        ("Low", D("100"), D("100")), ("Gone", D("30"), None), ("Fresh", None, D("20"))]


def test_math_lines_parts_are_the_changed_children():
    old = _receipt(_row("start", "Low", "1000", info=[("Card estimate", "-100"), ("Rent", "-500")]))
    new = _receipt(_row("start", "Low", "940", info=[("Card estimate", "-160"), ("Rent", "-500")]))
    lines = math_lines(old, new)
    assert lines[0].parts == [schemas.HistoryMathPart(label="Card estimate", delta=D("-60"))]


def test_math_lines_parts_under_a_subtracted_row_take_its_sign():
    old = _receipt(_row("start", "Low", "1000", kids=[("A", "100")]),
                   _row("subtract", "Bills", "300", kids=[("Rent", "300")]))
    new = _receipt(_row("start", "Low", "1060", kids=[("A", "160")]),
                   _row("subtract", "Bills", "360", kids=[("Rent", "360")]))
    lines = math_lines(old, new)
    assert lines[0].parts == [schemas.HistoryMathPart(label="A", delta=D("60"))]
    assert lines[1].parts == [schemas.HistoryMathPart(label="Rent", delta=D("-60"))]


def test_math_lines_parts_skip_one_sided_informational_children():
    old = _receipt(_row("start", "Low", "1000", kids=[("Real", "10")], info=[("Both", "5"), ("Moved", "7")]))
    new = _receipt(_row("start", "Low", "1000", kids=[("Fresh", "20")], info=[("Both", "9"), ("Shown", "40")]))
    parts = {p.label: p.delta for p in math_lines(old, new)[0].parts}
    # Informational "Moved" (old only) and "Shown" (new only) are not arithmetic.
    assert parts == {"Real": D("-10"), "Fresh": D("20"), "Both": D("4")}


def test_statement_headline_drops_line_causes_when_an_event_exists():
    causes = [Cause("x", None, head="new pending Visa charge"), Cause("Low -$5.00", D("-5"), short="Low changed")]
    assert statement_headline(causes) == "New pending Visa charge"


def test_statement_headline_uses_the_line_when_no_event():
    assert statement_headline([Cause("Low -$5.00", D("-5"), short="Low changed")]) == "Low changed"


def test_statement_rows_carry_change_and_balance(db_session):
    user = _user(db_session)
    for t, v in ((_at(2, 8), "500"), (_at(2, 9), "450"), (_at(2, 10), "475")):
        _snap(db_session, user, t, v)
    row = _statement(db_session, user).days[0].rows[0]
    assert (row.delta, row.old_value, row.new_value) == (D("25"), D("450"), D("475"))
    assert row.headline == "Base changed"


def test_statement_day_delta_is_the_days_net(db_session):
    user = _user(db_session)
    for t, v in ((_at(2, 8), "500"), (_at(2, 9), "450"), (_at(2, 10), "475")):
        _snap(db_session, user, t, v)
    day = _statement(db_session, user).days[0]
    assert day.delta == D("-25") and len(day.rows) == 2


def test_statement_groups_by_local_day(db_session):
    user = _user(db_session)
    _snap(db_session, user, datetime(2026, 11, 3, 3, 0), "100")
    _snap(db_session, user, datetime(2026, 11, 3, 4, 30), "90")  # Nov 2, 11:30 PM Eastern
    assert _statement(db_session, user).days[0].day == date(2026, 11, 2)


def test_statement_period_measures_from_oldest_shown(db_session):
    user = _user(db_session)
    for t, v in ((_at(1), "1000"), (_at(2), "900"), (_at(3), "850"), (_at(4), "800")):
        _snap(db_session, user, t, v)
    out = _statement(db_session, user, days=2)
    assert (out.period_from, out.period_delta, out.period_since) == (D("900"), D("-100"), _at(3))
    assert out.has_more is True and len(out.days) == 2
    assert out.current_value == D("800")


def test_statement_max_days_counts_days_with_changes(db_session):
    user = _user(db_session)
    for t, v in ((_at(1), "100"), (_at(2), "90"), (_at(3), "90"), (_at(4), "80")):
        _snap(db_session, user, t, v)
    out = _statement(db_session, user, days=2)
    assert [d.day for d in out.days] == [date(2026, 11, 4), date(2026, 11, 2)]
    assert out.has_more is False


def test_statement_current_taken_at_is_the_newest_reading(db_session):
    user = _user(db_session)
    for t, v in ((_at(2, 8), "500"), (_at(2, 9), "450"), (_at(3, 10), "450")):
        _snap(db_session, user, t, v)
    out = _statement(db_session, user)
    assert out.current_taken_at == _at(3, 10)  # the newest reading did not move


def test_statement_no_changes_is_empty(db_session):
    user = _user(db_session)
    _snap(db_session, user, _at(1), "100")
    out = _statement(db_session, user)
    assert out.days == [] and out.has_more is False
    assert (out.period_delta, out.period_from, out.period_since) == (None, None, None)


def test_statement_unreadable_receipt_has_no_math(db_session):
    user = _user(db_session)
    _snap(db_session, user, _at(1), "100")
    _snap(db_session, user, _at(2), "90", explain_json="not json")
    row = _statement(db_session, user).days[0].rows[0]
    assert (row.headline, row.math, row.events) == ("Inputs changed", [], [])


def test_statement_events_exclude_line_causes(db_session):
    user = _user(db_session)
    card = models.CreditCard(user_id=user.id, name="Visa", credit_limit=D("5000"), statement_day=20, due_day=10)
    db_session.add(card)
    db_session.commit()
    pending = [{"card_id": card.id, "card": "Visa", "external_id": "p1", "merchant": "Example Shop",
                "amount": "40.00"}]
    _snap(db_session, user, _at(1), "500", key="safety_margin", explain_json=_explain("1"))
    _snap(db_session, user, _at(2), "460", key="safety_margin", explain_json=_explain("2"),
          sources_json=json.dumps({"card_pending": pending, "checking_pending": [],
                                   "max_txn_id": 0, "max_card_txn_id": 0}))
    out = statement_for(db_session, user.id, _newest(db_session, user, "safety_margin"), 7)
    row = out.days[0].rows[0]
    assert [e.head for e in row.events] == ["new pending Visa charge"]
    assert row.headline == "New pending Visa charge"


def test_statement_route_returns_the_statement(db_session):
    user = _user(db_session)
    _snap(db_session, user, _at(1), "100")
    _snap(db_session, user, _at(2), "90")
    body = _client(db_session, user).get("/history/leftover/statement?days=3").json()
    assert body["metric_key"] == "leftover" and len(body["days"]) == 1
    # The frontend reads the sign off these strings (startsWith("-")).
    row = body["days"][0]["rows"][0]
    assert isinstance(body["current_value"], str) and isinstance(body["period_delta"], str)
    assert isinstance(body["days"][0]["delta"], str)
    assert all(isinstance(row[k], str) for k in ("delta", "old_value", "new_value"))
    assert row["delta"].startswith("-")


def test_statement_route_days_cap_is_the_retention(db_session):
    user = _user(db_session)
    _snap(db_session, user, _at(1), "100")
    _snap(db_session, user, _at(2), "90")
    client = _client(db_session, user)
    assert client.get("/history/leftover/statement?days=0").status_code == 422
    assert client.get("/history/leftover/statement?days=400").status_code == 200
    assert client.get("/history/leftover/statement?days=401").status_code == 422


def test_statement_route_unknown_key_is_404(db_session):
    user = _user(db_session)
    _snap(db_session, user, _at(1), "100")
    assert _client(db_session, user).get("/history/safety_margin/statement").status_code == 404


@pytest.mark.parametrize("key", ["leftover;drop", "Leftover", "card_payment:", "a" * 41])
def test_statement_route_bad_key_is_422(db_session, key):
    user = _user(db_session)
    assert _client(db_session, user).get(f"/history/{key}/statement").status_code == 422


def test_statement_route_is_scoped_to_the_caller(db_session):
    owner, other = _user(db_session, "owner"), _user(db_session, "other")
    _snap(db_session, owner, _at(1), "100")
    _snap(db_session, owner, _at(2), "90")
    assert _client(db_session, other).get("/history/leftover/statement").status_code == 404
