"""One cushion everywhere (Calculation changelog v6).

The Safety Margin 3-month warning, the forecast risk banner and the Wish List
all read the user's single `safety_cushion` (default $1,000) and split the same
way: amber below the cushion, red below $0. The per-account
`low_balance_threshold` and `wish_settings.cushion` columns remain in the
schema (additive rule) but nothing reads them any more.
"""
from decimal import Decimal
from typing import Literal

from backend import models

DEFAULT_CUSHION = Decimal("1000")

CushionStatus = Literal["ok", "warning", "danger"]


def cushion_for(user: models.User) -> Decimal:
    """The user's cushion: their setting, else the $1,000 default."""
    if user.safety_cushion is not None:
        return Decimal(user.safety_cushion)
    return DEFAULT_CUSHION


def cushion_status(value: Decimal, cushion: Decimal) -> CushionStatus:
    """"danger" strictly below $0, "warning" strictly below the cushion, else
    "ok". Exactly AT the cushion is ok -- it is the balance to stay at or
    above. Checked in that order, so a $0 cushion leaves only the below-$0
    signal."""
    if value < 0:
        return "danger"
    if value < cushion:
        return "warning"
    return "ok"
