"""Daily email restyle (2026-11-26): the HTML matches the calm Dashboard.

Safety Margin hero, Spendable, email-safe weekly-lows bars, a Needs attention
block, slate/teal cards, and a dark-mode media block. Only styling and order
change; every figure the old email carried still appears. Made-up amounts only.
"""
import re
from datetime import date, timedelta
from decimal import Decimal

from backend.schemas import WeeklyLow
from backend.services.summary_generator import _weekly_lows_bars_html
from backend.tests.test_summary_generator_next_month_low import _blank_snapshot, _render

D = Decimal
START = date(2026, 11, 26)


def _low(i, amount, status="ok"):
    s = START + timedelta(days=7 * i)
    return WeeklyLow(start=s, end=s + timedelta(days=6),
                     amount=None if amount is None else D(amount),
                     date=None if amount is None else s, status=status)


def _heights(html):
    return [int(h) for h in re.findall(r"height:(\d+)px", html)]


def test_hero_leads_with_safety_margin(db_session):
    snap = _blank_snapshot(safety_margin_weekly=D("1850.00"), left_to_spend_weekly=D("1400.00"))
    html, _ = _render(db_session, snap, "herolead")
    assert html.index("Safety Margin") < html.index("Spendable this week") < html.index("Checking Accounts")


def _figure_style(html, name="margin-figure"):
    m = re.search(rf"data-ob='{name}' style='([^']*)'", html)
    assert m, f"{name} not found"
    return m.group(1)


def test_margin_tone(db_session):
    """Owner ruling 2026-11-26: green at $0 or above (incl. exactly 0), red
    below $0, never amber."""
    zero, _ = _render(db_session, _blank_snapshot(safety_margin_weekly=D("0.00")), "tone0")
    assert "color:#059669" in _figure_style(zero)
    neg, _ = _render(db_session, _blank_snapshot(safety_margin_weekly=D("-0.01")), "toneneg")
    assert "color:#dc2626" in _figure_style(neg)
    pos, _ = _render(db_session, _blank_snapshot(safety_margin_weekly=D("500.00")), "tonepos")
    assert "color:#059669" in _figure_style(pos)
    for page in (zero, neg, pos):
        style = _figure_style(page)
        assert "#d97706" not in style and "#b45309" not in style and "#fbbf24" not in style


def test_spendable_tone(db_session):
    zero, _ = _render(db_session, _blank_snapshot(left_to_spend_weekly=D("0.00")), "sp0")
    assert "color:#059669" in _figure_style(zero, "spendable-figure")
    over, _ = _render(db_session, _blank_snapshot(left_to_spend_weekly=D("-0.01"), on_pace=False), "spover")
    assert "color:#b45309" in _figure_style(over, "spendable-figure")
    assert "over pace" in over and "color:#92400e" in over[over.index("over pace") - 200:over.index("over pace")]


def test_bars_geometry():
    lows = [_low(0, "2500.00"), _low(1, "800.00"), _low(2, "1000.00")]
    html = _weekly_lows_bars_html(lows, D("1000.00"))
    assert _heights(html) == [48, 15, 19]
    # lowest ok bar is the accent; the others are the neutral bar colour
    assert html.count("background:#0f766e") == 1
    assert html.count("background:#cbd5e1") == 2
    assert html.index("height:15px") < html.index("background:#0f766e") < html.index("height:19px")


def test_bars_respect_status_and_gaps():
    lows = [_low(0, "-50.00", "danger"), _low(1, "300.00", "warning"),
            _low(2, None), _low(3, "900.00"), _low(4, "1200.00")]
    html = _weekly_lows_bars_html(lows, D("1000.00"))
    assert _heights(html) == [3, 12, 36, 48]  # stub, 300/1200*48, 900/1200*48, max
    assert html.count("background:#dc2626") == 1
    assert html.count("background:#d97706") == 1
    assert html.count("background:#0f766e") == 1  # lowest ok = 900
    assert len(re.findall(r"<td\b", html)) == 5  # null week is an empty cell, not dropped
    assert html.count("<div") == 4


def test_lowest_bar_is_earliest_minimum():
    html = _weekly_lows_bars_html([_low(0, "700.00"), _low(1, "700.00"), _low(2, "900.00")], D("1000.00"))
    assert html.index("background:#0f766e") < html.index("background:#cbd5e1")


def test_no_weekly_lows_renders(db_session):
    assert _weekly_lows_bars_html([], D("1000.00")) == ""
    html, text = _render(db_session, _blank_snapshot(weekly_lows=[]), "nolows")
    assert "CHECKING LOW POINT EACH WEEK" not in html
    assert "Safety Margin" in html


def test_bars_render_inside_the_hero(db_session):
    snap = _blank_snapshot(weekly_lows=[_low(0, "2500.00"), _low(1, "800.00")], safety_cushion=D("1000.00"))
    html, _ = _render(db_session, snap, "herobars")
    assert "CHECKING LOW POINT EACH WEEK" in html and "height:48px" in html


def test_needs_attention_quiet_and_active(db_session):
    quiet, _ = _render(db_session, _blank_snapshot(), "quiet")
    assert "Nothing needs you today." in quiet
    assert "Needs attention" not in quiet
    active, _ = _render(db_session, _blank_snapshot(savings_pull_needed=D("640.00")), "active")
    assert "Needs attention" in active and "Pull $640.00 from savings" in active
    assert "Nothing needs you today." not in active


def test_needs_attention_lists_move_and_stale(db_session):
    snap = _blank_snapshot(next_month_minimum=D("-1500.00"), next_month_minimum_date=date(2026, 12, 9),
                           next_month_label="December")
    html, _ = _render(db_session, snap, "needsmove")
    block = html[html.index("Needs attention"):]
    assert "Move $2,000.00 into checking by Dec 1" in block.split("Checking Accounts")[0]


def test_no_information_lost(db_session):
    from unittest.mock import patch
    from backend.services.summary_generator import generate_daily_summary
    from backend.tests.test_summary_generator_next_month_low import _user_and_checking
    snap = _blank_snapshot(
        left_to_spend_weekly=D("-250.00"), left_to_spend=D("-900.00"),
        safety_margin_weekly=D("-80.00"), safety_margin=D("-120.00"), safety_margin_today=D("-11.43"),
        savings_pull_needed=D("1000.00"), pending_cards_count=2, pending_cards_total=D("412.50"),
        lookahead_minimum=D("-5200.00"), lookahead_minimum_date=date(2027, 1, 25), lookahead_status="danger",
        next_month_minimum=D("-1500.00"), next_month_minimum_date=date(2026, 12, 9), next_month_label="December",
        weekly_lows=[_low(0, "2500.00"), _low(1, "-5200.00", "danger")],
    )
    since = {
        "spendable_week": "SINCE-SPENDABLE", "safety_margin_week": "SINCE-MARGIN",
        "next_month_minimum": "SINCE-NEXT", "lookahead_minimum": "SINCE-QUARTER",
        "checking_balance": "SINCE-CHECKING",
    }
    user = _user_and_checking(db_session, "nolost")
    with patch("backend.services.summary_generator.compute_budget_snapshot", return_value=snap), \
         patch("backend.services.summary_generator._last_pull_line", return_value="Bank data updated today 7:15 AM"):
        html, text = generate_daily_summary(db_session, user, since_lines=since)
    for line in since.values():
        assert line in html and line in text
    assert "Move $2,000.00 into checking by Dec 1" in html
    assert "Includes pending charges on 2 cards ($412.50)" in html
    assert "Bank data updated today 7:15 AM" in html
    for title in ("Checking", "Upcoming", "Credit Cards", "Spending this month"):
        assert title in html
    assert "−$250.00" in html and "−$80.00" in html and "−$11.43/day" in html
    assert "Lowest next month (December)" in html and "Lowest in the next 3 months" in html
    assert "below $0" in html


def test_weekly_digest_title_present(db_session):
    from unittest.mock import MagicMock, patch
    from backend.services import summary_generator as sg
    from backend.tests.test_summary_generator_next_month_low import _user_and_checking
    user = _user_and_checking(db_session, "wd")
    with patch.object(sg, "_weekly_digest_section", lambda d: ("<div>Weekly Digest — marker</div>", "WEEKLY DIGEST")):
        html, _ = sg.generate_daily_summary(db_session, user, weekly_digest=MagicMock())
    assert "Weekly Digest" in html


def test_dark_mode_block(db_session):
    html, _ = _render(db_session, _blank_snapshot(), "dark")
    assert "prefers-color-scheme: dark" in html
    hero = re.search(r"<div class='ob-card ob-hero'[^>]*>", html)
    assert hero, "hero card missing"
    assert "background:#ffffff" in hero.group(0)
    for dark in ("#0b1220", "#131c2e", "#22304a", "#e2e8f0", "#94a3b8", "#2dd4bf", "#334155",
                 "#34d399", "#f87171", "#fbbf24"):
        assert dark in html


def test_no_checking_account_still_renders(db_session):
    from backend import models
    from backend.services.summary_generator import generate_daily_summary
    user = models.User(username="nochk", hashed_password="x", display_name="D")
    db_session.add(user)
    db_session.commit()
    html, text = generate_daily_summary(db_session, user)
    assert "No checking account to compute a snapshot from." in html


# Colours the dark block remaps (palette ink/muted) plus semantic colours that
# read fine on both backgrounds or carry their own dark override / own box.
_DARK_SAFE = {
    "#0f172a", "#64748b",                       # remapped by attribute selectors
    "#059669", "#dc2626", "#b45309", "#92400e",  # green/red/amber/warn-text (classes)
    "#d97706", "#0f766e", "#991b1b",             # amber text, accent (class), red text on its own light box
}


def test_every_inline_text_colour_is_dark_mode_safe(db_session):
    from unittest.mock import patch
    from backend import models
    from backend.services import summary_generator as sg
    from backend.tests.test_summary_generator_next_month_low import _user_and_checking
    user = _user_and_checking(db_session, "darkcolors")
    db_session.add(models.CreditCard(user_id=user.id, name="Card", credit_limit=D("5000"), statement_day=15,
                                     due_day=1, current_balance=D("300.00"), balance_due=D("100.00")))
    db_session.commit()
    snap = _blank_snapshot(
        weekly_lows=[_low(0, "2500.00"), _low(1, "-5.00", "danger")], savings_pull_needed=D("50.00"),
        next_month_minimum=D("-100.00"), next_month_minimum_date=date(2026, 12, 9), next_month_label="December",
        lookahead_minimum=D("-100.00"), lookahead_minimum_date=date(2027, 1, 9), lookahead_status="danger",
        pending_cards_count=1, pending_cards_total=D("10.00"))
    digest = sg.generate_weekly_digest(db_session, user, db_session.query(models.Account).first().id)
    with patch("backend.services.summary_generator.compute_budget_snapshot", return_value=snap):
        html, _ = sg.generate_daily_summary(db_session, user, weekly_digest=digest, since_lines={"safety_margin_week": "x"})
    used = set(re.findall(r"(?<![-\w])color:(#[0-9a-fA-F]{6})", html.split("</style>", 1)[1]))
    assert used, "expected inline colours"
    assert used <= _DARK_SAFE, f"inline colours with no dark-mode treatment: {sorted(used - _DARK_SAFE)}"


def test_lookahead_warning_alone_is_not_quiet(db_session):
    """Subject says "Heads up" for a warning low point, so the body must not
    say "Nothing needs you today." (no pull, no move line)."""
    snap = _blank_snapshot(lookahead_minimum=D("400.00"), lookahead_minimum_date=date(2027, 1, 25),
                           lookahead_status="warning", safety_cushion=D("1000.00"))
    html, _ = _render(db_session, snap, "lookwarn")
    assert "Nothing needs you today." not in html
    block = html[html.index("Needs attention"):html.index("Checking Accounts")]
    assert "Lowest in the next 3 months: $400.00 on Jan 25" in block
    assert "below your $1,000.00 cushion" in block


def test_covered_subject_iff_quiet_body(db_session):
    from backend.services.summary_generator import email_subject
    states = {
        "ok": {},
        "warning": dict(lookahead_minimum=D("400.00"), lookahead_minimum_date=date(2027, 1, 25), lookahead_status="warning"),
        "danger": dict(lookahead_minimum=D("-400.00"), lookahead_minimum_date=date(2027, 1, 25), lookahead_status="danger"),
        "pull": dict(savings_pull_needed=D("90.00")),
        "move": dict(next_month_minimum=D("-100.00"), next_month_minimum_date=date(2026, 12, 9), next_month_label="December"),
        "nm_ok": dict(next_month_minimum=D("50.00"), next_month_minimum_date=date(2026, 12, 9), next_month_label="December"),
    }
    for name, kw in states.items():
        snap = _blank_snapshot(**kw)
        html, _ = _render(db_session, snap, f"iff{name}")
        covered = email_subject(snap, date(2026, 11, 26), False).startswith("Covered")
        assert covered == ("Nothing needs you today." in html), name
        assert covered == ("Needs attention" not in html), name


def test_hero_red_lines_have_a_dark_red_override(db_session):
    snap = _blank_snapshot(lookahead_minimum=D("-400.00"), lookahead_minimum_date=date(2027, 1, 25),
                           lookahead_status="danger", next_month_minimum=D("-100.00"),
                           next_month_minimum_date=date(2026, 12, 9), next_month_label="December")
    html, _ = _render(db_session, snap, "darkred")
    hero = html[html.index("ob-hero"):html.index("Needs attention")]
    for m in re.finditer(r"<(?:p|b|span)\b([^>]*)>", hero):
        if "color:#dc2626" in m.group(1):
            assert "ob-neg" in m.group(1), m.group(0)
