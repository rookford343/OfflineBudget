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
from decimal import Decimal
from typing import Literal

from sqlalchemy.orm import Session

from backend import models
from backend.schemas import ForecastEntry
from backend.services.card_matching import card_matches_description
from backend.services.forecast_engine import (
    WALK_LOOKBACK_DAYS, build_forecast, find_balance_risk, risk_status,
)

WalkPurpose = Literal["display", "safety"]

__all__ = [
    "WALK_LOOKBACK_DAYS", "WalkPurpose", "floor_entries", "floor_mask", "walk_risk", "standard_walk", "walk_from",
]


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


def floor_mask(days, active_cards) -> list[bool]:
    """Per forecast day: may it be the reported floor? False from a locked
    card-payoff day (projected is_cc_locked, or a real card-matching payoff)
    through to the next income day -- the Dashboard's Safety Margin rule."""
    def _is_payoff_day(day) -> bool:
        if any(t.is_cc_locked for t in day.transactions):
            return True
        return any(
            t.is_actual and t.amount < 0
            and any(card_matches_description(card, t.name) for card in active_cards)
            for t in day.transactions
        )
    mask, in_locked_dip = [], False
    for day in days:
        if _is_payoff_day(day):
            in_locked_dip = True
        if any(t.type == "income" and t.amount > 0 for t in day.transactions):
            in_locked_dip = False
        mask.append(not in_locked_dip)
    return mask


def floor_entries(
    db: Session, user_id: int, walk: list[ForecastEntry], start: date,
) -> list[ForecastEntry]:
    """The days on or after `start` that may be a reported floor: the mask is
    computed over the FULL `walk` (so a locked payoff before `start` still
    masks the days up to the next income day, as in the Dashboard's
    `_lookahead_window`), then the days are cut to `start` onward. If every
    such day is masked, all of them are returned, as `_floor_minimum` does.
    The risk banner and the weekly digest read this."""
    active_cards = db.query(models.CreditCard).filter(
        models.CreditCard.user_id == user_id,
        models.CreditCard.is_active == True,
    ).all()
    mask = floor_mask(walk, active_cards)
    window = [(e, ok) for e, ok in zip(walk, mask) if e.date >= start]
    return [e for e, ok in window if ok] or [e for e, _ in window]


def walk_risk(
    db: Session, user_id: int, walk: list[ForecastEntry], start: date, cushion: Decimal,
) -> tuple[dict, str]:
    """The risk banner's (risk dict, status) for `walk` from `start`.

    Amber (below the cushion) skips locked statement-payoff dips (`floor_entries`).
    An actual overdraft never does: if the floor reads below $0 the usual
    first-breach date and amount stand; if only a locked day goes below $0, the
    status is "danger" with that first negative day's date and amount."""
    floor = floor_entries(db, user_id, walk, start)
    risk, status = find_balance_risk(floor, cushion), risk_status(floor, cushion)
    if status != "danger":
        overdraft = find_balance_risk(walk_from(walk, start), Decimal("0"))
        if overdraft["at_risk"]:
            risk = {**overdraft, "threshold": cushion}
            status = "danger"
    return risk, status


def checkpoint_delta(saved: Decimal | None, forecast_close: Decimal) -> Decimal | None:
    """A saved quarter-end balance minus the forecast close; None without a
    saved balance."""
    return None if saved is None else saved - forecast_close
