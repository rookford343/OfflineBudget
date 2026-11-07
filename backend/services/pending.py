"""Pending money: the one accessor, the one freshness rule.

Card pending charges come from two places: the issuer's pending feed
(`CardPendingTransaction` rows, replaced wholesale on every bank sync) and a
hand-typed `CreditCard.pending_charges`. Every figure in the app that needs a
card's pending reads it through `card_pending`; nothing else reads the raw
field (see docs/architecture.md, "Pending charges").

Checking pending debits are the Plaid `AccountPendingTransaction` snapshot,
read only while an active Plaid link keeps it fresh.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session, object_session

from backend import models
from backend.services.card_matching import match_payment_card

PENDING_FRESH_DAYS = 7


def card_has_sync_rows(db: Session, card: models.CreditCard) -> bool:
    """True when the issuer's pending feed has ever reported on this card.

    The signal is "any CardPendingTransaction row exists". It is the same
    signal the forecast already used (bank_feed_pending_card_ids). A synced
    card that now legitimately has zero pending rows has no rows left, so
    this reads False -- but `replace_pending_snapshot` wrote
    pending_charges = 0 stamped now, so the hand-typed rule below also gives
    0 for it for the next 7 days, and a stale hand-typed figure is never
    carried forward after that.
    """
    return db.query(models.CardPendingTransaction.id).filter(
        models.CardPendingTransaction.card_id == card.id,
    ).first() is not None


def card_pending(card: models.CreditCard, today: date) -> Decimal:
    """A card's pending charges right now.

    - The card has issuer pending rows: their sum (never below 0; a
      pending refund cannot make pending negative, as at sync time).
    - Otherwise the hand-typed `pending_charges`, only when stamped within
      `PENDING_FRESH_DAYS` of `today`. A stale or unstamped figure is
      nothing pending, never silently carried forward.
    """
    db = object_session(card)
    if db is not None:
        rows = db.query(models.CardPendingTransaction.amount).filter(
            models.CardPendingTransaction.card_id == card.id,
        ).all()
        if rows:
            return max(sum((Decimal(str(a)) for (a,) in rows), Decimal("0")), Decimal("0"))
    value = Decimal(str(card.pending_charges or 0))
    if value <= 0 or card.pending_charges_updated_at is None:
        return Decimal("0")
    if (today - card.pending_charges_updated_at.date()).days > PENDING_FRESH_DAYS:
        return Decimal("0")
    return value


def pending_snapshot_is_live(db: Session, account: models.Account) -> bool:
    """True when this account's AccountPendingTransaction snapshot is kept
    fresh: a checking account with an ACTIVE Plaid link. Nothing else
    refreshes the snapshot, so rows on any other account are stale and must
    be neither subtracted by the forecast nor shown as pending."""
    return account.type == models.AccountType.checking and db.query(
        models.BankConnectionAccountLink.id,
    ).join(models.BankConnection).filter(
        models.BankConnectionAccountLink.local_account_id == account.id,
        models.BankConnectionAccountLink.is_active == True,
        models.BankConnection.provider == "plaid",
    ).first() is not None


def checking_pending_debits(
    db: Session, account: models.Account, today: date, *, card_payments_only: bool,
) -> list[models.AccountPendingTransaction]:
    """Pending debits on a checking account, oldest first. Empty unless an
    active Plaid link keeps the snapshot fresh. With `card_payments_only`,
    only the debits that pay exactly one of the user's active cards (the
    forecast's rule: any other pending debit is most likely a bill the walk
    already projects). Pending credits are never included."""
    if not pending_snapshot_is_live(db, account):
        return []
    rows = db.query(models.AccountPendingTransaction).filter(
        models.AccountPendingTransaction.user_id == account.user_id,
        models.AccountPendingTransaction.account_id == account.id,
        models.AccountPendingTransaction.amount < 0,
    ).order_by(models.AccountPendingTransaction.date, models.AccountPendingTransaction.id).all()
    if not card_payments_only:
        return rows
    cards = db.query(models.CreditCard).filter(
        models.CreditCard.user_id == account.user_id, models.CreditCard.is_active == True,
    ).all()
    return [r for r in rows if match_payment_card(cards, r.description) is not None]


def checking_pending_rows(
    db: Session, account: models.Account, today: date,
) -> list[models.AccountPendingTransaction]:
    """Every pending row on a checking account, credits and debits alike,
    newest first. Empty unless an active Plaid link keeps the snapshot
    fresh (`pending_snapshot_is_live`)."""
    if not pending_snapshot_is_live(db, account):
        return []
    return db.query(models.AccountPendingTransaction).filter(
        models.AccountPendingTransaction.user_id == account.user_id,
        models.AccountPendingTransaction.account_id == account.id,
    ).order_by(
        models.AccountPendingTransaction.date.desc(), models.AccountPendingTransaction.id,
    ).all()


def checking_balance_with_pending(db: Session, account: models.Account, today: date) -> Decimal:
    """Posted balance plus every live pending row, credits and debits alike
    (a pending deposit raises it, a pending charge lowers it). Equals the
    posted balance when the snapshot is not live."""
    rows = checking_pending_rows(db, account, today)
    return Decimal(str(account.current_balance)) + sum(
        (Decimal(str(r.amount)) for r in rows), Decimal("0"),
    )
