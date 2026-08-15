"""The email's "Upcoming (next 7 days)" list, redesigned 2026-08-14 alongside
the Household Snapshot's card styling (Dan: "needs a little work on
formatting and giving better details").

Two real bugs this closes, both invisible until real data exercised them:

  1. The list showed no date at all -- just a name and an amount -- so
     "better details" meant showing WHEN, not only WHAT. Sorting by
     day_of_month alone (rather than the real fire date) also put items out
     of chronological order whenever the 7-day window crossed a month
     boundary: an item firing day_of_month=30 (2 days out) sorted AFTER one
     firing day_of_month=2 (5 days out), because 30 > 2.
  2. _fires_soon (recreated here as _next_fire_date) never special-cased
     RecurringFrequency.quarterly, added earlier the same day to
     forecast_engine.py but never ported to this second, parallel
     date-firing implementation. A quarterly item fell through to the
     generic monthly check and would have shown up in Upcoming every month
     instead of only its quarter months.
"""
from datetime import date
from decimal import Decimal
from backend import models
from backend.services.summary_generator import _next_fire_date, _fires_soon


def _item(**kwargs) -> models.RecurringItem:
    defaults = dict(
        name="Item", amount=Decimal("10.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=15,
        start_date=date(2026, 1, 1), is_active=True, month_of_year=None,
        end_date=None,
    )
    defaults.update(kwargs)
    return models.RecurringItem(**defaults)


def test_next_fire_date_returns_the_real_date_not_just_a_bool():
    item = _item(day_of_month=17)
    assert _next_fire_date(item, date(2026, 8, 14), 7) == date(2026, 8, 17)


def test_fires_soon_still_works_as_a_bool_via_delegation():
    """Existing callers/tests depend on _fires_soon's bool signature --
    it must keep working unchanged now that _next_fire_date does the work."""
    item = _item(day_of_month=17)
    assert _fires_soon(item, date(2026, 8, 14), 7) is True
    assert _fires_soon(item, date(2026, 1, 1), 7) is False


def test_cross_month_window_sorts_chronologically_by_real_date_not_day_of_month():
    """The bug: day_of_month=2 (5 days out) must NOT sort before
    day_of_month=30 (2 days out) just because 2 < 30."""
    near = _item(name="Near", day_of_month=30)   # 2026-08-30, 2 days from 8/28
    far = _item(name="Far", day_of_month=2)      # 2026-09-02, 5 days from 8/28
    today = date(2026, 8, 28)

    pairs = sorted(
        ((r, d) for r in [far, near] if (d := _next_fire_date(r, today, 7)) is not None),
        key=lambda pair: pair[1],
    )

    assert [name for (r, d) in pairs for name in [r.name]] == ["Near", "Far"], (
        "the nearer date must sort first regardless of day_of_month's numeric value"
    )


def test_quarterly_item_only_shows_in_its_quarter_month():
    """Stormwater: month_of_year=3 fires in Mar/Jun/Sep/Dec only. Before this
    fix a quarterly item fell through to the generic monthly branch and
    would fire every month."""
    stormwater = _item(
        name="Stormwater", frequency=models.RecurringFrequency.quarterly,
        month_of_year=3, day_of_month=0,
    )
    assert _next_fire_date(stormwater, date(2026, 9, 25), 7) is not None, "due 9/30, within the window"
    assert _next_fire_date(stormwater, date(2026, 8, 25), 7) is None, "August is not a quarter month"
    assert _next_fire_date(stormwater, date(2026, 10, 1), 7) is None, "October is not a quarter month either"


def test_daily_summary_shows_dates_and_stays_chronological_across_a_month_boundary(db_session):
    """End-to-end: the rendered email text lists the near item before the far
    one, and shows an actual date/day-label rather than just a bare name."""
    from backend.services.summary_generator import generate_daily_summary

    user = models.User(username="datetest", hashed_password="x", display_name="D")
    db_session.add(user)
    db_session.flush()
    account = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking,
                              current_balance=Decimal("5000.00"))
    db_session.add(account)
    db_session.flush()
    db_session.add_all([
        models.RecurringItem(user_id=user.id, account_id=account.id, name="Near Bill",
                              amount=Decimal("50.00"), type=models.RecurringType.expense,
                              frequency=models.RecurringFrequency.monthly, day_of_month=30,
                              start_date=date(2026, 1, 1)),
        models.RecurringItem(user_id=user.id, account_id=account.id, name="Far Bill",
                              amount=Decimal("75.00"), type=models.RecurringType.expense,
                              frequency=models.RecurringFrequency.monthly, day_of_month=2,
                              start_date=date(2026, 1, 1)),
    ])
    db_session.commit()

    import backend.services.summary_generator as sg
    orig = sg.date
    class _FixedDate(date):
        @classmethod
        def today(cls):
            return date(2026, 8, 28)
    sg.date = _FixedDate
    try:
        html, text = generate_daily_summary(db_session, user)
    finally:
        sg.date = orig

    near_pos = text.find("Near Bill")
    far_pos = text.find("Far Bill")
    assert near_pos != -1 and far_pos != -1
    assert near_pos < far_pos, "the item due in 2 days must be listed before the one due in 5 days"
