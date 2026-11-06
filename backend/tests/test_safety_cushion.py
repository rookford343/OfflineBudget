"""Safety Margin reads next month's low; the 3-month low is a warning signal
against the user's safety cushion (approved 2026-11-06).

1. Safety Margin starts from the lowest projected checking balance from
   today through the END of next calendar month (its own walk, same
   floor_mask rule), not the rolling 3-month low. Formula otherwise
   unchanged: low - this month's card bills + card bills already charged.
2. `lookahead_minimum` (the 3-month low, Forecast-tab walk) is still
   computed and gets `lookahead_status`:
     "danger"  -- strictly below $0
     "warning" -- strictly below the cushion (and not below $0)
     "ok"      -- at or above the cushion (exactly AT the cushion is ok)
3. `User.safety_cushion` is nullable; null means $1,000.00.

Synthetic figures and pinned dates only, never real account data.
"""
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from backend import models
from backend.schemas import UserUpdate
from backend.services.budget_snapshot import (
    DEFAULT_SAFETY_CUSHION, compute_budget_snapshot, lookahead_status,
)
from backend.services.summary_generator import generate_daily_summary
from backend.tests.test_summary_generator_next_month_low import _blank_snapshot

TODAY = date(2026, 3, 10)


def _freeze_today(monkeypatch, fixed: date) -> None:
    class _FixedDate(date):
        @classmethod
        def today(cls):
            return fixed
    monkeypatch.setattr("backend.services.forecast_engine.date", _FixedDate)
    monkeypatch.setattr("backend.services.budget_snapshot.date", _FixedDate)


def _scenario(db, monkeypatch, *, cushion: Decimal | None = None):
    """$3,000.00 checking, a $100.00 paycheck on the 15th, and one $5,000.00
    yearly bill on May 20 -- month 3 of the window, after next month (April)
    ends. No cards, so floor_mask excludes nothing and card bills are $0.

    The snapshot's walk starts 45 days early, and with no actual
    transactions recorded the Feb paycheck counts as projected, so today's
    projected balance is $3,100.00 and May 20 lands at -$1,600.00."""
    _freeze_today(monkeypatch, TODAY)
    user = models.User(username="cushion", hashed_password="x", display_name="C",
                       safety_cushion=cushion)
    db.add(user)
    db.flush()
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("3000.00"),
    )
    db.add(account)
    db.flush()
    db.add(models.RecurringItem(
        user_id=user.id, account_id=account.id, name="Paycheck",
        amount=Decimal("100.00"), type=models.RecurringType.income,
        frequency=models.RecurringFrequency.monthly, day_of_month=15,
        start_date=date(2026, 1, 1),
    ))
    db.add(models.RecurringItem(
        user_id=user.id, account_id=account.id, name="Big yearly bill",
        amount=Decimal("5000.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.yearly, month_of_year=5, day_of_month=20,
        start_date=date(2026, 1, 1),
    ))
    db.commit()
    return user, account


# ── 1. Safety Margin's window ──────────────────────────────────────────────

def test_safety_margin_reads_next_months_low_not_the_3_month_low(db_session, monkeypatch):
    user, account = _scenario(db_session, monkeypatch)
    snap = compute_budget_snapshot(db_session, user, account.id, as_of=TODAY)

    # The 3-month low is the May 20 bill, and it's unchanged.
    assert snap.lookahead_minimum_date == date(2026, 5, 20)
    assert snap.lookahead_minimum == Decimal("-1600.00")
    # Safety Margin reads today -> Apr 30 only: the lowest balance there is
    # today's $3,100.00 (no card bills to subtract). Under the old 3-month
    # rule it was -$1,600.00.
    assert snap.safety_margin == Decimal("3100.00")
    ex = snap.explain["safety_margin"]
    assert ex.rows[0].label == "Next month's lowest point"
    assert ex.rows[0].amount == Decimal("3100.00")
    assert "through Apr 30" in ex.rows[0].note
    assert ex.result == snap.safety_margin


def test_weekly_and_today_variants_follow_the_new_safety_margin(db_session, monkeypatch):
    user, account = _scenario(db_session, monkeypatch)
    snap = compute_budget_snapshot(db_session, user, account.id, as_of=TODAY)
    # Mar 10 -> Mar 31 is 22 days; weekly = 3100 / (22/7).
    assert snap.safety_margin_weekly == (Decimal("3100.00") / (Decimal(22) / Decimal(7))).quantize(Decimal("0.01"))
    assert snap.savings_pull_needed == Decimal("0.00")


# ── 2. lookahead_status boundaries ─────────────────────────────────────────

def test_lookahead_status_boundaries():
    cushion = Decimal("1000.00")
    assert lookahead_status(Decimal("1000.00"), cushion) == "ok"  # exactly at the cushion
    assert lookahead_status(Decimal("5000.00"), cushion) == "ok"
    assert lookahead_status(Decimal("999.99"), cushion) == "warning"
    assert lookahead_status(Decimal("0.00"), cushion) == "warning"  # $0 is not below $0
    assert lookahead_status(Decimal("-0.01"), cushion) == "danger"
    # A $0 cushion leaves only the below-$0 signal.
    assert lookahead_status(Decimal("0.00"), Decimal("0")) == "ok"


def test_snapshot_status_is_danger_when_the_3_month_low_is_below_zero(db_session, monkeypatch):
    user, account = _scenario(db_session, monkeypatch)
    snap = compute_budget_snapshot(db_session, user, account.id, as_of=TODAY)
    assert snap.lookahead_status == "danger"


# ── 3. The cushion setting ─────────────────────────────────────────────────

def test_null_cushion_defaults_to_1000(db_session, monkeypatch):
    user, account = _scenario(db_session, monkeypatch, cushion=None)
    snap = compute_budget_snapshot(db_session, user, account.id, as_of=TODAY)
    assert DEFAULT_SAFETY_CUSHION == Decimal("1000.00")
    assert snap.safety_cushion == Decimal("1000.00")


def test_a_set_cushion_drives_the_status(db_session, monkeypatch):
    # Move the yearly bill's month out of from the window so the 3-month low
    # is positive, then move the cushion across it.
    user, account = _scenario(db_session, monkeypatch, cushion=Decimal("3500.00"))
    bill = db_session.query(models.RecurringItem).filter_by(name="Big yearly bill").one()
    bill.month_of_year = 9
    db_session.commit()
    snap = compute_budget_snapshot(db_session, user, account.id, as_of=TODAY)
    assert snap.lookahead_minimum == Decimal("3100.00")
    assert snap.safety_cushion == Decimal("3500.00")
    assert snap.lookahead_status == "warning"

    user.safety_cushion = Decimal("3100.00")  # exactly at the low: ok
    db_session.commit()
    snap = compute_budget_snapshot(db_session, user, account.id, as_of=TODAY)
    assert snap.lookahead_status == "ok"


def test_user_update_accepts_and_rejects_cushions():
    assert UserUpdate(safety_cushion=Decimal("2500.00")).safety_cushion == Decimal("2500.00")
    assert UserUpdate(safety_cushion=None).safety_cushion is None
    import pytest
    with pytest.raises(ValueError):
        UserUpdate(safety_cushion=Decimal("-1.00"))


def test_patch_me_saves_and_clears_the_cushion(db_session):
    from backend.routers.auth import update_me
    from backend.schemas import UserOut
    user = models.User(username="cushionapi", hashed_password="x", display_name="C")
    db_session.add(user)
    db_session.commit()

    out = UserOut.model_validate(update_me(UserUpdate(safety_cushion=Decimal("2500.00")), db_session, user))
    assert out.safety_cushion == Decimal("2500.00")
    # An explicit null clears it back to the default.
    out = UserOut.model_validate(update_me(UserUpdate(safety_cushion=None), db_session, user))
    assert out.safety_cushion is None


# ── 4. The daily email ─────────────────────────────────────────────────────

def _render(db_session, snap, username):
    user = models.User(username=username, hashed_password="x", display_name="D")
    db_session.add(user)
    db_session.flush()
    db_session.add(models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("1000.00"),
    ))
    db_session.commit()
    with patch("backend.services.summary_generator.compute_budget_snapshot", return_value=snap):
        return generate_daily_summary(db_session, user)


def _snap(status: str, low: str):
    return _blank_snapshot(
        lookahead_minimum=Decimal(low), lookahead_minimum_date=date(2027, 1, 20),
        next_month_minimum=Decimal("4000.00"), next_month_minimum_date=date(2026, 11, 25),
        next_month_label="November", safety_cushion=Decimal("1000.00"),
        lookahead_status=status,
    )


def test_email_shows_no_warning_when_ok(db_session):
    html, text = _render(db_session, _snap("ok", "2500.00"), "emailok")
    assert "cushion" not in html and "cushion" not in text
    assert "below $0" not in html and "below $0" not in text


def test_email_shows_the_cushion_warning_in_amber(db_session):
    html, text = _render(db_session, _snap("warning", "400.00"), "emailwarn")
    assert "below your $1,000.00 cushion" in html
    assert "below your $1,000.00 cushion" in text
    assert "color:#d97706'>$400.00" in html


def test_email_shows_the_below_zero_warning_in_red(db_session):
    html, text = _render(db_session, _snap("danger", "-400.00"), "emaildanger")
    assert "below $0" in html and "below $0" in text
    assert "cushion" not in html
    assert "color:#dc2626'>−$400.00" in html
