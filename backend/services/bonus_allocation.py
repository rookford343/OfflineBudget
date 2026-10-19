"""Bonus allocation: when an annual bonus lands, move part of it straight to
savings accounts the user chose, on the same day (see models.BonusAllocationStep
and models.User.bonus_shortfall_account_id / bonus_shortfall_round_to).

split_bonus() is the pure waterfall math; allocation_transfers() walks every
BonusPlan to find payouts in a window and groups+splits them per source
account/date. forecast_engine.py injects the result into the day walk the
same way it injects PlannedTransfer rows.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_FLOOR, Decimal

from sqlalchemy.orm import Session

from backend import models

CENT = Decimal("0.01")


def round_down(amount: Decimal, to: Decimal | None) -> Decimal:
    """Floor `amount` to a multiple of `to` when `to` is set and > 0,
    otherwise just floor to cents (not the default ROUND_HALF_EVEN quantize
    -- this is a floor in both cases, never rounds up)."""
    if to is not None and to > 0:
        steps = (amount / to).to_integral_value(rounding=ROUND_FLOOR)
        return (steps * to).quantize(CENT)
    return amount.quantize(CENT, rounding=ROUND_FLOOR)


def split_bonus(
    total: Decimal,
    steps: list,
    shortfall_account_id: int | None,
    shortfall_round_to: Decimal | None,
) -> list[tuple[int, Decimal]]:
    """Waterfall `total` across `steps` (in position order), returning
    (account_id, amount) pairs. Whatever isn't moved stays in checking."""
    fixed_needed = sum((s.value for s in steps if s.kind == "fixed"), Decimal("0"))

    if total < fixed_needed and shortfall_account_id is not None:
        amt = round_down(total, shortfall_round_to)
        return [(shortfall_account_id, amt)] if amt > 0 else []

    results: list[tuple[int, Decimal]] = []
    remaining = total
    for s in steps:
        if s.kind == "fixed":
            amt = round_down(min(s.value, remaining), s.round_to)
        elif s.kind == "percent":
            amt = round_down(total * s.value / 100, s.round_to)
            amt = min(amt, remaining)
        else:  # rest
            amt = round_down(remaining, s.round_to)
        remaining -= amt
        if amt == 0:
            continue
        results.append((s.account_id, amt))
    return results


@dataclass(frozen=True)
class AllocationTransfer:
    from_account_id: int
    to_account_id: int
    amount: Decimal
    to_name: str
    from_name: str


def allocation_transfers(
    db: Session, user: models.User, start: date, end: date,
    override_map: dict[int, Decimal] | None = None,
) -> dict[date, list[AllocationTransfer]]:
    """Every bonus payout in [start, end], grouped by (shifted payout date,
    source account) and split per the user's steps/shortfall settings.

    `override_map` is forecast_engine.build_forecast's own recurring_item_id
    -> amount_delta map (scenario overrides) -- passed through so a scenario
    that changes a bonus's amount changes what gets split too, instead of
    this always splitting the real, unmodified net."""
    # Deferred imports -- forecast_engine.py imports this module at call time
    # (to splice the result into its day walk), so importing it back at
    # module scope here would be a circular import.
    from backend.services.bonus_plans import bonus_gross, bonus_net, is_bonus_shaped, payout_date, plans_by_item
    from backend.services.forecast_engine import _adjust_for_weekend

    override_map = override_map or {}

    steps = (
        db.query(models.BonusAllocationStep)
        .filter(models.BonusAllocationStep.user_id == user.id)
        .order_by(models.BonusAllocationStep.position)
        .all()
    )
    shortfall_account_id = user.bonus_shortfall_account_id
    shortfall_round_to = user.bonus_shortfall_round_to
    if not steps and shortfall_account_id is None:
        return {}

    # Active accounts only -- a step, the shortfall account, or a bonus
    # item's own account that's been deactivated since is skipped below
    # rather than moving money to/from a closed account.
    accounts = {
        a.id: a for a in db.query(models.Account).filter(
            models.Account.user_id == user.id, models.Account.is_active == True,
        ).all()
    }
    steps = [s for s in steps if s.account_id in accounts]
    if shortfall_account_id is not None and shortfall_account_id not in accounts:
        shortfall_account_id = None
        shortfall_round_to = None
    if not steps and shortfall_account_id is None:
        return {}

    groups: dict[tuple[date, int], Decimal] = {}
    for item_id, plan in plans_by_item(db, user.id).items():
        item = plan.recurring_item
        # Mirrors build_forecast's own filters exactly: is_bonus_shaped +
        # is_active (the plan/forecast guard), include_in_forecast (the
        # engine drops these from the day walk entirely -- see
        # build_forecast's recurring_items comprehension), and now the
        # item's own account must still be active too.
        if not is_bonus_shaped(item) or not item.is_active or not item.include_in_forecast:
            continue
        if item.account_id not in accounts:
            continue

        actual_dates = [
            t.date for t in db.query(models.Transaction).filter(
                models.Transaction.user_id == user.id,
                models.Transaction.recurring_item_id == item.id,
                models.Transaction.is_actual == True,
            ).all()
        ]

        # end.year + 1 covers a Jan 1/2/3 payout that shifts back onto Dec
        # 29-31 of end.year -- the shift only ever moves a date EARLIER, so
        # start.year - 1 could never shift forward into the window.
        for year in range(start.year, end.year + 2):
            natural_date = payout_date(item, year)
            if item.start_date > natural_date:
                continue
            if item.end_date and item.end_date < natural_date:
                continue
            shifted_date = _adjust_for_weekend(natural_date)
            if shifted_date < start or shifted_date > end:
                continue
            # Mirrors build_forecast's two actual-suppression checks: the
            # shifted (Friday) date's month in general, AND the natural
            # Sat/Sun date's own month specifically -- a shift that crosses
            # a month boundary (e.g. a May 1 Saturday payout pulled back to
            # Apr 30) would otherwise miss an actual dated on the real May 1.
            if any(
                (d.year == shifted_date.year and d.month == shifted_date.month)
                or (d.year == natural_date.year and d.month == natural_date.month)
                for d in actual_dates
            ):
                continue

            gross = bonus_gross(plan, user, year)
            if gross is None:
                continue
            net = bonus_net(plan, gross) + override_map.get(item.id, Decimal("0"))
            if net <= 0:
                continue

            key = (shifted_date, item.account_id)
            groups[key] = groups.get(key, Decimal("0")) + net

    result: dict[date, list[AllocationTransfer]] = {}
    for (d, source_account_id), total in groups.items():
        for dest_account_id, amount in split_bonus(total, steps, shortfall_account_id, shortfall_round_to):
            if dest_account_id == source_account_id:
                continue
            from_acct = accounts.get(source_account_id)
            to_acct = accounts.get(dest_account_id)
            result.setdefault(d, []).append(AllocationTransfer(
                from_account_id=source_account_id,
                to_account_id=dest_account_id,
                amount=amount,
                to_name=to_acct.name if to_acct else "",
                from_name=from_acct.name if from_acct else "",
            ))
    return result
