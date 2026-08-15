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


# ── Weekly-digest addendum gating ────────────────────────────────────────────
#
# The Daily Summary always sends now -- it no longer gets skipped on the
# Weekly Digest's day. Instead, on that day, the Weekly Digest's own
# section (spending by category, top merchants, balance risk) gets computed
# and passed into generate_daily_summary() as an addendum, appended to that
# same email rather than going out as a second, separate one.

import backend.main as main_module


def _run_send_daily_summaries(monkeypatch, *, recipients: str, today: date, weekly_digest_day: str = "fri"):
    """Runs _send_daily_summaries against one active user with one checking
    account, stubbing generate_daily_summary/generate_weekly_digest/send_email.
    Returns the `weekly_digest` value generate_daily_summary was called with
    (None if the addendum wasn't computed for that run)."""
    import backend.models as models
    from decimal import Decimal

    monkeypatch.setattr(main_module.settings, "DIGEST_RECIPIENTS", recipients, raising=False)
    monkeypatch.setattr(main_module.settings, "WEEKLY_DIGEST_DAY", weekly_digest_day, raising=False)

    class _FakeDate(date):
        @classmethod
        def today(cls):
            return today

    monkeypatch.setattr(main_module, "date", _FakeDate)

    user = models.User(id=1, username="dan", hashed_password="x", display_name="Dan", email="dan@example.com", is_active=True)
    account = models.Account(id=1, user_id=1, name="Checking", type=models.AccountType.checking, current_balance=Decimal("100.00"))

    class _FakeQuery:
        def __init__(self, model):
            self.model = model
        def filter(self, *a, **kw):
            return self
        def filter_by(self, **kw):
            return self
        def first(self):
            # No AppSetting rows -> app_settings falls back to the .env
            # defaults these tests already configure via monkeypatched
            # settings, keeping each test's original intent.
            return None
        def all(self):
            if self.model is models.User:
                return [user]
            if self.model is models.Account:
                return [account]
            return []

    class _FakeSession:
        def query(self, model):
            return _FakeQuery(model)
        def close(self):
            pass

    monkeypatch.setattr("backend.database.SessionLocal", lambda: _FakeSession())

    captured = {"weekly_digest": "not-called"}

    def _fake_generate_daily_summary(db, u, *, weekly_digest=None):
        captured["weekly_digest"] = weekly_digest
        return ("<html>", "text")

    monkeypatch.setattr("backend.services.summary_generator.generate_daily_summary", _fake_generate_daily_summary)
    monkeypatch.setattr("backend.services.summary_generator.generate_weekly_digest", lambda db, u, account_id: "WEEKLY_DIGEST_STUB")
    monkeypatch.setattr("backend.services.email_service.send_email_via", lambda *a, **kw: (True, None))

    main_module._send_daily_summaries()
    return captured["weekly_digest"]


def test_daily_summary_gets_the_weekly_addendum_on_digest_day_when_recipients_are_configured(monkeypatch):
    assert _run_send_daily_summaries(monkeypatch, recipients="dan@example.com", today=date(2026, 8, 14)) == "WEEKLY_DIGEST_STUB"


def test_daily_summary_has_no_addendum_on_digest_day_when_the_digest_is_disabled(monkeypatch):
    """Regression: a blank DIGEST_RECIPIENTS disables the Weekly Digest
    addendum -- the Daily Summary itself must still send."""
    assert _run_send_daily_summaries(monkeypatch, recipients="", today=date(2026, 8, 14)) is None


def test_daily_summary_has_no_addendum_on_a_non_digest_day(monkeypatch):
    assert _run_send_daily_summaries(monkeypatch, recipients="dan@example.com", today=date(2026, 8, 13)) is None


# ── Multi-recipient daily summary ────────────────────────────────────────────

from backend.services.email_service import parse_recipients


def test_parse_recipients_splits_a_comma_separated_field():
    assert parse_recipients("dan@example.com, wife@example.com") == ["dan@example.com", "wife@example.com"]


def test_parse_recipients_handles_a_single_address():
    assert parse_recipients("dan@example.com") == ["dan@example.com"]


def test_parse_recipients_drops_blank_entries_and_extra_whitespace():
    assert parse_recipients(" dan@example.com ,, wife@example.com,") == ["dan@example.com", "wife@example.com"]


def test_parse_recipients_returns_empty_list_for_none_or_blank():
    assert parse_recipients(None) == []
    assert parse_recipients("") == []


def test_daily_summary_emails_every_recipient_in_a_multi_address_field(monkeypatch):
    """Regression: user.email holding "dan@x.com, wife@x.com" used to be
    passed whole to send_email as a single malformed address -- now each
    parsed recipient gets its own send_email call."""
    import backend.models as models
    from decimal import Decimal

    monkeypatch.setattr(main_module.settings, "DIGEST_RECIPIENTS", "", raising=False)

    class _FakeDate(date):
        @classmethod
        def today(cls):
            return date(2026, 8, 13)  # a non-digest-day Thursday

    monkeypatch.setattr(main_module, "date", _FakeDate)

    user = models.User(id=1, username="dan", hashed_password="x", display_name="Dan", email="dan@example.com, wife@example.com", is_active=True)
    account = models.Account(id=1, user_id=1, name="Checking", type=models.AccountType.checking, current_balance=Decimal("100.00"))

    class _FakeQuery:
        def __init__(self, model):
            self.model = model
        def filter(self, *a, **kw):
            return self
        def filter_by(self, **kw):
            return self
        def first(self):
            # No AppSetting rows -> app_settings falls back to the .env
            # defaults these tests already configure via monkeypatched
            # settings, keeping each test's original intent.
            return None
        def all(self):
            if self.model is models.User:
                return [user]
            if self.model is models.Account:
                return [account]
            return []

    class _FakeSession:
        def query(self, model):
            return _FakeQuery(model)
        def close(self):
            pass

    monkeypatch.setattr("backend.database.SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr("backend.services.summary_generator.generate_daily_summary", lambda db, u, **kw: ("<html>", "text"))
    sent_to = []

    def _capture(db, to, *a, **kw):
        sent_to.append(to)
        return (True, None)

    monkeypatch.setattr("backend.services.email_service.send_email_via", _capture)

    main_module._send_daily_summaries()

    assert sent_to == ["dan@example.com", "wife@example.com"]
