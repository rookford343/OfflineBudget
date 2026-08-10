from datetime import date
from backend.main import _is_digest_day


def test_is_digest_day_true_on_the_matching_weekday():
    # Aug 14 2026 is a Friday.
    assert _is_digest_day(date(2026, 8, 14), "fri") is True


def test_is_digest_day_false_on_other_weekdays():
    # Aug 13 2026 is a Thursday.
    assert _is_digest_day(date(2026, 8, 13), "fri") is False


def test_is_digest_day_is_case_and_whitespace_insensitive():
    assert _is_digest_day(date(2026, 8, 14), " FRI ") is True


def test_is_digest_day_accepts_a_full_weekday_name():
    # APScheduler's day_of_week also accepts full names, not just 'fri'.
    assert _is_digest_day(date(2026, 8, 14), "friday") is True
    assert _is_digest_day(date(2026, 8, 14), " Friday ") is True
    assert _is_digest_day(date(2026, 8, 13), "friday") is False


def test_is_digest_day_fails_open_on_unsupported_cron_forms():
    """Lists/ranges/integers aren't parsed. Returning False means the Daily
    Summary keeps sending -- nothing is silently lost."""
    assert _is_digest_day(date(2026, 8, 14), "mon-fri") is False
    assert _is_digest_day(date(2026, 8, 14), "mon,fri") is False
    assert _is_digest_day(date(2026, 8, 14), "4") is False


# ── Daily-summary skip gating ────────────────────────────────────────────────

import backend.main as main_module


def _daily_summary_ran(monkeypatch, *, recipients: str, today: date) -> bool:
    """Runs _send_daily_summaries with a stubbed clock and settings, and
    reports whether it got past the digest-day skip (True) or returned
    early (False). The DB work past the guard is stubbed out."""
    monkeypatch.setattr(main_module.settings, "DIGEST_RECIPIENTS", recipients, raising=False)
    monkeypatch.setattr(main_module.settings, "WEEKLY_DIGEST_DAY", "fri", raising=False)

    class _FakeDate(date):
        @classmethod
        def today(cls):
            return today

    monkeypatch.setattr(main_module, "date", _FakeDate)

    reached = {"past_guard": False}

    class _FakeSession:
        def query(self, *a, **kw):
            reached["past_guard"] = True
            raise RuntimeError("stop here -- the guard is all this test cares about")

        def close(self):
            pass

    monkeypatch.setattr("backend.database.SessionLocal", lambda: _FakeSession())
    try:
        main_module._send_daily_summaries()
    except RuntimeError:
        pass
    return reached["past_guard"]


def test_daily_summary_is_skipped_on_digest_day_when_recipients_are_configured(monkeypatch):
    assert _daily_summary_ran(monkeypatch, recipients="dan@example.com", today=date(2026, 8, 14)) is False


def test_daily_summary_still_sends_on_digest_day_when_the_digest_is_disabled(monkeypatch):
    """Regression: a blank DIGEST_RECIPIENTS disables the Weekly Digest, so
    skipping the Daily Summary that day would send nothing at all."""
    assert _daily_summary_ran(monkeypatch, recipients="", today=date(2026, 8, 14)) is True


def test_daily_summary_sends_on_a_non_digest_day(monkeypatch):
    assert _daily_summary_ran(monkeypatch, recipients="dan@example.com", today=date(2026, 8, 13)) is True
