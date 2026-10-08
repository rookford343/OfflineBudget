"""Pure Wish List money math. Spec: docs/superpowers/specs/2026-10-07-wish-list-design.md"""
from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from backend import models
from backend.services.forecast_engine import _card_payoff_date_for_charge

CENT = Decimal("0.01")
ZERO = Decimal("0")


def _q(v: Decimal) -> Decimal:
    return v.quantize(CENT, rounding=ROUND_HALF_UP)


def add_months(d: date, k: int) -> date:
    y, m = divmod(d.month - 1 + k, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def net_price(item: models.WishItem) -> Decimal:
    price = Decimal(item.price or 0)
    if item.trade_in_on is None:
        return _q(max(price - Decimal(item.trade_in_value or 0), ZERO))
    return _q(price)


def financed_principal(item: models.WishItem, option: models.WishOption) -> Decimal:
    return _q(max(net_price(item) - Decimal(option.down_payment or 0), ZERO))


def payment_schedule(principal: Decimal, apr: Decimal, months: int) -> list[Decimal]:
    principal = Decimal(principal)
    if months <= 0 or principal <= 0:
        return []
    r = Decimal(apr or 0) / Decimal(1200)
    if r == 0:
        regular = _q(principal / months)
        total = _q(principal)
    else:
        regular = _q(principal * r / (1 - (1 + r) ** -months))
        # Amortized total: simulate the balance so interest is cent-exact.
        bal, total = principal, ZERO
        for _ in range(months - 1):
            interest = _q(bal * r)
            bal = bal + interest - regular
            total += regular
        total += _q(bal + _q(bal * r))
    return [regular] * (months - 1) + [_q(total - regular * (months - 1))]


def _trade_in_credit(item: models.WishItem) -> Decimal:
    return _q(Decimal(item.trade_in_value or 0)) if item.trade_in_on is not None else ZERO


def _validate_financed_months(months: int | None) -> None:
    """Raise ValueError if financed option months is invalid."""
    if months is None or months < 1 or months > 84:
        raise ValueError("Financed option needs 1-84 months")


def total_cost(item: models.WishItem, option: models.WishOption) -> Decimal:
    if option.method == models.WishMethod.financed:
        _validate_financed_months(option.months)
        paid = Decimal(option.down_payment or 0) + sum(
            payment_schedule(financed_principal(item, option), option.apr or 0, option.months or 0), ZERO)
    else:
        paid = net_price(item)
    return _q(paid - _trade_in_credit(item))


def monthly_payment(item: models.WishItem, option: models.WishOption) -> Decimal | None:
    if option.method != models.WishMethod.financed:
        return None
    _validate_financed_months(option.months)
    sched = payment_schedule(financed_principal(item, option), option.apr or 0, option.months or 0)
    return sched[0] if sched else None


def _route(option: models.WishOption, charge_date: date, cards: dict) -> date:
    """Card-routed money leaves checking on that card's payoff date."""
    if option.card_id is not None:
        card = cards.get(option.card_id)
        if card is None:
            raise ValueError("Card no longer exists")
        return _card_payoff_date_for_charge(card, charge_date)
    return charge_date


def option_flows(item: models.WishItem, option: models.WishOption, buy_date: date,
                 cards: dict) -> list[tuple[date, Decimal]]:
    flows: list[tuple[date, Decimal]] = []
    if option.method == models.WishMethod.full_checking:
        amt = net_price(item)
        if amt > 0:
            flows.append((buy_date, -amt))
    elif option.method == models.WishMethod.full_card:
        amt = net_price(item)
        if amt > 0:
            flows.append((_route(option, buy_date, cards), -amt))
    else:
        _validate_financed_months(option.months)
        down = _q(Decimal(option.down_payment or 0))
        if down > 0:
            flows.append((_route(option, buy_date, cards), -down))
        sched = payment_schedule(financed_principal(item, option), option.apr or 0, option.months or 0)
        for k, pay in enumerate(sched, start=1):
            flows.append((_route(option, add_months(buy_date, k), cards), -pay))
    credit = _trade_in_credit(item)
    if credit > 0:
        flows.append((item.trade_in_on, credit))
    return flows
