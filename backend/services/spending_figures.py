"""Spending page figures the frontend used to work out for itself.

* `direct_actual`: what is filed on a parent category itself rather than on
  one of its children.
* `mean_total`: the average line on the monthly spending bars.
* `monthly_averages`: each category's mean monthly total over the full months
  in a monthly-by-category response. The current calendar month is partial, so
  it is left out; a full month with nothing for a category still counts as $0,
  and months the response doesn't contain are not invented.
"""
from __future__ import annotations
from decimal import Decimal
from typing import Mapping

ZERO = Decimal("0")


def direct_actual(parent_breakdown: Mapping[str, Decimal]) -> Decimal:
    """A parent's own spend: its by-source breakdown, children excluded."""
    return sum(parent_breakdown.values(), ZERO)


def mean_total(totals: list[Decimal]) -> Decimal | None:
    """Mean of the monthly bars; None unless there is more than one month."""
    return sum(totals, ZERO) / len(totals) if len(totals) > 1 else None


def monthly_averages(
    month_totals: Mapping[str, Mapping[int, Decimal]], current_month: str,
) -> dict[int, Decimal] | None:
    """{category_id: mean monthly total} over the months other than
    `current_month` ("YYYY-MM"); None when no full month is present."""
    full = [m for m in month_totals if m != current_month]
    if not full:
        return None
    ids = {cid for m in month_totals.values() for cid in m}
    return {
        cid: sum((month_totals[m].get(cid, ZERO) for m in full), ZERO) / len(full)
        for cid in ids
    }
