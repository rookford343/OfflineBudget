"""Orchestrates SimpleFIN sync: pulls transactions for every linked account
and feeds them through the existing CSV-import pipeline so dedup, auto-
categorization, and rules apply identically regardless of source."""
from __future__ import annotations
import json
import logging
from decimal import Decimal
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


def sync_connection(db: Session, connection: models.BankConnection) -> tuple[int, int]:
    """Sync every linked account for one BankConnection. Isolates failures per
    account so one broken link doesn't block the others, and isolates the
    decrypt step so a corrupted/key-mismatched token can't propagate out to
    the caller (sync_all iterates other connections in the same job).

    Returns (imported, skipped_duplicates) totals across every link on this
    connection -- lets a caller (the "Sync Now" button) tell "ran, found
    nothing new" apart from "ran, here's what changed" instead of the
    timestamp-only signal that used to be the only feedback available.
    """
    user = db.get(models.User, connection.user_id)
    if not user:
        return (0, 0)

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
        return (0, 0)

    links = db.query(models.BankConnectionAccountLink).filter(
        models.BankConnectionAccountLink.connection_id == connection.id,
    ).all()

    any_success = False
    connection.last_error = None
    total_imported = 0
    total_skipped = 0
    for link in links:
        try:
            imported, skipped = _sync_link(db, user, access_url, link)
            total_imported += imported
            total_skipped += skipped
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
    return (total_imported, total_skipped)


def _sync_link(
    db: Session, user: models.User, access_url: str, link: models.BankConnectionAccountLink,
) -> tuple[int, int]:
    since = (
        link.last_synced_at - timedelta(days=_OVERLAP_DAYS)
        if link.last_synced_at
        else datetime.utcnow() - timedelta(days=_INITIAL_LOOKBACK_DAYS)
    )
    txns, balance = fetch_transactions(access_url, link.simplefin_account_id, since)

    if user.debug_capture_raw_bank_data and txns:
        _capture_raw_snapshots(db, user.id, txns)

    parsed_rows = [
        ParsedRow(
            date=t.posted.date(), description=t.description, amount=t.amount,
            external_id=t.id,
        )
        for t in txns
    ]

    imported = 0
    skipped = 0
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
        result = run_import(
            db, user, confirm_rows,
            account_id=link.local_account_id,
            card_id=link.local_credit_card_id,
            source=models.TransactionSource.bank_sync,
            card_source=models.CardTransactionSource.bank_sync,
        )
        imported = result.imported
        skipped = result.skipped_duplicates

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

            if card.payment_sent_pending_sync:
                # A fresh sync just wrote real, authoritative data --
                # whatever it now says, the manual marker is stale by
                # definition. balance_due is never touched by bank sync
                # (confirmed: only current_balance is), so this is the
                # actual reconciliation signal, not balance_due changing.
                # Without this the flag could never clear from a real
                # sync at all -- only from record_payment or a manual
                # edit, which is exactly the workaround this feature
                # exists to replace. Found in final whole-branch review,
                # 2026-08-28.
                card.payment_sent_pending_sync = False
                card.payment_sent_amount = None

            if card.pending_charges and card.pending_charges > 0 and imported > 0:
                # Dan's call (final whole-branch review, 2026-08-28): only
                # clear when this sync actually brought in new transactions
                # for this card -- a balance refresh alone isn't proof the
                # hand-typed figure is stale, but real posted activity is.
                # A no-op sync (current_balance unchanged, nothing new
                # imported) now leaves the pending figure alone, so it keeps
                # feeding the forecast's second hop and budget_snapshot's
                # Left to Spend until something real actually supersedes it.
                card.pending_charges = Decimal("0")
                card.pending_charges_updated_at = None

    link.last_synced_at = datetime.utcnow()
    db.commit()
    return (imported, skipped)


def _capture_raw_snapshots(db: Session, user_id: int, txns: list) -> None:
    """Debug-only: overwrite this user's raw snapshot for each external_id so
    a re-synced overlap window updates the capture in place instead of
    accumulating duplicate rows for the same transaction (_OVERLAP_DAYS
    re-fetches the last few days on every sync)."""
    existing = {
        s.external_id: s
        for s in db.query(models.BankSyncRawSnapshot).filter(
            models.BankSyncRawSnapshot.user_id == user_id,
            models.BankSyncRawSnapshot.external_id.in_([t.id for t in txns]),
        ).all()
    }
    for t in txns:
        raw_json = json.dumps(t.raw, default=str)
        if t.id in existing:
            existing[t.id].raw_json = raw_json
            existing[t.id].captured_at = datetime.utcnow()
        else:
            db.add(models.BankSyncRawSnapshot(
                user_id=user_id, external_id=t.id, raw_json=raw_json,
            ))


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
