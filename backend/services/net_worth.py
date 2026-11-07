"""Net worth: one recipe for the live Net Worth view and the stored daily snapshots.

assets = manual assets + active account balances
liabilities = manual liabilities + active card current balances
net worth = assets - liabilities

An overdrawn account is a negative balance, so it lowers assets.
"""
from __future__ import annotations
from decimal import Decimal

from sqlalchemy.orm import Session

from backend import models, schemas
from backend.services.explain import ExplainBuilder

ZERO = Decimal("0")


def _dec(value) -> Decimal:
    return Decimal(str(value))


def net_worth_totals(db: Session, user_id: int) -> schemas.NetWorthTotals:
    assets = db.query(models.ManualAsset).filter(
        models.ManualAsset.user_id == user_id).order_by(models.ManualAsset.id).all()
    liabilities = db.query(models.ManualLiability).filter(
        models.ManualLiability.user_id == user_id).order_by(models.ManualLiability.id).all()
    accounts = db.query(models.Account).filter(
        models.Account.user_id == user_id, models.Account.is_active == True,
    ).order_by(models.Account.id).all()
    cards = db.query(models.CreditCard).filter(
        models.CreditCard.user_id == user_id, models.CreditCard.is_active == True,
    ).order_by(models.CreditCard.id).all()

    manual_assets = sum((_dec(a.current_value) for a in assets), ZERO)
    account_balances = sum((_dec(a.current_balance) for a in accounts), ZERO)
    manual_liabilities = sum((_dec(l.current_balance) for l in liabilities), ZERO)
    card_balances = sum((_dec(c.current_balance) for c in cards), ZERO)
    total_assets = manual_assets + account_balances
    total_liabilities = manual_liabilities + card_balances
    net_worth = total_assets - total_liabilities

    explain = (
        ExplainBuilder("Net Worth")
        .start("Manual assets", manual_assets, children=[
            schemas.ExplainChild(label=a.name, amount=_dec(a.current_value)) for a in assets
        ])
        .add("Account balances", account_balances, children=[
            schemas.ExplainChild(label=a.name, amount=_dec(a.current_balance)) for a in accounts
        ])
        .subtract("Manual liabilities", manual_liabilities, children=[
            schemas.ExplainChild(label=l.name, amount=_dec(l.current_balance)) for l in liabilities
        ])
        .subtract("Card balances", card_balances, children=[
            schemas.ExplainChild(label=c.name, amount=_dec(c.current_balance)) for c in cards
        ])
        .build(net_worth)
    )
    return schemas.NetWorthTotals(
        manual_assets=manual_assets, account_balances=account_balances,
        total_assets=total_assets,
        manual_liabilities=manual_liabilities, card_balances=card_balances,
        total_liabilities=total_liabilities,
        net_worth=net_worth, explain=explain,
    )
