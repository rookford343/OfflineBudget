"""The daily email's "since last email" lines (metric_diff.since_last_email).

Invented figures only. "Today" is pinned to 2026-11-02 by test_parity_headline.
"""
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

from backend import models
from backend.services import metric_history
from backend.services.metric_diff import since_last_email
from backend.services.metric_history import collect_headline_metrics, record_snapshot
from backend.services.summary_generator import generate_daily_summary
from backend.tests.test_parity_headline import TODAY, _headline_fixture, _pin_today

D = Decimal
PREV = datetime(2026, 11, 1, 12, 0)


def _world(db, monkeypatch, *, email_snapshot=True):
    _pin_today(monkeypatch, TODAY)
    user, checking = _headline_fixture(db)
    user.email = "reader@example.com"
    db.commit()
    if email_snapshot:
        record_snapshot(db, user, "email", as_of=TODAY, now=PREV)
    return user, checking


def _add_pending(db, user, n):
    visa = db.query(models.CreditCard).filter_by(name="Test Visa").one()
    for i in range(n):
        db.add(models.CardPendingTransaction(
            user_id=user.id, card_id=visa.id, external_id=f"p-{i}", date=TODAY,
            amount=D("10.00") + i, merchant=f"Example Shop Number {i} Of The Town",
            synced_at=datetime(2026, 11, 2, 8, 0),
        ))
    db.commit()


def _since(db, user):
    return since_last_email(db, user, collect_headline_metrics(db, user, TODAY))


def _set_previous(db, user, key, delta):
    """Make the stored email reading `delta` below today's figure."""
    now_value = {r.key: r.value for r in collect_headline_metrics(db, user, TODAY)}[key]
    snap = metric_history.latest_snapshot(db, user.id, "email")
    row = next(r for r in snap.readings if r.metric_key == key)
    row.value = now_value - delta
    db.commit()


def test_since_line_under_a_moved_figure(db_session, monkeypatch):
    user, _ = _world(db_session, monkeypatch)
    _add_pending(db_session, user, 2)
    _set_previous(db_session, user, "safety_margin_week", D("-400.00"))
    since = _since(db_session, user)
    line = since["safety_margin_week"]
    assert line in ("+$400.00 since last email", "−$400.00 since last email")
    html, text = generate_daily_summary(db_session, user, since_lines=since)
    assert html.index("Safety Margin (this week)") < html.index(line) < html.index("Lowest")
    assert f"\n    {line}\n" in text
    assert text.index("Safety margin (this week)") < text.index(line)


def test_the_documented_line_for_a_400_dollar_drop(db_session, monkeypatch):
    user, _ = _world(db_session, monkeypatch)
    _add_pending(db_session, user, 2)
    _set_previous(db_session, user, "safety_margin_week", D("-400.00"))
    line = _since(db_session, user)["safety_margin_week"]
    assert line == "−$400.00 since last email"


def test_the_line_is_the_signed_amount_for_both_signs(db_session, monkeypatch):
    user, _ = _world(db_session, monkeypatch)
    _set_previous(db_session, user, "checking_balance", D("12.50"))
    assert _since(db_session, user)["checking_balance"] == "+$12.50 since last email"
    _set_previous(db_session, user, "checking_balance", D("-12.50"))
    assert _since(db_session, user)["checking_balance"] == "−$12.50 since last email"


def test_no_line_for_an_unmoved_figure(db_session, monkeypatch):
    user, _ = _world(db_session, monkeypatch)
    _add_pending(db_session, user, 1)
    _set_previous(db_session, user, "safety_margin_week", D("-400.00"))
    since = _since(db_session, user)
    assert "safety_margin_week" in since
    # Card pending charges never touch the checking balance: a real unmoved figure.
    assert "checking_balance" not in since


def test_a_cent_is_a_move_and_no_change_is_not(db_session, monkeypatch):
    user, _ = _world(db_session, monkeypatch)
    _add_pending(db_session, user, 1)
    _set_previous(db_session, user, "checking_balance", D("0.01"))
    assert _since(db_session, user)["checking_balance"] == "+$0.01 since last email"
    _set_previous(db_session, user, "checking_balance", D("0.00"))
    assert "checking_balance" not in _since(db_session, user)


def test_one_corrupt_reading_drops_only_its_own_line(db_session, monkeypatch):
    from backend.services import metric_diff
    user, _ = _world(db_session, monkeypatch)
    _set_previous(db_session, user, "safety_margin_week", D("-400.00"))
    _set_previous(db_session, user, "spendable_week", D("-25.00"))
    real = metric_diff.signed_money

    def flaky(amount):
        if abs(amount) == D("400.00"):
            raise RuntimeError("corrupt reading")
        return real(amount)

    monkeypatch.setattr(metric_diff, "signed_money", flaky)
    since = _since(db_session, user)
    assert "safety_margin_week" not in since
    assert "spendable_week" in since


def test_no_since_line_without_a_previous_email(db_session, monkeypatch):
    user, _ = _world(db_session, monkeypatch, email_snapshot=False)
    record_snapshot(db_session, user, "sync", as_of=TODAY, now=PREV)  # a sync is not an email
    _add_pending(db_session, user, 2)
    assert _since(db_session, user) == {}
    html, text = generate_daily_summary(db_session, user, since_lines=_since(db_session, user))
    assert "since last email" not in html and "since last email" not in text






def test_every_mapped_figure_is_a_real_key():
    from backend.services import summary_generator as sg
    assert set(sg.SINCE_KEYS) <= set(metric_history.METRIC_KEYS)
    assert set(sg.SINCE_KEYS) == {
        sg.SINCE_SPENDABLE, sg.SINCE_MARGIN, sg.SINCE_NEXT_MONTH, sg.SINCE_QUARTER, sg.SINCE_CHECKING,
    }








# ── Every place a line is printed ────────────────────────────────────────────

def _marked():
    from backend.services.summary_generator import SINCE_KEYS
    return {k: f"MARK-{k}" for k in SINCE_KEYS}


def test_spendable_card_prints_its_line(db_session, monkeypatch):
    user, _ = _world(db_session, monkeypatch)
    html, text = generate_daily_summary(db_session, user, since_lines=_marked())
    assert html.index("Spendable this week") < html.index("MARK-spendable_week") < html.index("Safety Margin (this week)")
    assert text.index("Spendable this week:") < text.index("    MARK-spendable_week\n") < text.index("Safety margin (this week)")


def test_safety_margin_card_prints_its_line(db_session, monkeypatch):
    user, _ = _world(db_session, monkeypatch)
    html, text = generate_daily_summary(db_session, user, since_lines=_marked())
    assert html.index("Safety Margin (this week)") < html.index("MARK-safety_margin_week") < html.index("Lowest")
    assert text.index("Safety margin (this week)") < text.index("    MARK-safety_margin_week\n") < text.index("Monthly:")


def test_each_lowest_balance_row_prints_its_line(db_session, monkeypatch):
    user, _ = _world(db_session, monkeypatch)
    html, text = generate_daily_summary(db_session, user, since_lines=_marked())
    for body, nm_row, q_row in ((html, "Lowest next month", "Lowest in the next 3 months"),
                                (text, "  Lowest next month", "  Lowest in the next 3 months")):
        assert body.index(nm_row) < body.index("MARK-next_month_minimum") < body.index(q_row)
        assert body.index(q_row) < body.index("MARK-lookahead_minimum")
    assert "    MARK-next_month_minimum\n" in text and "    MARK-lookahead_minimum\n" in text


def test_lowest_row_lines_by_row_shape():
    from backend.services.summary_generator import _lowest_row_since
    both = {"next_month_minimum": "NM", "lookahead_minimum": "Q"}
    combined = "Lowest next month (December) and in the next 3 months"
    assert _lowest_row_since("Lowest next month (December)", both) == "NM"
    assert _lowest_row_since("Lowest in the next 3 months", both) == "Q"
    assert _lowest_row_since(combined, both) == "NM"
    assert _lowest_row_since(combined, {"lookahead_minimum": "Q"}) == "Q"
    assert _lowest_row_since("Lowest next month (December)", {"lookahead_minimum": "Q"}) is None
    assert _lowest_row_since(combined, {}) is None


def test_primary_checking_row_prints_its_line(db_session, monkeypatch):
    user, _ = _world(db_session, monkeypatch)
    html, text = generate_daily_summary(db_session, user, since_lines=_marked())
    assert html.index("Checking") < html.index("MARK-checking_balance") < html.index("Upcoming")
    assert text.index("CHECKING ACCOUNTS") < text.index("    MARK-checking_balance\n") < text.index("UPCOMING BILLS")
    # Only the primary checking carries it.
    assert text.count("MARK-checking_balance") == 1


# ── The send loop ────────────────────────────────────────────────────────────

def _run_send(db, monkeypatch, send):
    import backend.main as main
    if not db.query(models.AppSetting).filter_by(key="REPORT_RECIPIENTS").first():
        db.add(models.AppSetting(key="REPORT_RECIPIENTS", value="reader@example.com"))
        db.commit()

    class _Fixed(type(TODAY)):
        @classmethod
        def today(cls):
            return TODAY

    monkeypatch.setattr(main, "date", _Fixed)
    with patch("backend.database.SessionLocal", return_value=db), \
         patch.object(db, "close", lambda: None), \
         patch("backend.services.scheduler_state.succeeded_today",
               side_effect=lambda d, job, now=None: job == "bank_sync"), \
         patch("backend.services.email_service.send_email_via", send):
        main._send_daily_summaries()


def _email_count(db):
    return db.query(models.MetricSnapshot).filter_by(trigger="email").count()


def test_email_snapshot_saved_only_after_a_send(db_session, monkeypatch):
    user, _ = _world(db_session, monkeypatch, email_snapshot=False)
    _run_send(db_session, monkeypatch, lambda db, to, *a, **kw: (False, "smtp down"))
    assert _email_count(db_session) == 0
    _run_send(db_session, monkeypatch, lambda db, to, *a, **kw: (True, None))
    assert _email_count(db_session) == 1


def test_the_email_carries_lines_and_still_goes_when_history_breaks(db_session, monkeypatch):
    user, _ = _world(db_session, monkeypatch)
    _add_pending(db_session, user, 2)
    _set_previous(db_session, user, "safety_margin_week", D("-400.00"))
    bodies = []

    def send(db, to, subject, html, text, *a, **kw):
        bodies.append(html)
        return (True, None)

    _run_send(db_session, monkeypatch, send)
    assert "since last email" in bodies[0]
    assert _email_count(db_session) == 2

    def boom(*a, **kw):
        raise RuntimeError("history broke")

    monkeypatch.setattr(metric_history, "collect_headline_metrics", boom)
    db_session.query(models.SchedulerRun).delete()
    db_session.commit()
    _run_send(db_session, monkeypatch, send)
    assert len(bodies) == 2 and "since last email" not in bodies[1]
    assert _email_count(db_session) == 2


# ── "What changed since last email" closing section ──────────────────────────

CHANGES_TITLE = "What changed since last email"


def _explained(db, user, keys=None):
    from backend.services.metric_diff import explain_since_last_email
    return explain_since_last_email(db, user, collect_headline_metrics(db, user, TODAY), keys=keys)


def _moved_world(db, monkeypatch, pending=2):
    user, _ = _world(db, monkeypatch)
    _add_pending(db, user, pending)
    _set_previous(db, user, "safety_margin_week", D("-400.00"))
    return user


def test_section_comes_last_with_label_delta_and_cause(db_session, monkeypatch):
    user = _moved_world(db_session, monkeypatch)
    changes = _explained(db_session, user)
    html, text = generate_daily_summary(db_session, user, since_changes=changes)
    assert html.index("Sent by OfflineBudget") > html.index(CHANGES_TITLE) > html.index("Spending this month")
    block = html[html.index(CHANGES_TITLE):html.index("Sent by OfflineBudget")]
    assert "Safety Margin (this week)" in block and "−$400.00" in block
    assert "new pending Test Visa charges" in block
    assert text.rstrip().splitlines()[-1].startswith("    ")
    tail = text[text.index(CHANGES_TITLE.upper()):]
    assert "Safety Margin (this week)" in tail and "−$400.00" in tail and "new pending Test Visa" in tail
    assert tail.index("Example Shop Number 0") < tail.index("Example Shop Number 1")


def test_no_section_without_a_previous_email_or_a_move(db_session, monkeypatch):
    user, _ = _world(db_session, monkeypatch, email_snapshot=False)
    assert _explained(db_session, user) == []
    for changes in (None, [], _explained(db_session, user)):
        html, text = generate_daily_summary(db_session, user, since_changes=changes)
        assert CHANGES_TITLE not in html and CHANGES_TITLE.upper() not in text


def test_no_section_when_nothing_moved(db_session, monkeypatch):
    user, _ = _world(db_session, monkeypatch)
    changes = _explained(db_session, user)
    assert changes == []
    html, text = generate_daily_summary(db_session, user, since_changes=changes)
    assert CHANGES_TITLE not in html and CHANGES_TITLE.upper() not in text


def test_keys_limit_the_figures(db_session, monkeypatch):
    user = _moved_world(db_session, monkeypatch)
    assert [c.key for c in _explained(db_session, user, keys=("safety_margin_week",))] == ["safety_margin_week"]
    assert _explained(db_session, user, keys=("checking_balance",)) == []


def test_a_derived_figure_points_at_its_parent(db_session, monkeypatch):
    user = _moved_world(db_session, monkeypatch)
    _set_previous(db_session, user, "safety_margin", D("-400.00"))
    changes = {c.key: c for c in _explained(db_session, user)}
    parent = changes["safety_margin"]
    child = changes["safety_margin_week"]
    assert parent.causes[0].parent_key == ""
    assert [c.text for c in child.causes] == [f"Same causes as {parent.label}"]
    assert child.causes[0].parent_key == "safety_margin"
    html, text = generate_daily_summary(db_session, user, since_changes=[parent, child])
    assert "Same causes as" not in html and "Same causes as" not in text
    top = text[text.index(CHANGES_TITLE.upper()):].splitlines()[1]
    assert child.label in top and parent.label in top
    assert "Moved:" not in text[text.index(CHANGES_TITLE.upper()):]


def test_more_than_five_items_are_capped(db_session, monkeypatch):
    user = _moved_world(db_session, monkeypatch, pending=8)
    changes = [c for c in _explained(db_session, user) if c.key == "safety_margin_week"]
    html, text = generate_daily_summary(db_session, user, since_changes=changes)
    block = html[html.index(CHANGES_TITLE):]
    assert block.count("Example Shop Number") == 5
    assert "and 3 more" in block and "and 3 more" in text
    assert "Example Shop Number 5" not in block


def test_one_batch_moving_two_figures_is_listed_once(db_session, monkeypatch):
    user = _moved_world(db_session, monkeypatch, pending=3)
    _set_previous(db_session, user, "next_month_minimum", D("-16.00"))
    changes = [c for c in _explained(db_session, user) if c.key in ("safety_margin_week", "next_month_minimum")]
    assert len(changes) == 2
    html, text = generate_daily_summary(db_session, user, since_changes=changes)
    html, text = html[html.index(CHANGES_TITLE):], text[text.index(CHANGES_TITLE.upper()):]
    for body in (html, text):
        assert body.count("new pending Test Visa charges") == 1
        for i in range(3):
            assert body.count(f"Example Shop Number {i} ") == 1
        assert all(c.label in body for c in changes)
    top = text.splitlines()[1]
    assert all(c.label in top for c in changes)


def _cause(head="", text="a cause", rows=(), short=""):
    from backend.services.metric_diff import Cause
    return Cause(text=text, amount=None, head=head, items=tuple(n for n, _ in rows), rows=tuple(rows), short=short)


def _chg(key, label, causes, delta="5.00"):
    from backend.services.metric_diff import EmailChange
    return EmailChange(key=key, label=label, delta=D(delta), causes=causes)


def test_a_partial_reason_names_the_figures_it_moved(db_session, monkeypatch):
    user, _ = _world(db_session, monkeypatch)
    shared = _cause(head="Shared batch", rows=[("Item One", D("1.00"))])
    only_b = _cause(text="Only B reason")
    changes = [_chg("k1", "Figure A", [shared]), _chg("k2", "Figure B", [shared, only_b])]
    html, text = generate_daily_summary(db_session, user, since_changes=changes)
    tail = text[text.index(CHANGES_TITLE.upper()):]
    assert tail.count("Moved:") == 1
    assert "Moved: Figure A, Figure B" not in tail
    assert tail.index("Only B reason") < tail.index("Moved: Figure B")
    assert tail.index("Shared batch") < tail.index("Only B reason")
    assert html.count("Moved: Figure B") == 1 and "Moved: Figure A" not in html


def test_a_vague_inherited_cause_is_filtered_out(db_session, monkeypatch):
    user, _ = _world(db_session, monkeypatch)
    vague = _cause(text="Card bills already charged changed", short="Card bills already charged changed")
    substantive = _cause(
        text="Jan 15 — CC Estimate: Test Visa −$40.00", short="Jan 15 — CC Estimate: Test Visa changed"
    )
    changes = [_chg("k1", "Figure A", [vague, substantive])]
    html, text = generate_daily_summary(db_session, user, since_changes=changes)
    html, text = html[html.index(CHANGES_TITLE):], text[text.index(CHANGES_TITLE.upper()):]
    assert "Card bills already charged changed" not in html
    assert "Card bills already charged changed" not in text
    assert "Jan 15 — CC Estimate: Test Visa −$40.00" in html
    assert "Jan 15 — CC Estimate: Test Visa −$40.00" in text


def test_a_grouped_head_cause_is_never_dropped_by_the_vague_filter(db_session, monkeypatch):
    user, _ = _world(db_session, monkeypatch)
    grouped = _cause(head="New pending charges", rows=[("Some Merchant", D("12.34"))])
    changes = [_chg("k1", "Figure A", [grouped])]
    html, text = generate_daily_summary(db_session, user, since_changes=changes)
    html, text = html[html.index(CHANGES_TITLE):], text[text.index(CHANGES_TITLE.upper()):]
    assert "New pending charges" in html and "New pending charges" in text
    assert "Some Merchant" in html and "Some Merchant" in text


def test_seven_distinct_reasons_are_capped(db_session, monkeypatch):
    user, _ = _world(db_session, monkeypatch)
    changes = [_chg("k1", "Figure A", [_cause(text=f"Reason number {i}") for i in range(8)])]
    html, text = generate_daily_summary(db_session, user, since_changes=changes)
    assert "and 2 more reasons" in html and "and 2 more reasons" in text
    assert "Reason number 5" in text and "Reason number 6" not in text


def test_a_merchant_name_is_escaped(db_session, monkeypatch):
    user = _moved_world(db_session, monkeypatch, pending=1)
    db_session.query(models.CardPendingTransaction).update({"merchant": "Shop <b>Bold</b> & Sons"})
    db_session.commit()
    changes = _explained(db_session, user)
    html, _ = generate_daily_summary(db_session, user, since_changes=changes)
    assert "Shop &lt;b&gt;Bold&lt;/b&gt; &amp; Sons" in html
    assert "<b>Bold</b>" not in html


def test_the_email_still_goes_when_explaining_breaks(db_session, monkeypatch):
    from backend.services import metric_diff
    _moved_world(db_session, monkeypatch)
    bodies = []

    def send(db, to, subject, html, text, *a, **kw):
        bodies.append(html)
        return (True, None)

    def boom(*a, **kw):
        raise RuntimeError("explain broke")

    monkeypatch.setattr(metric_diff, "explain_since_last_email", boom)
    _run_send(db_session, monkeypatch, send)
    assert len(bodies) == 1 and CHANGES_TITLE not in bodies[0]
    assert "Sent by OfflineBudget" in bodies[0]
    # The since-lines and the email snapshot survive the failed explanation.
    assert "since last email" in bodies[0]
    assert _email_count(db_session) == 2


def _change(label="Figure", head="", text="a cause", rows=()):
    return _chg("safety_margin_week", label, [_cause(head=head, text=text, rows=rows)])


def test_a_figure_label_is_escaped(db_session, monkeypatch):
    user, _ = _world(db_session, monkeypatch)
    html, _ = generate_daily_summary(db_session, user, since_changes=[_change(label="Lab <b>X</b>")])
    assert "Lab &lt;b&gt;X&lt;/b&gt;" in html and "<b>X</b>" not in html


def test_a_grouped_cause_head_is_escaped(db_session, monkeypatch):
    user, _ = _world(db_session, monkeypatch)
    change = _change(head="Head <b>Y</b>", rows=[("Item One", D("1.00"))])
    html, _ = generate_daily_summary(db_session, user, since_changes=[change])
    assert "Head &lt;b&gt;Y&lt;/b&gt;" in html and "<b>Y</b>" not in html


def test_a_line_cause_text_is_escaped(db_session, monkeypatch):
    user, _ = _world(db_session, monkeypatch)
    html, _ = generate_daily_summary(db_session, user, since_changes=[_change(text="Cause <b>Z</b>")])
    assert "Cause &lt;b&gt;Z&lt;/b&gt;" in html and "<b>Z</b>" not in html


def test_the_text_body_shows_a_capped_grouped_cause(db_session, monkeypatch):
    user, _ = _world(db_session, monkeypatch)
    rows = [(f"Item Number {i}", D("1.00")) for i in range(8)]
    _, text = generate_daily_summary(
        db_session, user, since_changes=[_change(head="Grouped head", rows=rows)],
    )
    tail = text[text.index(CHANGES_TITLE.upper()):]
    assert "- Grouped head" in tail
    for i in range(5):
        assert f"Item Number {i}" in tail
    assert "Item Number 5" not in tail
    assert "    and 3 more" in tail


def _reason_count(text):
    tail = text[text.index(CHANGES_TITLE.upper()):]
    return sum(1 for ln in tail.splitlines() if ln.startswith("- "))


def test_same_head_and_names_with_different_amounts_stay_two_reasons(db_session, monkeypatch):
    user, _ = _world(db_session, monkeypatch)
    one = _cause(head="Batch head", rows=[("Item One", D("1.00"))])
    two = _cause(head="Batch head", rows=[("Item One", D("2.00"))])
    changes = [_chg("k1", "Figure A", [one]), _chg("k2", "Figure B", [two])]
    _, text = generate_daily_summary(db_session, user, since_changes=changes)
    assert _reason_count(text) == 2
    assert "Item One $1.00" in text and "Item One $2.00" in text


def test_same_head_with_different_names_stays_two_reasons(db_session, monkeypatch):
    user, _ = _world(db_session, monkeypatch)
    one = _cause(head="Batch head", rows=[("Item One", D("1.00"))])
    two = _cause(head="Batch head", rows=[("Item Two", D("1.00"))])
    changes = [_chg("k1", "Figure A", [one]), _chg("k2", "Figure B", [two])]
    _, text = generate_daily_summary(db_session, user, since_changes=changes)
    assert _reason_count(text) == 2


def test_line_causes_differing_only_by_amount_stay_separate(db_session, monkeypatch):
    user, _ = _world(db_session, monkeypatch)
    changes = [
        _chg("k1", "Figure A", [_cause(text="Example bill changed by $5.00")]),
        _chg("k2", "Figure B", [_cause(text="Example bill changed by $6.00")]),
    ]
    _, text = generate_daily_summary(db_session, user, since_changes=changes)
    assert _reason_count(text) == 2


def test_a_figure_label_in_the_moved_note_is_escaped(db_session, monkeypatch):
    user, _ = _world(db_session, monkeypatch)
    changes = [
        _chg("k1", "Lab <b>X</b>", [_cause(text="Reason one"), _cause(text="Reason two")]),
        _chg("k2", "Figure B", [_cause(text="Reason two")]),
    ]
    html, _ = generate_daily_summary(db_session, user, since_changes=changes)
    assert "Moved: Lab &lt;b&gt;X&lt;/b&gt;" in html and "<b>X</b>" not in html


def test_a_child_listed_before_its_parent_merges_into_the_parent(db_session, monkeypatch):
    from backend.services.metric_diff import Cause
    user, _ = _world(db_session, monkeypatch)
    placeholder = Cause(text="Same causes as Parent Figure", amount=None, parent_key="parent")
    child = _chg("child", "Child Figure", [placeholder])
    parent = _chg("parent", "Parent Figure", [_cause(text="Reason one"), _cause(text="Reason two")])
    html, text = generate_daily_summary(db_session, user, since_changes=[child, parent])
    tail = text[text.index(CHANGES_TITLE.upper()):]
    assert "Same causes as" not in html and "Same causes as" not in text
    assert "Moved:" not in tail and "Moved:" not in html
    assert _reason_count(text) == 2
    assert "Child Figure" in tail.splitlines()[1]
