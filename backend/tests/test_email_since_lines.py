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
    return since_last_email(db, user, collect_headline_metrics(db, user, TODAY), as_of=TODAY)


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
    assert line.startswith("+$400.00 since last email: new pending Test Visa charges: ") or \
        line.startswith("−$400.00 since last email: new pending Test Visa charges: ")
    html, text = generate_daily_summary(db_session, user, since_lines=since)
    assert html.index("Safety Margin (this week)") < html.index(line) < html.index("Lowest")
    assert f"\n    {line}\n" in text
    assert text.index("Safety margin (this week)") < text.index(line)


def test_the_documented_line_for_a_400_dollar_drop(db_session, monkeypatch):
    user, _ = _world(db_session, monkeypatch)
    _add_pending(db_session, user, 2)
    _set_previous(db_session, user, "safety_margin_week", D("-400.00"))
    line = _since(db_session, user)["safety_margin_week"]
    assert line.startswith("−$400.00 since last email: new pending Test Visa charges: ")


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
    assert _since(db_session, user)["checking_balance"].startswith("+$0.01 since last email")
    _set_previous(db_session, user, "checking_balance", D("0.00"))
    assert "checking_balance" not in _since(db_session, user)


def test_one_corrupt_reading_drops_only_its_own_line(db_session, monkeypatch):
    from backend.services import metric_diff
    user, _ = _world(db_session, monkeypatch)
    _add_pending(db_session, user, 1)
    _set_previous(db_session, user, "safety_margin_week", D("-400.00"))
    _set_previous(db_session, user, "spendable_week", D("-25.00"))
    real = metric_diff._causes_or_fallback

    def flaky(db, user_id, key, prev, cur):
        if key == "safety_margin_week":
            raise RuntimeError("corrupt reading")
        return real(db, user_id, key, prev, cur)

    monkeypatch.setattr(metric_diff, "_causes_or_fallback", flaky)
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


def test_line_fits_a_phone(db_session, monkeypatch):
    user, _ = _world(db_session, monkeypatch)
    _add_pending(db_session, user, 6)
    _set_previous(db_session, user, "safety_margin_week", D("-400.00"))
    since = _since(db_session, user)
    assert since
    assert all(len(line) <= 120 for line in since.values()), since
    assert any(line.endswith("…") or "and " in line for line in since.values())


def test_a_unreadable_older_snapshot_degrades_to_inputs_changed(db_session, monkeypatch):
    user, _ = _world(db_session, monkeypatch)
    _add_pending(db_session, user, 1)
    snap = metric_history.latest_snapshot(db_session, user.id, "email")
    snap.sources_json = "not json"
    for r in snap.readings:
        r.explain_json = "garbage"
        if r.metric_key == "safety_margin_week":
            r.value = r.value + D("5.00")
    db_session.commit()
    line = _since(db_session, user)["safety_margin_week"]
    assert line.endswith("inputs changed")


def test_every_mapped_figure_is_a_real_key():
    from backend.services import summary_generator as sg
    assert set(sg.SINCE_KEYS) <= set(metric_history.METRIC_KEYS)
    assert set(sg.SINCE_KEYS) == {
        sg.SINCE_SPENDABLE, sg.SINCE_MARGIN, sg.SINCE_NEXT_MONTH, sg.SINCE_QUARTER, sg.SINCE_CHECKING,
    }


def test_fit_cuts_at_a_word_boundary():
    from backend.services.metric_diff import EMAIL_LINE_MAX, _fit
    line = " ".join(["word"] * 40)
    out = _fit(line)
    assert len(out) <= EMAIL_LINE_MAX and out.endswith("…") and not out.endswith(" …")
    assert line.startswith(out[:-1]) and out[:-1].endswith("word")


def test_fit_cuts_a_line_with_no_spaces():
    from backend.services.metric_diff import EMAIL_LINE_MAX, _fit
    out = _fit("x" * 300)
    assert len(out) == EMAIL_LINE_MAX and out.endswith("…")


def test_fit_leaves_exactly_120_characters_alone():
    from backend.services.metric_diff import _fit
    line = ("ab " * 40)[:120]
    assert len(line) == 120 and _fit(line) == line
    assert _fit(line + "z") != line + "z"


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
