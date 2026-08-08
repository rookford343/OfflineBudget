"""Orchestrates SimpleFIN sync: pulls transactions for every linked account
and feeds them through the existing CSV-import pipeline so dedup, auto-
categorization, and rules apply identically regardless of source."""
from __future__ import annotations
import logging
from datetime import datetime, timedelta
from sqlalchemy import func
from sqlalchemy.orm import Session
from backend import models, schemas
from backend.services.crypto import decrypt
from backend.services.csv_parser import ParsedRow
from backend.services.import_service import build_preview, run_import
from backend.services.simplefin_client import fetch_transactions, SimpleFinError

logger = logging.getLogger(__name__)

_INITIAL_LOOKBACK_DAYS = 30  # first sync for a newly-linked account
_OVERLAP_DAYS = 3  # re-fetch a few days of overlap each sync so late-posting
                    # transactions aren't missed; import_service's dedup skips
                    # anything already imported


def sync_connection(db: Session, connection: models.BankConnection) -> None:
    """Sync every linked account for one BankConnection. Isolates failures per
    account so one broken link doesn't block the others."""
    user = db.get(models.User, connection.user_id)
    if not user:
        return

    access_url = decrypt(connection.access_url_encrypted)
    links = db.query(models.BankConnectionAccountLink).filter(
        models.BankConnectionAccountLink.connection_id == connection.id,
    ).all()

    any_success = False
    connection.last_error = None
    for link in links:
        try:
            _sync_link(db, user, access_url, link)
            any_success = True
        except SimpleFinError as exc:
            logger.error(
                "Bank sync failed for connection %s account %s: %s",
                connection.id, link.simplefin_account_id, exc,
            )
            connection.last_error = str(exc)

    # Any link succeeding brings the connection back to active (last_error is
    # still preserved for visibility even on a partial failure). Only a
    # connection where every link failed flips to `error`.
    if any_success:
        connection.status = models.BankConnectionStatus.active
    elif connection.last_error:
        connection.status = models.BankConnectionStatus.error
    connection.last_synced_at = datetime.utcnow()
    db.commit()


def _sync_link(db: Session, user: models.User, access_url: str, link: models.BankConnectionAccountLink) -> None:
    since = (
        link.last_synced_at - timedelta(days=_OVERLAP_DAYS)
        if link.last_synced_at
        else datetime.utcnow() - timedelta(days=_INITIAL_LOOKBACK_DAYS)
    )
    txns, balance = fetch_transactions(access_url, link.simplefin_account_id, since)

    parsed_rows = [
        ParsedRow(date=t.posted.date(), description=t.description, amount=t.amount)
        for t in txns
    ]

    if parsed_rows:
        preview_rows = build_preview(db, user, parsed_rows)
        confirm_rows = [
            schemas.ImportConfirmRow(
                date=r.date, description=r.description, amount=r.amount,
                category_id=r.category_id, is_transfer=r.is_transfer,
                recurring_item_id=r.suggested_recurring_item_id,
            )
            for r in preview_rows
        ]
        # import_service.run_import always tags new rows with the csv_import
        # source. Capture the high-water mark before the call and retag only
        # the rows this call actually inserted, so bank-sync-origin
        # transactions are distinguishable without touching the shared
        # import pipeline (dedup, categorization, rules stay identical for
        # every source).
        max_txn_id_before = db.query(func.max(models.Transaction.id)).scalar() or 0
        max_card_txn_id_before = db.query(func.max(models.CreditCardTransaction.id)).scalar() or 0
        run_import(
            db, user, confirm_rows,
            account_id=link.local_account_id,
            card_id=link.local_credit_card_id,
        )
        if link.local_account_id:
            db.query(models.Transaction).filter(
                models.Transaction.account_id == link.local_account_id,
                models.Transaction.id > max_txn_id_before,
            ).update({"source": models.TransactionSource.bank_sync})
        elif link.local_credit_card_id:
            db.query(models.CreditCardTransaction).filter(
                models.CreditCardTransaction.card_id == link.local_credit_card_id,
                models.CreditCardTransaction.id > max_card_txn_id_before,
            ).update({"source": models.CardTransactionSource.bank_sync})

    if link.local_account_id:
        account = db.get(models.Account, link.local_account_id)
        if account:
            account.current_balance = balance
    elif link.local_credit_card_id:
        card = db.get(models.CreditCard, link.local_credit_card_id)
        if card:
            card.current_balance = balance

    link.last_synced_at = datetime.utcnow()
    db.commit()


def sync_all(db: Session) -> None:
    """Entry point for the daily scheduled job -- syncs every active connection."""
    connections = db.query(models.BankConnection).filter(
        models.BankConnection.status == models.BankConnectionStatus.active,
    ).all()
    for connection in connections:
        sync_connection(db, connection)
