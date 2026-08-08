"""Orchestrates SimpleFIN sync: pulls transactions for every linked account
and feeds them through the existing CSV-import pipeline so dedup, auto-
categorization, and rules apply identically regardless of source."""
from __future__ import annotations
import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from backend import models, schemas
from backend.services.crypto import decrypt
from backend.services.csv_parser import ParsedRow
from backend.services.import_service import build_preview, run_import
from backend.services.simplefin_client import fetch_transactions

logger = logging.getLogger(__name__)

_INITIAL_LOOKBACK_DAYS = 30  # first sync for a newly-linked account
_OVERLAP_DAYS = 3  # re-fetch a few days of overlap each sync so late-posting
                    # transactions aren't missed; import_service's dedup skips
                    # anything already imported


def sync_connection(db: Session, connection: models.BankConnection) -> None:
    """Sync every linked account for one BankConnection. Isolates failures per
    account so one broken link doesn't block the others, and isolates the
    decrypt step so a corrupted/key-mismatched token can't propagate out to
    the caller (sync_all iterates other connections in the same job)."""
    user = db.get(models.User, connection.user_id)
    if not user:
        return

    try:
        access_url = decrypt(connection.access_url_encrypted)
    except Exception as exc:  # noqa: BLE001 -- any decrypt failure isolates this connection only
        logger.error(
            "Bank sync failed to decrypt access token for connection %s: %s",
            connection.id, exc,
        )
        db.rollback()
        connection.last_error = str(exc)
        connection.status = models.BankConnectionStatus.error
        connection.last_synced_at = datetime.utcnow()
        db.commit()
        return

    links = db.query(models.BankConnectionAccountLink).filter(
        models.BankConnectionAccountLink.connection_id == connection.id,
    ).all()

    any_success = False
    connection.last_error = None
    for link in links:
        try:
            _sync_link(db, user, access_url, link)
            any_success = True
        except Exception as exc:  # noqa: BLE001 -- one link's failure (SimpleFinError or
            # anything unexpected out of build_preview/run_import) must never
            # stop the other links on this connection from syncing.
            logger.error(
                "Bank sync failed for connection %s account %s: %s",
                connection.id, link.simplefin_account_id, exc,
            )
            db.rollback()
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
        ParsedRow(
            date=t.posted.date(), description=t.description, amount=t.amount,
            external_id=t.id,
        )
        for t in txns
    ]

    if parsed_rows:
        preview_rows = build_preview(db, user, parsed_rows)
        # build_preview stamps each preview row with the index of the ParsedRow
        # it came from, so we recover SimpleFIN's transaction id by index rather
        # than widening the preview/confirm contract for every CSV caller.
        confirm_rows = [
            schemas.ImportConfirmRow(
                date=r.date, description=r.description, amount=r.amount,
                category_id=r.category_id, is_transfer=r.is_transfer,
                recurring_item_id=r.suggested_recurring_item_id,
                external_id=parsed_rows[r.row_index].external_id,
            )
            for r in preview_rows
        ]
        run_import(
            db, user, confirm_rows,
            account_id=link.local_account_id,
            card_id=link.local_credit_card_id,
            source=models.TransactionSource.bank_sync,
            card_source=models.CardTransactionSource.bank_sync,
        )

    if link.local_account_id:
        account = db.get(models.Account, link.local_account_id)
        if account:
            account.current_balance = balance
    elif link.local_credit_card_id:
        card = db.get(models.CreditCard, link.local_credit_card_id)
        if card:
            # SimpleFIN reports a card's liability as a NEGATIVE balance, but
            # CreditCard.current_balance is a positive amount owed everywhere
            # else in this codebase (import_service subtracts signed amounts,
            # utilization_pct divides by credit_limit). Flip the sign.
            card.current_balance = -balance

    link.last_synced_at = datetime.utcnow()
    db.commit()


def sync_all(db: Session) -> None:
    """Entry point for the daily scheduled job -- syncs every connection the
    user hasn't explicitly disconnected. Errored connections are deliberately
    INCLUDED: sync_connection is the only code path that can flip status back
    to `active`, so excluding `error` would make a single transient failure
    (timeout, bank unreachable) permanent. Isolates each connection so one
    connection's unexpected failure (including a decrypt error or anything
    sync_connection itself doesn't catch) can never abort the rest of the job."""
    connections = db.query(models.BankConnection).filter(
        models.BankConnection.status != models.BankConnectionStatus.disconnected,
    ).all()
    for connection in connections:
        try:
            sync_connection(db, connection)
        except Exception as exc:  # noqa: BLE001 -- defense in depth: sync_connection
            # already isolates decrypt and per-link failures internally, but
            # nothing raised while processing one connection may prevent
            # sync_all from attempting every other connection.
            logger.error(
                "Bank sync job failed entirely for connection %s: %s",
                connection.id, exc,
            )
            db.rollback()
