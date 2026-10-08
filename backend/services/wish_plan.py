"""Wish List fit engine. Spec: docs/superpowers/specs/2026-10-07-wish-list-design.md

One baseline forecast; every wish is a cumulative-delta array laid on top.
A flow on date x changes the balance on x and every later day, so its
cumulative array is 0 before x and the flow amount from x on."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Callable

ZERO = Decimal("0")


def cum_from_flows(dates: list[date], flows: list[tuple[date, Decimal]]) -> list[Decimal]:
    if not dates:
        return []
    first, last = dates[0], dates[-1]
    per_day = {}
    for d, amt in flows:
        if d > last:
            continue
        key = max(d, first)
        per_day[key] = per_day.get(key, ZERO) + Decimal(amt)
    out, running = [], ZERO
    for d in dates:
        running += per_day.get(d, ZERO)
        out.append(running)
    return out


def low_point(base, mask, dates, overlays, from_idx):
    best = None
    for i in range(from_idx, len(dates)):
        if not mask[i]:
            continue
        v = base[i] + sum((o[i] for o in overlays), ZERO)
        if best is None or v < best[0]:
            best = (v, i)
    if best is None:  # every day masked: fall back to the raw minimum, like _lookahead_minimum
        for i in range(from_idx, len(dates)):
            v = base[i] + sum((o[i] for o in overlays), ZERO)
            if best is None or v < best[0]:
                best = (v, i)
    return best


def earliest_safe_date(dates, base, mask, prior: list[Decimal], flows_for: Callable[[date], list], cushion: Decimal,
                       first_idx: int, last_idx: int) -> dict:
    """First buy date in [first_idx, last_idx] whose low point from THAT day
    through the horizon (spec: low_point over [d, horizon]), with prior wishes
    and this option applied, stays at or above the cushion. Every flow an
    option produces lands on or after its buy date (a card purchase lands
    later, on the payoff date), so a dip before the buy date can't be caused
    by this purchase and is correctly ignored."""
    best = None
    for i in range(first_idx, last_idx + 1):
        cum = cum_from_flows(dates, flows_for(dates[i]))
        lp = low_point(base, mask, dates, [prior, cum], i)
        if lp is None:
            continue
        low, low_i = lp
        if best is None or low > best[0]:
            best = (low, i)
        if low >= cushion:
            return {"safe_date": dates[i], "low": low, "low_date": dates[low_i],
                    "best_date": dates[i], "best_low": low, "shortfall": ZERO}
    if best is None:
        return {"safe_date": None, "low": None, "low_date": None, "best_date": None,
                "best_low": None, "shortfall": None}
    return {"safe_date": None, "low": None, "low_date": None, "best_date": dates[best[1]],
            "best_low": best[0], "shortfall": cushion - best[0]}


from backend import models
from backend.services.budget_snapshot import floor_mask
from backend.services.forecast_engine import build_forecast
from backend.services.scenario_service import resolve_scenario
from backend.services.wish_math import option_flows, total_cost, monthly_payment

HORIZON_DAYS = 365
LAST_BUY_OFFSET = 30


def effective_cushion(db, user, account_id) -> Decimal:
    row = db.query(models.WishSettings).filter(models.WishSettings.user_id == user.id).first()
    if row is not None and row.cushion is not None:
        return Decimal(row.cushion)
    acct = db.get(models.Account, account_id)
    if acct is not None and acct.low_balance_threshold is not None:
        return Decimal(acct.low_balance_threshold)
    return Decimal("1000")


def _series(db, user_id, account_id, today, end, proposal=None, overrides=None):
    days = build_forecast(db, user_id, account_id, today - timedelta(days=45), end,
                          overrides=overrides, proposal=proposal, include_unbilled_card_bills=False)
    return [d for d in days if d.date >= today]


def build_plan(db, user, account_id, today: date) -> dict:
    end = today + timedelta(days=HORIZON_DAYS)
    base_days = _series(db, user.id, account_id, today, end)
    dates = [d.date for d in base_days]
    base = [Decimal(d.projected_balance) for d in base_days]
    cards = {c.id: c for c in db.query(models.CreditCard).filter(models.CreditCard.user_id == user.id).all()}
    active_cards = [c for c in cards.values() if c.is_active]
    mask = floor_mask(base_days, active_cards)
    cushion = effective_cushion(db, user, account_id)
    last_idx = max(0, len(dates) - 1 - LAST_BUY_OFFSET)
    zero = [ZERO] * len(dates)
    prior = list(zero)

    items = db.query(models.WishItem).filter(models.WishItem.user_id == user.id).order_by(
        models.WishItem.rank, models.WishItem.id).all()
    out = []
    for item in items:
        sc = item.scenario
        committed = sc.status == "committed"
        blocks = zero
        if not committed:
            resolved = resolve_scenario(db, user.id, sc.id)
            if resolved is not None:
                overrides, proposal = resolved
                if proposal.items or proposal.expenses or overrides:
                    alt = _series(db, user.id, account_id, today, end, proposal=proposal, overrides=overrides)
                    alt_by = {d.date: Decimal(d.projected_balance) for d in alt}
                    blocks = [alt_by.get(dt, b) - b for dt, b in zip(dates, base)]
        item_prior = [p + b for p, b in zip(prior, blocks)]
        opts_out = []
        options = list(item.options) or [None]
        none_fit = {"safe_date": None, "low": None, "low_date": None, "best_date": None,
                    "best_low": None, "shortfall": None}
        for opt in options:
            error = None
            if opt is None:
                opt_monthly_payment = None
                opt_total_cost = ZERO
                fit = none_fit if committed else earliest_safe_date(
                    dates, base, mask, item_prior, lambda d: [], cushion, 0, last_idx)
            else:
                try:
                    opt_monthly_payment = monthly_payment(item, opt)
                    opt_total_cost = total_cost(item, opt)
                    if committed:
                        fit = none_fit
                    else:
                        flows_for = lambda d, o=opt: option_flows(item, o, d, cards)
                        fit = earliest_safe_date(dates, base, mask, item_prior, flows_for, cushion, 0, last_idx)
                except ValueError as e:
                    error = str(e)
                    opt_monthly_payment = None
                    opt_total_cost = None
                    fit = none_fit
            opts_out.append({
                "option_id": opt.id if opt is not None else None,
                "label": opt.label if opt is not None else "Extra costs only",
                "method": opt.method.value if opt is not None else None,
                "monthly_payment": opt_monthly_payment,
                "total_cost": opt_total_cost,
                "error": error,
                **fit,
            })
        plan_opt = None
        if item.plan_option_id is not None:
            plan_opt = next(
                (o for o in opts_out if o["option_id"] == item.plan_option_id and o["error"] is None), None)
        if plan_opt is None:
            fitting = [o for o in opts_out if o["error"] is None and o["safe_date"] is not None]
            if fitting:
                plan_opt = min(fitting, key=lambda o: (o["safe_date"], o["total_cost"]))
            else:
                # Prefer any error-free option over opts_out[0], which may be
                # the errored one -- an option that merely doesn't fit within
                # the horizon is still a better fallback than one that
                # couldn't even be priced. If every option errored, opts_out[0]
                # is used only as a placeholder; `fits` below stays False
                # because its "error" is never None.
                plan_opt = next((o for o in opts_out if o["error"] is None), opts_out[0])

        # Ruling: a target_date before today is stale (the window to act on it
        # has already passed) and is treated as unset -- placement falls back
        # to the engine's own safe date, and the item reports that it did so.
        raw_target = item.target_date
        target_ignored = raw_target is not None and raw_target < today
        valid_target = raw_target if (raw_target is not None and not target_ignored) else None

        placement = valid_target or plan_opt["safe_date"]
        fits = placement is not None and not committed and plan_opt["error"] is None
        explain = None
        target_low = None
        target_shortfall = None
        if fits:
            opt_obj = next((o for o in item.options if o.id == plan_opt["option_id"]), None)
            cum = cum_from_flows(dates, option_flows(item, opt_obj, placement, cards)) if opt_obj else zero
            place_idx = next((k for k, dt in enumerate(dates) if dt >= placement), len(dates) - 1)
            lp = low_point(base, mask, dates, [item_prior, cum], place_idx)
            if lp is not None:
                low, li = lp
                using_target = valid_target is not None
                explain = {
                    "title": "Your chosen date" if using_target else "Earliest safe date",
                    "result": str(low),
                    "rows": [
                        {"op": "start", "label": f"Projected balance on {dates[li].isoformat()}", "amount": str(base[li])},
                        {"op": "add", "label": "Wishes ranked above this one", "amount": str(prior[li])},
                        {"op": "add", "label": "This item's extra costs", "amount": str(blocks[li])},
                        {"op": "add", "label": "This option's payments by then", "amount": str(cum[li])},
                        {"op": "result", "label": f"Low point (cushion {cushion})", "amount": str(low)},
                    ],
                }
                if using_target:
                    target_low = low
                    target_shortfall = (cushion - low) if low < cushion else ZERO
            prior = [p + c for p, c in zip(item_prior, cum)]
        out.append({
            "id": item.id, "scenario_id": sc.id, "name": sc.name, "rank": item.rank, "status": sc.status,
            "price": Decimal(item.price), "trade_in_value": Decimal(item.trade_in_value),
            "trade_in_on": item.trade_in_on, "target_date": item.target_date,
            "target_ignored": target_ignored, "target_low": target_low, "target_shortfall": target_shortfall,
            "plan_option_id": plan_opt["option_id"], "placement_date": placement if not committed else None,
            "fits": fits, "options": opts_out, "explain": explain,
        })
    return {"cushion": cushion, "items": out}
