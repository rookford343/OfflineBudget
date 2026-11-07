"""The standard forecast walk every consumer reads.

One start date and one flag rule, so the Forecast tab, the Dashboard's lows,
the risk banner, the weekly digest, upcoming bills, the Wish List and the
start-of-month baselines draw the same balance for the same day.

- Start: `as_of - WALK_LOOKBACK_DAYS` (the engine's walk horizon). Recurring
  items due since then and still unmatched count as not yet posted.
- Purpose picks `include_unbilled_card_bills`:
  - "display" (True): the Forecast tab's walk. This month's card bills not
    yet charged ride the next card payment.
  - "safety" (False): Safety Margin's walk. It leaves those bills out of the
    card payment because Safety Margin subtracts them itself.

The walk is returned from its start; a caller that only wants as_of onward
slices it. A caller that needs history before the horizon (the Forecast
tab's year views, /monthly-summary) builds its own range: build_forecast
gives every start the same balances from the horizon on
(tests/test_forecast_walk_policy.py).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from sqlalchemy.orm import Session

from backend.schemas import ForecastEntry
from backend.services.forecast_engine import WALK_LOOKBACK_DAYS, build_forecast

WalkPurpose = Literal["display", "safety"]

__all__ = ["WALK_LOOKBACK_DAYS", "WalkPurpose", "standard_walk", "walk_from"]


def standard_walk(
    db: Session, user_id: int, account_id: int, as_of: date, end: date,
    purpose: WalkPurpose = "display", **extra,
) -> list[ForecastEntry]:
    """The standard walk from `as_of - WALK_LOOKBACK_DAYS` through `end`.
    `extra` passes build_forecast keywords through (`overrides`, `proposal`)."""
    if purpose not in ("display", "safety"):
        raise ValueError(f"unknown walk purpose: {purpose!r}")
    return build_forecast(
        db, user_id, account_id, as_of - timedelta(days=WALK_LOOKBACK_DAYS), end,
        include_unbilled_card_bills=(purpose == "display"),
        **extra,
    )


def walk_from(entries: list[ForecastEntry], as_of: date) -> list[ForecastEntry]:
    """The days of a walk on or after `as_of`."""
    return [e for e in entries if e.date >= as_of]
