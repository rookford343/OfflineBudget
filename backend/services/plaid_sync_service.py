"""Plaid sync: one `/transactions/sync` run for a Plaid BankConnection, fed
through the same import, balance, pending-charge and statement logic SimpleFIN
uses (see bank_sync_service.py), plus a previewable first import that pairs
Plaid's rows with the ones SimpleFIN already stored (see cutover_match.py).

Order of a run: fetch every page, then every other Plaid read (accounts,
item status, liabilities), and only then write. A failure or 429 anywhere in
the reads therefore leaves the database and the stored cursor untouched. The
cursor is saved in the final commit, so a run that dies part-way re-reads
the same delta next time; external-id dedup makes that replay harmless.

`dry_run` is the first-import preview: it classifies the posted rows and
writes nothing. `run_import` commits internally, so the preview must never
call it -- a rollback could not undo that commit."""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from backend import models, schemas
from backend.services import plaid_client
from backend.services.bank_sync_service import (
    PendingCharge, apply_account_balance, apply_card_balance, replace_pending_snapshot,
)
from backend.services.crypto import decrypt
from backend.services.csv_parser import ParsedRow
from backend.services.cutover_match import MATCH_DAYS, WINDOW_BEFORE_DAYS, cutover_zone, find_match
from backend.services.import_service import (
    _find_duplicate_card_transaction, _find_duplicate_transaction, build_preview, run_import,
)
from backend.services.plaid_client import (
    READY_UPDATE_STATUSES, PlaidAccount, PlaidError, PlaidNotReady, PlaidRateLimited, PlaidTransaction,
)
from backend.services.statement_reconcile import _FULL_COVERAGE_SLOP

logger = logging.getLogger(__name__)

LOGIN_REQUIRED_MESSAGE = "Your bank needs you to log in again. Use Reconnect in Settings → Accounts."
RATE_LIMITED_MESSAGE = "Plaid rate limit reached; will retry next run"
_UNEXPECTED_MESSAGE = "Plaid sync failed unexpectedly; see the server log"

Outcome = Literal["imported", "matched", "ignored"]


@dataclass
class ImportReportRow:
    date: date
    amount: Decimal
    description: str
    outcome: Outcome
    target: str


@dataclass
class PlaidSyncReport:
    imported: int = 0
    matched: int = 0
    ignored: int = 0
    rows: list[ImportReportRow] = field(default_factory=list)
    # Display names of the item's accounts with no active link on this
    # connection. Their rows are skipped, and once the cursor moves past them
    # that history is gone, so the first-import preview lists them.
    unlinked_accounts: list[str] = field(default_factory=list)


def _pid(transaction_id: str) -> str:
    return f"plaid:{transaction_id}"


@dataclass
class _Delta:
    """Every page of one sync folded into its final state. `changes` maps a
    Plaid transaction id to ("added" | "modified", latest copy); an id added
    and then modified within the same run stays "added". `removed` keeps
    page order."""
    changes: dict[str, tuple[str, PlaidTransaction]]
    removed: list[str]
    next_cursor: str


def _fetch_delta(access_token: str, cursor: str | None, *, require_ready: bool = False) -> _Delta:
    """With `require_ready` (first import and its preview), raises
    PlaidNotReady when the first page shows Plaid's initial pull isn't done
    -- before anything is written, so the cursor stays None."""
    changes: dict[str, tuple[str, PlaidTransaction]] = {}
    removed: dict[str, None] = {}  # ordered set
    first = True
    while True:
        page = plaid_client.sync_page(access_token, cursor)
        if first and require_ready and page.transactions_update_status not in READY_UPDATE_STATUSES:
            raise PlaidNotReady()
        first = False
        for t in page.added:
            changes[t.id] = ("added", t)
            removed.pop(t.id, None)
        for t in page.modified:
            kind = changes[t.id][0] if t.id in changes else "modified"
            changes[t.id] = (kind, t)
            removed.pop(t.id, None)
        for rid in page.removed:
            changes.pop(rid, None)
            removed[rid] = None
        cursor = page.next_cursor
        if not page.has_more:
            return _Delta(changes, list(removed), cursor)


def _local_naive(value: datetime | None) -> datetime | None:
    """Plaid's timestamps are tz-aware. The app's balance dates are
    local-naive (SimpleFIN's come from datetime.fromtimestamp), and
    card.balance_as_of raises on an aware/naive mix. Converting to UTC instead
    would turn a 21:30 ET update into 01:30 the next day and anchor last
    night's balance to today."""
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone().replace(tzinfo=None)


def _target_name(db: Session, link: models.BankConnectionAccountLink) -> str:
    if link.local_account_id:
        account = db.get(models.Account, link.local_account_id)
        if account:
            return account.name
    elif link.local_credit_card_id:
        card = db.get(models.CreditCard, link.local_credit_card_id)
        if card:
            return card.name
    return link.simplefin_account_name


def _stored_row(db: Session, user_id: int, link: models.BankConnectionAccountLink, external_id: str):
    """The stored row on this link's account or card that carries `external_id`
    as its own id or as the cutover's alt id."""
    if link.local_account_id:
        m = models.Transaction
        q = db.query(m).filter(m.user_id == user_id, m.account_id == link.local_account_id)
    else:
        m = models.CreditCardTransaction
        q = db.query(m).filter(m.user_id == user_id, m.card_id == link.local_credit_card_id)
    return q.filter(or_(m.external_id == external_id, m.alt_external_id == external_id)).first()


def _plaid_claimed_ids(db: Session, user_id: int, link: models.BankConnectionAccountLink, cutover: date) -> set[int]:
    """Rows in the match window that already carry a Plaid id. find_match
    ignores external ids by design, so without this a second identical Plaid
    charge could pair with a row an earlier Plaid row already owns."""
    since = cutover - timedelta(days=WINDOW_BEFORE_DAYS + MATCH_DAYS)
    if link.local_account_id:
        m = models.Transaction
        q = db.query(m.id).filter(m.user_id == user_id, m.account_id == link.local_account_id)
    else:
        m = models.CreditCardTransaction
        q = db.query(m.id).filter(m.user_id == user_id, m.card_id == link.local_credit_card_id)
    q = q.filter(m.date >= since, or_(m.alt_external_id.isnot(None), m.external_id.like("plaid:%")))
    return {row_id for (row_id,) in q.all()}


def _classify(
    db: Session, user_id: int, link: models.BankConnectionAccountLink, txn: PlaidTransaction,
    cutover: date | None, consumed: set[int],
) -> tuple[Outcome, models.Transaction | models.CreditCardTransaction | None]:
    """Read-only: decides what a posted row would do. Returns the cutover match
    (to receive alt_external_id) when one was found. Shared by the preview and
    the real run, so the preview reports exactly what a confirm will do.

    A row already stored under this Plaid id (its own external_id, or an
    alt_external_id from an earlier cutover match) is "matched" before any
    zoning: on a replay, find_match would otherwise pair it with a second,
    unclaimed look-alike row and stamp the same Plaid id on that too."""
    if _stored_row(db, user_id, link, _pid(txn.id)) is not None:
        return "matched", None
    if cutover is not None:
        zone = cutover_zone(txn.date, cutover)
        if zone == "ignore":
            return "ignored", None
        if zone == "match":
            hit = find_match(db, user_id, account_id=link.local_account_id, card_id=link.local_credit_card_id,
                             txn=txn, consumed=consumed)
            if hit is not None:
                return "matched", hit
    row = schemas.ImportConfirmRow(date=txn.date, description=txn.description, amount=txn.amount,
                                   external_id=_pid(txn.id))
    if link.local_account_id:
        dup = _find_duplicate_transaction(db, user_id, link.local_account_id, row, consumed)
    else:
        dup = _find_duplicate_card_transaction(db, user_id, link.local_credit_card_id, row, consumed)
    if dup is not None:
        consumed.add(dup.id)
        return "matched", None
    return "imported", None


def _import(
    db: Session, user: models.User, link: models.BankConnectionAccountLink, txns: list[PlaidTransaction],
    consumed: set[int],
) -> int:
    """Mirrors bank_sync_service._sync_link: ParsedRow -> preview -> confirm ->
    run_import. Card rows keep checking convention (negative = charge), the
    same sign _sync_link passes for SimpleFIN; run_import flips it once.

    `consumed` is the classify pass's set (rows find_match paired this run,
    rows already carrying a Plaid id, and heuristic duplicates). Seeding
    run_import with it keeps its own heuristic dedup from re-using a row the
    matcher already gave to a different Plaid charge."""
    if not txns:
        return 0
    parsed = [ParsedRow(date=t.date, description=t.description, amount=t.amount, external_id=_pid(t.id))
              for t in txns]
    confirm = [
        schemas.ImportConfirmRow(
            date=r.date, description=r.description, amount=r.amount,
            category_id=r.category_id, is_transfer=r.is_transfer,
            recurring_item_id=r.suggested_recurring_item_id,
            external_id=parsed[r.row_index].external_id,
        )
        for r in build_preview(db, user, parsed)
    ]
    result = run_import(
        db, user, confirm,
        account_id=link.local_account_id, card_id=link.local_credit_card_id,
        source=models.TransactionSource.bank_sync, card_source=models.CardTransactionSource.bank_sync,
        consumed=consumed,
    )
    return result.imported


def _user_edited(row) -> bool:
    if isinstance(row, models.Transaction):
        return bool(row.notes and row.notes.strip())
    # CreditCardTransaction has no notes; a description the user typed that
    # differs from the bank's merchant text is the equivalent edit.
    return bool(row.description and row.description.strip() and row.description != row.merchant)


def _apply_removed(db: Session, user_id: int, links, removed: list[str]) -> None:
    for rid in removed:
        pid = _pid(rid)
        for link in links:
            row = _stored_row(db, user_id, link, pid)
            if row is None:
                continue
            if _user_edited(row):
                logger.warning("Plaid removed a transaction the user edited; kept row %s", row.id)
            else:
                db.delete(row)
            break


def _pending_for_card(
    db: Session, card_id: int, link_txns: list[tuple[str, PlaidTransaction]], removed: list[str],
) -> list[PendingCharge]:
    """`/transactions/sync` is a delta, so the pending list is carried forward:
    the Plaid pending rows already stored, minus ids Plaid removed or reports
    as posted now, plus this run's pending rows. Rows from another provider
    (SimpleFIN ids) are dropped -- this snapshot replaces them."""
    current = {
        r.external_id: PendingCharge(r.external_id, r.date, Decimal(str(r.amount)), r.merchant)
        for r in db.query(models.CardPendingTransaction).filter(
            models.CardPendingTransaction.card_id == card_id,
            models.CardPendingTransaction.external_id.like("plaid:%"),
        ).all()
    }
    for rid in removed:
        current.pop(_pid(rid), None)
    for _kind, t in link_txns:
        if t.pending:
            current[_pid(t.id)] = PendingCharge(_pid(t.id), t.date, -t.amount, t.description[:256])
        else:
            current.pop(_pid(t.id), None)
    return list(current.values())


def _credits_since(db: Session, card: models.CreditCard, issue_date: date) -> Decimal:
    """Sum of abs(amount) for this card's CreditCardTransaction rows posted
    after `issue_date` with amount < 0 (positive=charge, negative=payment,
    refund or return). The issuer's own rule -- confirmed live: a statement
    closed, a merchant return posted after close, then autopay for the
    remainder, and the issuer showed that statement paid in full -- treats
    a return exactly like a payment, so both count here."""
    total = db.query(func.sum(-models.CreditCardTransaction.amount)).filter(
        models.CreditCardTransaction.card_id == card.id,
        models.CreditCardTransaction.user_id == card.user_id,
        models.CreditCardTransaction.amount < 0,
        models.CreditCardTransaction.date > issue_date,
    ).scalar() or Decimal("0")
    return Decimal(str(total))


def _recompute_balance_due(
    db: Session, card: models.CreditCard, original: Decimal, issue_date: date, cap: Decimal,
) -> None:
    """Recompute what's still owed on the CURRENT statement: `original` (the
    statement balance Plaid reports right now -- never the stored
    balance_due, which record_payment may have hand-reduced; comparing
    against the original is what keeps a posting-lag payment from being
    double counted) minus credits posted after `issue_date`. Within
    _FULL_COVERAGE_SLOP of full coverage it clears to 0, the same rounding
    slop reconcile_statement_payment allows; otherwise it's capped at `cap`
    so this can only lower balance_due, never raise it -- a hand-recorded
    payment that hasn't posted yet still counts. Stamps
    balance_due_updated_at only when balance_due actually changes."""
    remaining = original - _credits_since(db, card, issue_date)
    previous = Decimal(str(card.balance_due or 0))
    new_balance_due = Decimal("0") if remaining <= _FULL_COVERAGE_SLOP else min(cap, remaining)
    if new_balance_due != previous:
        card.balance_due = new_balance_due
        card.balance_due_updated_at = datetime.utcnow()


def _apply_statements(db: Session, by_account: dict, statements) -> None:
    for st in statements:
        link = by_account.get(st.account_id)
        if link is None or not link.local_credit_card_id or st.last_statement_issue_date is None:
            continue
        card = db.get(models.CreditCard, link.local_credit_card_id)
        if card is None:
            continue
        stored = card.last_statement_issue_date
        if stored is not None and st.last_statement_issue_date <= stored:
            # Same statement: recompute what's left from the issuer's
            # current figure and this card's credits since it closed --
            # payments and returns alike -- instead of resetting balance_due
            # to the statement total (record_payment may have already
            # hand-reduced it) or leaving an already-paid statement standing
            # until the next one closes.
            if st.last_statement_balance is not None:
                original = max(st.last_statement_balance, Decimal("0"))
                _recompute_balance_due(db, card, original, stored, Decimal(str(card.balance_due or 0)))
            continue
        if st.last_statement_balance is None:
            # No balance to apply: skip the statement entirely, so the issue
            # date doesn't advance and a later complete copy still applies.
            continue
        original = max(st.last_statement_balance, Decimal("0"))
        if stored is not None:
            # Strictly newer than a statement we already tracked: start from
            # this statement's own total (a statement that closed in credit,
            # an overpayment, means nothing is due), then pay it down with
            # any credits already posted after ITS close -- this run's own
            # imported card transactions count, since _apply_statements runs
            # after they're imported and committed.
            _recompute_balance_due(db, card, original, st.last_statement_issue_date, original)
        else:
            # stored is None: the card's first Plaid statement. Its
            # balance_due predates Plaid and may already be reduced by
            # record_payment or paid off, so the cap is whatever is
            # currently there -- but pay it down against the just-seeded
            # date too, so a statement that's already fully covered clears
            # on this very first sync instead of waiting for the next one.
            _recompute_balance_due(
                db, card, original, st.last_statement_issue_date, Decimal(str(card.balance_due or 0)),
            )
        card.last_statement_issue_date = st.last_statement_issue_date
        if st.next_payment_due_date is not None:
            card.next_payment_date = st.next_payment_due_date
        if st.minimum_payment_amount is not None:
            card.minimum_payment_amount = st.minimum_payment_amount


def _record_error(db: Session, connection: models.BankConnection, exc: Exception) -> None:
    """Store a safe, plain-language error. PlaidError's text comes only from
    Plaid's error_code/error_message (see plaid_client), never a request body
    or the token. A 429 changes nothing but last_error."""
    if isinstance(exc, PlaidRateLimited):
        connection.last_error = RATE_LIMITED_MESSAGE
    elif isinstance(exc, PlaidError):
        connection.status = models.BankConnectionStatus.error
        connection.last_error = LOGIN_REQUIRED_MESSAGE if exc.code == "ITEM_LOGIN_REQUIRED" else str(exc)
    else:
        connection.status = models.BankConnectionStatus.error
        connection.last_error = _UNEXPECTED_MESSAGE
    db.commit()


def sync_plaid_connection(
    db: Session, connection: models.BankConnection, *, first_import: bool = False, dry_run: bool = False,
) -> PlaidSyncReport:
    """Run one Plaid sync (or, with dry_run, preview it). On failure the error
    is recorded on the connection (not on a dry run, which writes nothing) and
    re-raised, so the first-import endpoint can report it; sync_connection
    swallows it to keep sync_all going."""
    user = db.get(models.User, connection.user_id)
    if user is None:
        return PlaidSyncReport()
    connection_id = connection.id
    try:
        return _run(db, user, connection, first_import=first_import, dry_run=dry_run)
    except Exception as exc:
        db.rollback()
        code = exc.code if isinstance(exc, PlaidError) else type(exc).__name__
        logger.error("Plaid sync failed for connection %s: %s", connection_id, code)
        # NOT_READY isn't a fault with the connection: nothing was written and
        # the user just tries again in a minute.
        if not dry_run and not isinstance(exc, PlaidNotReady):
            _record_error(db, connection, exc)
        raise


def _run(
    db: Session, user: models.User, connection: models.BankConnection, *, first_import: bool, dry_run: bool,
) -> PlaidSyncReport:
    access_token = decrypt(connection.access_url_encrypted)
    delta = _fetch_delta(access_token, connection.sync_cursor, require_ready=first_import or dry_run)

    links = db.query(models.BankConnectionAccountLink).filter(
        models.BankConnectionAccountLink.connection_id == connection.id,
        models.BankConnectionAccountLink.is_active == True,
    ).all()
    by_account = {link.simplefin_account_id: link for link in links}

    # Rows for accounts with no active link are dropped here, silently.
    per_link: dict[int, list[tuple[str, PlaidTransaction]]] = defaultdict(list)
    for kind, txn in delta.changes.values():
        link = by_account.get(txn.account_id)
        if link is not None:
            per_link[link.id].append((kind, txn))

    # Plaid connections always carry cutover_date (set at exchange). A first
    # import without one falls back to today, the value exchange would set.
    cutover = connection.cutover_date or (date.today() if first_import else None)
    report = PlaidSyncReport()

    if dry_run:
        # A read, so the preview may make it: it lists the unmapped accounts.
        report.unlinked_accounts = _unlinked_names(plaid_client.get_accounts(access_token), by_account)
        for link in links:
            consumed = _plaid_claimed_ids(db, user.id, link, cutover) if cutover else set()
            target = _target_name(db, link)
            for kind, txn in per_link[link.id]:
                if kind != "added" or txn.pending:
                    continue
                outcome, _ = _classify(db, user.id, link, txn, cutover, consumed)
                _count(report, txn, outcome, target)
        db.rollback()  # belt and braces: nothing above writes
        return report

    # Every remaining Plaid read happens before the first write.
    item_accounts = plaid_client.get_accounts(access_token)
    accounts = {a.id: a for a in item_accounts}
    report.unlinked_accounts = _unlinked_names(item_accounts, by_account)
    last_update = _local_naive(plaid_client.get_last_successful_update(access_token))
    statements = plaid_client.get_card_statements(access_token)

    imported_by_link: dict[int, int] = {}
    for link in links:
        consumed = _plaid_claimed_ids(db, user.id, link, cutover) if cutover else set()
        target = _target_name(db, link)
        to_classify: list[PlaidTransaction] = []
        for kind, txn in per_link[link.id]:
            if txn.pending:
                continue
            if kind == "modified":
                stored = _stored_row(db, user.id, link, _pid(txn.id))
                if stored is not None:
                    _apply_modified(stored, txn)
                    continue
            to_classify.append(txn)

        to_import: list[PlaidTransaction] = []
        for txn in to_classify:
            outcome, hit = _classify(db, user.id, link, txn, cutover, consumed)
            if hit is not None:
                hit.alt_external_id = _pid(txn.id)
            if outcome == "imported":
                to_import.append(txn)
            _count(report, txn, outcome, target)
        imported_by_link[link.id] = _import(db, user, link, to_import, consumed)

    report.imported = sum(imported_by_link.values())
    _apply_removed(db, user.id, links, delta.removed)

    for link in links:
        plaid_account = accounts.get(link.simplefin_account_id)
        current = plaid_account.current if plaid_account else None
        imported = imported_by_link.get(link.id, 0)
        if link.local_account_id:
            account = db.get(models.Account, link.local_account_id)
            if account and current is not None:
                apply_account_balance(db, user, account, current, last_update, imported)
        elif link.local_credit_card_id:
            card = db.get(models.CreditCard, link.local_credit_card_id)
            if card is None:
                continue
            pending = _pending_for_card(db, card.id, per_link[link.id], delta.removed)
            if current is not None:
                # Plaid reports credit owed as positive already: no sign flip.
                apply_card_balance(db, user, card, current, last_update, pending, imported)
            else:
                replace_pending_snapshot(db, user, card, pending)

    _apply_statements(db, by_account, statements)

    now = datetime.utcnow()
    connection.sync_cursor = delta.next_cursor
    for link in links:
        link.last_synced_at = now
    connection.last_synced_at = now
    connection.status = models.BankConnectionStatus.active
    connection.last_error = None
    db.commit()

    try:
        plaid_client.refresh_transactions(access_token)
    except PlaidError as exc:
        # Best effort: the sync above already succeeded and is committed.
        logger.warning("Plaid refresh request skipped for connection %s: %s", connection.id, exc.code)
    return report


def _unlinked_names(item_accounts: list[PlaidAccount], by_account: dict) -> list[str]:
    return [f"{a.name} ••{a.mask}" if a.mask else a.name for a in item_accounts if a.id not in by_account]


def _apply_modified(row, txn: PlaidTransaction) -> None:
    row.date = txn.date
    if isinstance(row, models.Transaction):
        row.amount = txn.amount
        row.description = txn.description[:256]
    else:
        row.amount = -txn.amount  # card convention: positive = charge
        row.merchant = txn.description[:256]


def _count(report: PlaidSyncReport, txn: PlaidTransaction, outcome: Outcome, target: str) -> None:
    report.rows.append(ImportReportRow(date=txn.date, amount=txn.amount, description=txn.description,
                                       outcome=outcome, target=target))
    if outcome == "imported":
        report.imported += 1
    elif outcome == "matched":
        report.matched += 1
    else:
        report.ignored += 1
