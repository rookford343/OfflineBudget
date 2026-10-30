"""The daily email's Household Snapshot redesign (approved 2026-10-29):

  1. Real minus sign (U+2212) before a negative dollar figure, never
     Python's default "$-".
  2. A "Lowest next month (<Month>)" line alongside the existing 3-month
     one, collapsed into one combined line when they land on the same day
     for the same amount.
  3. A "Move $Y into checking by <1st of next month>" line directly under
     the next-month low when it's projected to go negative, Y rounded UP
     to the next whole $1,000.
  4. The two Household Snapshot cards stay in one table row (two <td>
     cells, percentage widths) at any width, with figures/labels/padding
     sized to fit a narrow phone without overflowing.

Uses invented figures throughout, never real account data.
"""
import re
from datetime import date
from decimal import Decimal
from backend import models
from backend.services.summary_generator import _fmt, _round_up_to_thousand, generate_daily_summary
from backend.schemas import BudgetSnapshot


def _blank_snapshot(**overrides) -> BudgetSnapshot:
    """A BudgetSnapshot with every amount zeroed out except what a test
    overrides -- isolates the Household Snapshot rendering from the rest of
    compute_budget_snapshot's machinery."""
    defaults = dict(
        as_of=date(2026, 10, 29),
        leftover=Decimal("0"),
        left_to_spend=Decimal("0"),
        left_to_spend_weekly=Decimal("0"),
        savings_budget=Decimal("0"),
        left_to_spend_if_savings_skipped=Decimal("0"),
        savings_pull_needed=Decimal("0"),
        shortfall_this_month=Decimal("0"),
        reserve_needed=Decimal("0"),
        savings_balance=Decimal("0"),
        months_left_in_year=3,
        spendable_today=Decimal("0"),
        days_left_in_week=7,
        on_pace=True,
        safety_margin=Decimal("0"),
        safety_margin_weekly=Decimal("0"),
        safety_margin_today=Decimal("0"),
        days_remaining_in_month=30,
        lookahead_minimum=Decimal("0"),
        lookahead_minimum_date=None,
        next_month_minimum=Decimal("0"),
        next_month_minimum_date=None,
        next_month_label=None,
        explain={},
        cards=[],
        categories=[],
        top_merchants=[],
    )
    defaults.update(overrides)
    return BudgetSnapshot(**defaults)


def _user_and_checking(db, username: str):
    user = models.User(username=username, hashed_password="x", display_name="D")
    db.add(user)
    db.flush()
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("1000.00"),
    )
    db.add(account)
    db.commit()
    return user


def _render(db_session, snap: BudgetSnapshot, username: str) -> tuple[str, str]:
    """Patches compute_budget_snapshot to hand generate_daily_summary a
    fixed snapshot, isolating the Household Snapshot rendering under test
    from the rest of the forecast/leftover machinery."""
    from unittest.mock import patch
    user = _user_and_checking(db_session, username)
    with patch("backend.services.summary_generator.compute_budget_snapshot", return_value=snap):
        return generate_daily_summary(db_session, user)


# ── 1. Minus sign ──────────────────────────────────────────────────────────

def test_fmt_negative_uses_a_real_minus_sign_before_the_dollar_sign():
    assert _fmt(Decimal("-3150.75")) == "−$3,150.75"
    assert not _fmt(Decimal("-3150.75")).startswith("$-")


def test_fmt_positive_has_no_sign():
    assert _fmt(Decimal("3150.75")) == "$3,150.75"


def test_email_never_renders_the_old_dollar_hyphen_format(db_session):
    snap = _blank_snapshot(
        left_to_spend_weekly=Decimal("-1234.56"),
        safety_margin_weekly=Decimal("-55.00"),
        lookahead_minimum=Decimal("-5200.00"),
        lookahead_minimum_date=date(2027, 1, 25),
        next_month_minimum=Decimal("-3150.75"),
        next_month_minimum_date=date(2026, 11, 25),
        next_month_label="November",
    )
    html, text = _render(db_session, snap, "signtest")
    assert "$-" not in html
    assert "$-" not in text
    assert "−$3,150.75" in html
    assert "−$3,150.75" in text


# ── 2. Two lows / combined line ─────────────────────────────────────────────

def test_different_dates_show_two_separate_lines(db_session):
    snap = _blank_snapshot(
        lookahead_minimum=Decimal("-5200.00"),
        lookahead_minimum_date=date(2027, 1, 25),
        next_month_minimum=Decimal("-1500.00"),
        next_month_minimum_date=date(2026, 11, 25),
        next_month_label="November",
    )
    html, text = _render(db_session, snap, "twolines")

    assert "Lowest next month (November):" in html
    assert "Lowest in the next 3 months:" in html
    assert "−$1,500.00" in html and "−$5,200.00" in html
    assert "Nov 25" in html and "Jan 25" in html
    assert "and in the next 3 months" not in html

    assert "Lowest next month (November):" in text
    assert "Lowest in the next 3 months:" in text


def test_same_date_and_amount_collapses_to_one_combined_line(db_session):
    snap = _blank_snapshot(
        lookahead_minimum=Decimal("-1500.00"),
        lookahead_minimum_date=date(2026, 11, 25),
        next_month_minimum=Decimal("-1500.00"),
        next_month_minimum_date=date(2026, 11, 25),
        next_month_label="November",
    )
    html, text = _render(db_session, snap, "combined")

    assert "Lowest next month (November) and in the next 3 months:" in html
    assert "−$1,500.00" in html
    # Only one amount/date line for the low -- not two separate ones.
    assert html.count("Lowest") == 1
    assert "Lowest next month (November) and in the next 3 months:" in text
    assert text.count("Lowest") == 1


def test_same_date_different_amount_does_not_combine(db_session):
    """Belt-and-suspenders: a same-day coincidence with a different amount
    (shouldn't happen given both read off the same walk, but the combine
    check must require both, not date alone) stays as two lines."""
    snap = _blank_snapshot(
        lookahead_minimum=Decimal("-1500.00"),
        lookahead_minimum_date=date(2026, 11, 25),
        next_month_minimum=Decimal("-1400.00"),
        next_month_minimum_date=date(2026, 11, 25),
        next_month_label="November",
    )
    html, _text = _render(db_session, snap, "samedatediffamt")
    assert "and in the next 3 months" not in html
    assert html.count("Lowest") == 2


# ── 3. Move line + rounding ─────────────────────────────────────────────────

def test_round_up_to_thousand_rounding_table():
    assert _round_up_to_thousand(Decimal("612.40")) == Decimal("1000")
    assert _round_up_to_thousand(Decimal("1000.00")) == Decimal("1000")
    assert _round_up_to_thousand(Decimal("1000.01")) == Decimal("2000")


def test_move_line_appears_when_next_month_low_is_negative(db_session):
    snap = _blank_snapshot(
        lookahead_minimum=Decimal("-612.40"),
        lookahead_minimum_date=date(2026, 11, 3),
        next_month_minimum=Decimal("-612.40"),
        next_month_minimum_date=date(2026, 11, 3),
        next_month_label="November",
    )
    html, text = _render(db_session, snap, "moveline")
    assert "Move $1,000.00 into checking by Nov 1" in html
    assert "Move $1,000.00 into checking by Nov 1" in text


def test_move_line_absent_when_next_month_low_is_non_negative(db_session):
    snap = _blank_snapshot(
        lookahead_minimum=Decimal("300.00"),
        lookahead_minimum_date=date(2027, 1, 10),
        next_month_minimum=Decimal("0.00"),
        next_month_minimum_date=date(2026, 11, 5),
        next_month_label="November",
    )
    html, text = _render(db_session, snap, "nomoveline")
    assert "Move $" not in html
    assert "Move $" not in text


# ── 5. Safety Margin per-day line ───────────────────────────────────────────

def test_email_shows_the_safety_margin_per_day_line(db_session):
    """Safety Margin gets its own "$Y/day" line, same style as Spendable's
    per-day line, in both the HTML and text bodies. Negative values use the
    email's real-minus-sign "-$" formatter."""
    snap = _blank_snapshot(
        safety_margin_weekly=Decimal("-55.00"),
        safety_margin_today=Decimal("-7.86"),
    )
    html, text = _render(db_session, snap, "margintoday")
    assert "−$7.86/day" in html
    assert "−$7.86/day" in text
    assert "$-7.86" not in html and "$-7.86" not in text


def test_email_safety_margin_per_day_line_positive_has_no_sign(db_session):
    snap = _blank_snapshot(
        safety_margin_weekly=Decimal("210.00"),
        safety_margin_today=Decimal("30.00"),
    )
    html, text = _render(db_session, snap, "marginpositive")
    assert "$30.00/day" in html
    assert "$30.00/day" in text
    assert "−$30.00/day" not in html and "−$30.00/day" not in text


# ── 4. Layout: two-cell table row with percentage widths ───────────────────

def test_household_snapshot_cards_are_one_table_row_two_cells_percentage_widths(db_session):
    snap = _blank_snapshot(
        left_to_spend_weekly=Decimal("-250.00"),
        safety_margin_weekly=Decimal("100.00"),
    )
    html, _text = _render(db_session, snap, "layout")

    snapshot_block = html[html.index("Household Snapshot"):]
    row = snapshot_block[: snapshot_block.index("</tr>")]
    tds = re.findall(r"<td\b[^>]*>", row)
    assert len(tds) == 2, f"expected exactly 2 <td> cells in the snapshot row, found {len(tds)}"
    for td in tds:
        assert "50%" in td, f"cell must carry a percentage width, got: {td}"
