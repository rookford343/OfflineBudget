"""Track Budgets' figures: what each line may spend and the page headline.

A line's available amount is its Budget plus any rolled-over balance (only
while rollover is on for that category). Each line is held at whole cents
before it is summed, so the headline equals the sum of the lines the page
shows. Moved here from the Budget page, which used to compute it.
"""
from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

from backend import schemas

ZERO = Decimal("0")
CENT = Decimal("0.01")


def _cents(v: Decimal) -> Decimal:
    return v.quantize(CENT, rounding=ROUND_HALF_UP)


def line_available(line: schemas.PlanTrackLine) -> Decimal:
    """Budget plus the rollover balance when rollover is enabled."""
    return _cents(line.budget) + (_cents(line.rollover_balance) if line.rollover_enabled else ZERO)


def track_totals(lines: Iterable[schemas.PlanTrackLine]) -> schemas.TrackTotals:
    lines = list(lines)
    budgeted = sum((_cents(ln.budget) for ln in lines), ZERO)
    available = sum((line_available(ln) for ln in lines), ZERO)
    spent = sum((_cents(ln.actual_total) for ln in lines), ZERO)
    return schemas.TrackTotals(
        budgeted=budgeted,
        available=available,
        spent=spent,
        left=available - spent,
        pct=spent / available * 100 if available > ZERO else ZERO,
        over_count=sum(1 for ln in lines if _cents(ln.actual_total) > line_available(ln)),
    )
