"""CRITICAL review finding: "match wins over skip" was only enforced inside
recurring_floating_status.py's own status computation -- i.e. only when
something called GET /recurring/floating-status for that exact item/year/
month. month_base.build_month_base and forecast_engine.build_forecast both
read the RecurringSkip table directly, with no awareness that a real
transaction had already linked, so the reviewer's reproduction (skip
November, then import a transaction dated Nov 12) left the real linked
spend silently excluded from Leftover and the forecast until someone
happened to open the Recurring page for that exact month.

effective_skips() (backend/services/recurring_skips.py) is now the one
place all three callers ask "is this skip still true" -- these tests prove
they agree, without calling the status endpoint first."""
from datetime import date
from decimal import Decimal
from backend import models
from backend.services.available_to_spend import available_to_spend
from backend.services.forecast_engine import build_forecast
from backend.services.month_base import build_month_base
from backend.services.recurring_skips import effective_skips

D = Decimal


def _floating_item(user, account, **overrides) -> models.RecurringItem:
    kwargs = dict(
        user_id=user.id, account_id=account.id, name="Test Cleaning Co",
        amount=D("150.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=0,
        start_date=date(2026, 1, 1), is_floating=True,
    )
    kwargs.update(overrides)
    return models.RecurringItem(**kwargs)


def test_effective_skips_excludes_a_month_with_a_linked_checking_match(db_session, test_user, test_account):
    item = _floating_item(test_user, test_account)
    db_session.add(item)
    db_session.flush()
    db_session.add(models.RecurringSkip(user_id=test_user.id, recurring_item_id=item.id, year=2026, month=11))
    db_session.add(models.Transaction(
        user_id=test_user.id, account_id=test_account.id, recurring_item_id=item.id,
        date=date(2026, 11, 12), amount=D("-150.00"), description="Test Cleaning Co payment",
        is_actual=True,
    ))
    db_session.commit()

    out = effective_skips(db_session, test_user.id, [item.id], year=2026, month=11)
    assert out == set()


def test_effective_skips_excludes_a_month_with_a_linked_card_match(db_session, test_user, test_account, test_card):
    item = _floating_item(test_user, test_account, name="Test Haircut", amount=D("45.00"), card_id=test_card.id)
    db_session.add(item)
    db_session.flush()
    db_session.add(models.RecurringSkip(user_id=test_user.id, recurring_item_id=item.id, year=2026, month=11))
    db_session.add(models.CreditCardTransaction(
        card_id=test_card.id, user_id=test_user.id, recurring_item_id=item.id,
        date=date(2026, 11, 10), amount=D("45.00"), merchant="Test Barber Shop",
    ))
    db_session.commit()

    out = effective_skips(db_session, test_user.id, [item.id], year=2026, month=11)
    assert out == set()


def test_effective_skips_keeps_a_skip_with_no_match(db_session, test_user, test_account):
    item = _floating_item(test_user, test_account)
    db_session.add(item)
    db_session.flush()
    db_session.add(models.RecurringSkip(user_id=test_user.id, recurring_item_id=item.id, year=2026, month=11))
    db_session.commit()

    out = effective_skips(db_session, test_user.id, [item.id], year=2026, month=11)
    assert out == {(item.id, 2026, 11)}


def test_month_base_honors_a_match_over_a_stale_skip_without_the_status_endpoint(db_session, test_user, test_account):
    """The reviewer's exact reproduction: skip November, then import a
    matching transaction dated Nov 12 -- build_month_base must not exclude
    the item just because the (now-stale) skip row is still sitting there."""
    item = _floating_item(test_user, test_account)
    db_session.add(item)
    db_session.flush()
    db_session.add(models.RecurringSkip(user_id=test_user.id, recurring_item_id=item.id, year=2026, month=11))
    db_session.add(models.Transaction(
        user_id=test_user.id, account_id=test_account.id, recurring_item_id=item.id,
        date=date(2026, 11, 12), amount=D("-150.00"), description="Test Cleaning Co payment",
        is_actual=True,
    ))
    db_session.commit()

    base = build_month_base(db_session, test_user, 2026, 11)
    assert any(o.recurring_item_id == item.id for o in base.monthly_bills)
    assert base.expense_total == D("150.00")
    assert base.monthly_bills_total == D("150.00")

    # The stale skip row is still in the database (recurring_floating_status.py
    # no longer deletes it as a read side effect) -- it just has no effect.
    assert db_session.query(models.RecurringSkip).filter_by(recurring_item_id=item.id).count() == 1


def test_forecast_engine_honors_a_match_over_a_stale_skip_without_the_status_endpoint(db_session, test_user, test_account):
    """Same reproduction as month_base, for the sibling path that this
    codebase has a known failure mode of disagreeing with it (dashboard vs.
    forecast vs. month-in-review)."""
    item = _floating_item(test_user, test_account)
    db_session.add(item)
    db_session.flush()
    db_session.add(models.RecurringSkip(user_id=test_user.id, recurring_item_id=item.id, year=2026, month=11))
    db_session.add(models.Transaction(
        user_id=test_user.id, account_id=test_account.id, recurring_item_id=item.id,
        date=date(2026, 11, 12), amount=D("-150.00"), description="Test Cleaning Co payment",
        is_actual=True,
    ))
    db_session.commit()

    entries = build_forecast(db_session, test_user.id, test_account.id, date(2026, 11, 1), date(2026, 11, 30))
    matched = [t for e in entries for t in e.transactions if t.recurring_item_id == item.id]
    assert matched, "the linked actual must still appear in the forecast despite the stale skip row"
    assert matched[0].is_actual is True
    assert matched[0].amount == D("-150.00")


def test_available_to_spend_reflects_the_match_not_the_stale_skip(db_session, test_user, test_account):
    """The consequence the reviewer actually hit: with the bug, the bill's
    amount silently dropped out of Leftover/Available-to-Spend because
    build_month_base still treated the month as skipped -- the real $150.00
    that left checking was accounted for nowhere. Fixed, the bill counts as
    a committed expense exactly once, with no need to open the status
    endpoint first."""
    item = _floating_item(test_user, test_account)
    db_session.add(item)
    db_session.flush()
    db_session.add(models.RecurringSkip(user_id=test_user.id, recurring_item_id=item.id, year=2026, month=11))
    db_session.add(models.Transaction(
        user_id=test_user.id, account_id=test_account.id, recurring_item_id=item.id,
        date=date(2026, 11, 12), amount=D("-150.00"), description="Test Cleaning Co payment",
        is_actual=True,
    ))
    db_session.commit()

    result = available_to_spend(db_session, test_user, date(2026, 11, 20))
    assert result.committed_expenses == D("150.00")
