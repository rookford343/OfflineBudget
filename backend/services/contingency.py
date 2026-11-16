"""Contingency planning: the emergency fund's balance.

See docs/architecture.md's provenance table ("Emergency fund balance").
"""
from decimal import Decimal
from sqlalchemy.orm import Session
from backend import models


def emergency_fund_balance(db: Session, user_id: int) -> Decimal:
    """Sum of current_balance for the user's active savings/money-market
    accounts flagged as the emergency fund.

    Mirrors services/budget_snapshot.py's savings_balance query exactly,
    just flipping is_emergency_fund to True -- same user/active/type scoping,
    so an emergency fund never also counts as everyday savings or vice versa.
    """
    return sum(
        (acct.current_balance for acct in db.query(models.Account).filter(
            models.Account.user_id == user_id,
            models.Account.is_active == True,
            models.Account.type.in_([models.AccountType.savings, models.AccountType.money_market]),
            models.Account.is_emergency_fund == True,
        ).all()),
        Decimal("0"),
    )
