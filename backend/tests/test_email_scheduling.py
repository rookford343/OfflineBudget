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
