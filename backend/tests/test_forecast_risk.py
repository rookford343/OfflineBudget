from datetime import date
from decimal import Decimal
from backend.schemas import ForecastEntry
from backend.services.forecast_engine import find_balance_risk


def _entry(d: date, balance: str) -> ForecastEntry:
    return ForecastEntry(date=d, projected_balance=Decimal(balance), transactions=[])


def test_no_risk_when_balance_stays_above_threshold():
    entries = [
        _entry(date(2026, 8, 1), "500.00"),
        _entry(date(2026, 8, 2), "480.00"),
        _entry(date(2026, 8, 3), "460.00"),
    ]
    result = find_balance_risk(entries, Decimal("0"))
    assert result == {"at_risk": False, "date": None, "amount": None, "threshold": Decimal("0")}


def test_flags_first_day_balance_drops_below_threshold():
    entries = [
        _entry(date(2026, 8, 1), "200.00"),
        _entry(date(2026, 8, 2), "50.00"),
        _entry(date(2026, 8, 3), "-30.00"),
        _entry(date(2026, 8, 4), "-80.00"),
    ]
    result = find_balance_risk(entries, Decimal("0"))
    assert result["at_risk"] is True
    assert result["date"] == date(2026, 8, 3)
    assert result["amount"] == Decimal("-30.00")
    assert result["threshold"] == Decimal("0")


def test_uses_custom_threshold_not_just_zero():
    entries = [
        _entry(date(2026, 8, 1), "200.00"),
        _entry(date(2026, 8, 2), "150.00"),
        _entry(date(2026, 8, 3), "80.00"),
    ]
    result = find_balance_risk(entries, Decimal("100"))
    assert result["at_risk"] is True
    assert result["date"] == date(2026, 8, 3)
    assert result["amount"] == Decimal("80.00")
    assert result["threshold"] == Decimal("100")


def test_empty_entries_returns_no_risk():
    result = find_balance_risk([], Decimal("0"))
    assert result["at_risk"] is False
