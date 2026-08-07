from datetime import date
from decimal import Decimal
from backend.schemas import ForecastEntry, ForecastTransaction
from backend.services.forecast_engine import find_balance_risk, find_transfer_signal


def _entry(d: date, balance: str) -> ForecastEntry:
    return ForecastEntry(date=d, projected_balance=Decimal(balance), transactions=[])


def _entry_with_transfer(d: date, balance: str, transfer_amount: str | None = None, name: str = "Transfer from Savings") -> ForecastEntry:
    txns = []
    if transfer_amount is not None:
        txns.append(ForecastTransaction(
            name=name, amount=Decimal(transfer_amount), type="income",
            category_name=None, is_actual=False, is_transfer=True,
        ))
    return ForecastEntry(date=d, projected_balance=Decimal(balance), transactions=txns)


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


def test_find_transfer_signal_returns_not_triggered_when_no_transfers():
    entries = [_entry_with_transfer(date(2026, 8, 1), "500.00")]
    result = find_transfer_signal(entries)
    assert result == {"triggered": False, "date": None, "amount": None, "from_name": None}


def test_find_transfer_signal_returns_first_transfer():
    entries = [
        _entry_with_transfer(date(2026, 8, 1), "500.00"),
        _entry_with_transfer(date(2026, 9, 1), "3375.00", transfer_amount="3000.00", name="Transfer from Savings"),
    ]
    result = find_transfer_signal(entries)
    assert result == {
        "triggered": True,
        "date": date(2026, 9, 1),
        "amount": Decimal("3000.00"),
        "from_name": "Savings",
    }
