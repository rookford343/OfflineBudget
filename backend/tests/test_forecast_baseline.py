from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch
from backend import models
from backend.schemas import ForecastEntry
from backend.services.forecast_baseline import (
    ensure_month_baseline, get_month_baseline, baseline_points, ensure_baselines_for_all,
)

ENGINE = "backend.services.forecast_baseline.build_forecast"
SUCCEEDED_TODAY = "backend.services.forecast_baseline.scheduler_state.succeeded_today"


def _connect_bank(db, user, status=models.BankConnectionStatus.active):
    conn = models.BankConnection(user_id=user.id, access_url_encrypted="x", status=status)
    db.add(conn); db.commit()
    return conn


def _seed(db, username="fb"):
    user = models.User(username=username, hashed_password="x", display_name="FB")
    db.add(user); db.flush()
    acct = models.Account(user_id=user.id, name="Chk", type=models.AccountType.checking,
                          current_balance=Decimal("1000.00"))
    db.add(acct); db.commit()
    return user, acct


def _fake(start: date, end: date, base="1000.00"):
    out, d, n = [], start, 0
    while d <= end:
        out.append(ForecastEntry(date=d, projected_balance=Decimal(base) - n, transactions=[]))
        d += timedelta(days=1); n += 1
    return out


def test_saves_one_point_per_day_of_the_month(db_session):
    user, acct = _seed(db_session)
    with patch(ENGINE, side_effect=lambda db, u, a, s, e, **kw: _fake(s, e)) as eng:
        row = ensure_month_baseline(db_session, user.id, acct.id, date(2026, 10, 1))
    assert eng.call_args.args[3:5] == (date(2026, 10, 1), date(2026, 10, 31))
    pts = baseline_points(row)
    assert len(pts) == 31
    assert pts[0] == {"date": "2026-10-01", "projected_balance": "1000.00"}
    assert pts[-1]["date"] == "2026-10-31"
    assert row.taken_on == date(2026, 10, 1)
    assert row.forecasted_open == Decimal("1000.00")
    assert row.forecasted_close == Decimal("970.00")


def test_second_call_returns_the_same_row_unchanged(db_session):
    user, acct = _seed(db_session)
    with patch(ENGINE, side_effect=lambda db, u, a, s, e, **kw: _fake(s, e)):
        first = ensure_month_baseline(db_session, user.id, acct.id, date(2026, 10, 1))
    with patch(ENGINE, side_effect=lambda db, u, a, s, e, **kw: _fake(s, e, base="5.00")) as eng:
        second = ensure_month_baseline(db_session, user.id, acct.id, date(2026, 10, 3))
    assert eng.call_count == 0
    assert second.id == first.id
    assert baseline_points(second)[0]["projected_balance"] == "1000.00"
    assert second.taken_on == date(2026, 10, 1)
    assert db_session.query(models.MonthlyForecastSnapshot).count() == 1


def test_save_window_day_7_creates_day_8_does_not(db_session):
    user, acct = _seed(db_session)
    with patch(ENGINE, side_effect=lambda db, u, a, s, e, **kw: _fake(s, e)):
        assert ensure_month_baseline(db_session, user.id, acct.id, date(2026, 10, 7)) is not None
        assert ensure_month_baseline(db_session, user.id, acct.id, date(2026, 11, 8)) is None
    assert get_month_baseline(db_session, user.id, acct.id, 2026, 11) is None


def test_existing_row_is_returned_even_after_the_window(db_session):
    user, acct = _seed(db_session)
    with patch(ENGINE, side_effect=lambda db, u, a, s, e, **kw: _fake(s, e)):
        ensure_month_baseline(db_session, user.id, acct.id, date(2026, 10, 2))
        assert ensure_month_baseline(db_session, user.id, acct.id, date(2026, 10, 20)) is not None


def test_real_engine_produces_a_full_month(db_session):
    user, acct = _seed(db_session)
    row = ensure_month_baseline(db_session, user.id, acct.id, date(2026, 10, 1))
    assert [p["date"] for p in baseline_points(row)][:2] == ["2026-10-01", "2026-10-02"]
    assert len(baseline_points(row)) == 31


def test_malformed_points_read_as_none(db_session):
    user, acct = _seed(db_session)
    row = models.MonthlyForecastSnapshot(user_id=user.id, account_id=acct.id, year=2026, month=10,
                                         forecasted_open=Decimal("0"), forecasted_close=Decimal("0"),
                                         daily_points="not json")
    db_session.add(row); db_session.commit()
    assert baseline_points(row) is None
    assert baseline_points(None) is None


def test_ensure_for_all_covers_active_checking_only_and_survives_a_failure(db_session):
    user, acct = _seed(db_session)
    other_user, other_acct = _seed(db_session, username="fb2")
    savings = models.Account(user_id=user.id, name="Sav", type=models.AccountType.savings)
    closed = models.Account(user_id=user.id, name="Old", type=models.AccountType.checking, is_active=False)
    db_session.add_all([savings, closed]); db_session.commit()

    def engine(db, u, a, s, e, **kw):
        if a == other_acct.id:
            raise RuntimeError("boom")
        return _fake(s, e)

    with patch(ENGINE, side_effect=engine):
        assert ensure_baselines_for_all(db_session, date(2026, 10, 1)) == 1
    saved = {r.account_id for r in db_session.query(models.MonthlyForecastSnapshot).all()}
    assert saved == {acct.id}


def test_active_bank_connection_and_sync_not_succeeded_today_creates_nothing(db_session):
    user, acct = _seed(db_session)
    _connect_bank(db_session, user)
    with patch(ENGINE, side_effect=lambda db, u, a, s, e, **kw: _fake(s, e)) as eng, \
         patch(SUCCEEDED_TODAY, return_value=False):
        row = ensure_month_baseline(db_session, user.id, acct.id, date(2026, 10, 1))
    assert row is None
    assert eng.call_count == 0
    assert get_month_baseline(db_session, user.id, acct.id, 2026, 10) is None


def test_active_bank_connection_and_sync_succeeded_today_creates(db_session):
    user, acct = _seed(db_session)
    _connect_bank(db_session, user)
    with patch(ENGINE, side_effect=lambda db, u, a, s, e, **kw: _fake(s, e)), \
         patch(SUCCEEDED_TODAY, return_value=True):
        row = ensure_month_baseline(db_session, user.id, acct.id, date(2026, 10, 1))
    assert row is not None
    assert get_month_baseline(db_session, user.id, acct.id, 2026, 10) is not None


def test_no_bank_connection_creates_without_consulting_sync_state(db_session):
    user, acct = _seed(db_session)
    with patch(ENGINE, side_effect=lambda db, u, a, s, e, **kw: _fake(s, e)), \
         patch(SUCCEEDED_TODAY) as synced:
        row = ensure_month_baseline(db_session, user.id, acct.id, date(2026, 10, 1))
    assert row is not None
    assert synced.call_count == 0


def test_disconnected_bank_connection_is_not_gated(db_session):
    user, acct = _seed(db_session)
    _connect_bank(db_session, user, status=models.BankConnectionStatus.disconnected)
    with patch(ENGINE, side_effect=lambda db, u, a, s, e, **kw: _fake(s, e)), \
         patch(SUCCEEDED_TODAY, return_value=False) as synced:
        row = ensure_month_baseline(db_session, user.id, acct.id, date(2026, 10, 1))
    assert row is not None
    assert synced.call_count == 0


def test_existing_row_plus_sync_not_succeeded_still_returns_existing_row(db_session):
    user, acct = _seed(db_session)
    with patch(ENGINE, side_effect=lambda db, u, a, s, e, **kw: _fake(s, e)):
        first = ensure_month_baseline(db_session, user.id, acct.id, date(2026, 10, 1))
    _connect_bank(db_session, user)
    with patch(ENGINE, side_effect=lambda db, u, a, s, e, **kw: _fake(s, e, base="5.00")) as eng, \
         patch(SUCCEEDED_TODAY, return_value=False):
        second = ensure_month_baseline(db_session, user.id, acct.id, date(2026, 10, 3))
    assert eng.call_count == 0
    assert second.id == first.id


def test_save_race_returns_existing_row_instead_of_raising(db_session):
    user, acct = _seed(db_session)
    real_get = get_month_baseline
    calls = {"n": 0}

    def racing_get(db, user_id, account_id, year, month):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return real_get(db, user_id, account_id, year, month)

    # Simulate a second caller inserting the row after our check but before
    # our insert: seed the row directly, then let the real insert race it.
    with patch(ENGINE, side_effect=lambda db, u, a, s, e, **kw: _fake(s, e)):
        winner = ensure_month_baseline(db_session, user.id, acct.id, date(2026, 10, 1))
    with patch("backend.services.forecast_baseline.get_month_baseline", side_effect=racing_get), \
         patch(ENGINE, side_effect=lambda db, u, a, s, e, **kw: _fake(s, e, base="5.00")) as eng:
        loser = ensure_month_baseline(db_session, user.id, acct.id, date(2026, 10, 3))
    assert loser.id == winner.id
    assert db_session.query(models.MonthlyForecastSnapshot).count() == 1
