import logging
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from backend import models, schemas
from backend.dependencies import get_db, get_current_user
from backend.services.crypto import assert_encryption_configured, decrypt, encrypt, EncryptionNotConfigured
from backend.services.simplefin_client import claim_setup_token, fetch_accounts, SimpleFinError
from backend.services.bank_sync_service import sync_connection
from backend.services.job_locks import _bank_sync_lock
from backend.services.plaid_client import (
    PlaidAccount, PlaidError, PlaidNotConfigured,
    create_link_token, exchange_public_token, get_accounts as get_plaid_accounts, remove_item,
)
from backend.services.plaid_sync_service import sync_plaid_connection
from backend.routers._shared import owned_or_404

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bank-sync", tags=["bank-sync"])


def _get_owned_connection(db: Session, user: models.User, connection_id: int) -> models.BankConnection:
    return owned_or_404(db, models.BankConnection, connection_id, user.id, "Connection not found")


def _assert_account_owned(db: Session, user_id: int, account_id: int) -> None:
    if not db.query(models.Account).filter(
        models.Account.id == account_id,
        models.Account.user_id == user_id,
    ).first():
        raise HTTPException(status_code=404, detail="Account not found")


def _assert_credit_card_owned(db: Session, user_id: int, card_id: int) -> None:
    if not db.query(models.CreditCard).filter(
        models.CreditCard.id == card_id,
        models.CreditCard.user_id == user_id,
    ).first():
        raise HTTPException(status_code=404, detail="Credit card not found")


def _plaid_http_error(exc: PlaidError) -> HTTPException:
    """PlaidNotConfigured -> 400 with the plain "add these env vars" message
    (no error-code prefix: there's nothing to configure around, just .env to
    edit). Every other PlaidError -> 422 with str(exc) ("CODE: message"),
    which PlaidError guarantees never carries a token or request body."""
    if isinstance(exc, PlaidNotConfigured):
        return HTTPException(status_code=400, detail=exc.message)
    return HTTPException(status_code=422, detail=str(exc))


def _plaid_account_out(account: PlaidAccount) -> schemas.BankConnectionAccountOut:
    return schemas.BankConnectionAccountOut(
        simplefin_account_id=account.id,
        name=account.name,
        org_name="Plaid",
        balance=account.current if account.current is not None else Decimal("0"),
        currency="USD",
        mask=account.mask,
        kind=account.subtype or account.type,
    )


def _find_active_link_for_target(
    db: Session, user_id: int, local_account_id: int | None, local_credit_card_id: int | None,
) -> models.BankConnectionAccountLink | None:
    """An active link, on any of this user's connections (either provider),
    that already targets this local account or card -- the one-active-link
    rule backing the Plaid cutover: a local account/card should have at most
    one provider feeding it at a time."""
    query = (
        db.query(models.BankConnectionAccountLink)
        .join(models.BankConnection)
        .filter(
            models.BankConnection.user_id == user_id,
            models.BankConnectionAccountLink.is_active == True,
        )
    )
    if local_account_id:
        query = query.filter(models.BankConnectionAccountLink.local_account_id == local_account_id)
    else:
        query = query.filter(models.BankConnectionAccountLink.local_credit_card_id == local_credit_card_id)
    return query.first()


@router.post("/connect", response_model=schemas.BankConnectionConnectResponse, status_code=status.HTTP_201_CREATED)
def connect(
    body: schemas.BankConnectionConnectRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    # Check the encryption key FIRST: a SimpleFIN setup token can only be
    # claimed once, so failing after claim_setup_token would burn the user's
    # token and force them back to the bank for a new one.
    try:
        assert_encryption_configured()
    except EncryptionNotConfigured as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        access_url = claim_setup_token(body.setup_token)
    except SimpleFinError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    encrypted = encrypt(access_url)

    connection = models.BankConnection(user_id=user.id, access_url_encrypted=encrypted)
    db.add(connection)
    db.commit()
    db.refresh(connection)

    try:
        accounts = fetch_accounts(access_url)
    except SimpleFinError as exc:
        raise HTTPException(status_code=422, detail=f"Connected, but failed to list accounts: {exc}")

    return schemas.BankConnectionConnectResponse(
        connection_id=connection.id,
        accounts=[
            schemas.BankConnectionAccountOut(
                simplefin_account_id=a.id, name=a.name, org_name=a.org_name,
                balance=a.balance, currency=a.currency,
            )
            for a in accounts
        ],
    )


@router.post("/plaid/link-token", response_model=schemas.PlaidLinkTokenResponse)
def plaid_link_token(
    body: schemas.PlaidLinkTokenRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    access_token = None
    if body.connection_id is not None:
        connection = _get_owned_connection(db, user, body.connection_id)
        if connection.provider != "plaid":
            raise HTTPException(status_code=400, detail="Connection is not a Plaid connection")
        try:
            access_token = decrypt(connection.access_url_encrypted)
        except EncryptionNotConfigured as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    try:
        link_token = create_link_token(str(user.id), access_token=access_token)
    except PlaidError as exc:
        raise _plaid_http_error(exc)
    return schemas.PlaidLinkTokenResponse(link_token=link_token)


@router.post("/plaid/exchange", response_model=schemas.BankConnectionConnectResponse, status_code=status.HTTP_201_CREATED)
def plaid_exchange(
    body: schemas.PlaidExchangeRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    # Same reasoning as /connect: check the encryption key before spending
    # the public token, which Plaid lets a caller exchange only once.
    try:
        assert_encryption_configured()
    except EncryptionNotConfigured as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        access_token, item_id = exchange_public_token(body.public_token)
    except PlaidError as exc:
        raise _plaid_http_error(exc)

    connection = models.BankConnection(
        user_id=user.id,
        provider="plaid",
        plaid_item_id=item_id,
        access_url_encrypted=encrypt(access_token),
        cutover_date=date.today(),
    )
    db.add(connection)
    db.commit()
    db.refresh(connection)

    try:
        accounts = get_plaid_accounts(access_token)
    except PlaidError as exc:
        raise HTTPException(status_code=422, detail=f"Connected, but failed to list accounts: {exc}")

    return schemas.BankConnectionConnectResponse(
        connection_id=connection.id,
        accounts=[_plaid_account_out(a) for a in accounts],
    )


@router.post("/{connection_id}/link", response_model=schemas.BankConnectionLinkOut, status_code=status.HTTP_201_CREATED)
def link_account(
    connection_id: int,
    body: schemas.BankConnectionLinkRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    connection = _get_owned_connection(db, user, connection_id)
    if not body.local_account_id and not body.local_credit_card_id:
        raise HTTPException(status_code=400, detail="Provide either local_account_id or local_credit_card_id")
    if body.local_account_id:
        _assert_account_owned(db, user.id, body.local_account_id)
    if body.local_credit_card_id:
        _assert_credit_card_owned(db, user.id, body.local_credit_card_id)

    existing_link = _find_active_link_for_target(db, user.id, body.local_account_id, body.local_credit_card_id)
    if existing_link is not None:
        if not body.switch_existing:
            target_label = "account" if body.local_account_id else "credit card"
            raise HTTPException(status_code=409, detail={
                "message": f"This {target_label} is already synced by another connection",
                "existing_link_id": existing_link.id,
            })
        existing_link.is_active = False

    link = models.BankConnectionAccountLink(
        connection_id=connection.id,
        simplefin_account_id=body.simplefin_account_id,
        simplefin_account_name=body.simplefin_account_name,
        local_account_id=body.local_account_id,
        local_credit_card_id=body.local_credit_card_id,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


@router.get("/{connection_id}/accounts", response_model=list[schemas.BankConnectionAccountOut])
def list_connection_accounts(
    connection_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Re-discover the accounts on an existing connection, dispatching on
    provider.

    /connect and /plaid/exchange each return this list exactly once, and the
    one-time token (setup token or public token) is consumed by then -- so
    without this endpoint, losing that response (refresh, navigating away,
    closing the mapping UI early) means the user can never map the
    remaining accounts without disconnecting and starting over.
    """
    connection = _get_owned_connection(db, user, connection_id)
    try:
        access_url = decrypt(connection.access_url_encrypted)
    except EncryptionNotConfigured as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if connection.provider == "plaid":
        try:
            accounts = get_plaid_accounts(access_url)
        except PlaidError as exc:
            raise _plaid_http_error(exc)
        return [_plaid_account_out(a) for a in accounts]

    try:
        accounts = fetch_accounts(access_url)
    except SimpleFinError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return [
        schemas.BankConnectionAccountOut(
            simplefin_account_id=a.id, name=a.name, org_name=a.org_name,
            balance=a.balance, currency=a.currency,
        )
        for a in accounts
    ]


@router.get("/status", response_model=list[schemas.BankConnectionStatusOut])
def status_list(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    return db.query(models.BankConnection).filter(models.BankConnection.user_id == user.id).all()


@router.get("/scheduler-status", response_model=list[schemas.SchedulerRunOut])
def scheduler_status(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """Not scoped to `user` -- SchedulerRun tracks the two background jobs
    themselves (daily_summary, bank_sync), which run once per process across
    every user, not per-user state. `user` stays a dependency purely to keep
    this endpoint authenticated like every other route in the app."""
    return db.query(models.SchedulerRun).all()


@router.post("/sync-now", response_model=schemas.BankSyncNowResponse)
def sync_now(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    # Shares _bank_sync_lock with the scheduled job (main.py's
    # _run_bank_sync) so a click on "Sync Now" during a scheduled sync can't
    # race it the same way the cron trigger and the sweep's retry used to
    # race each other. Non-blocking: rather than queue behind a sync already
    # in flight (which could be seconds or minutes), 409 immediately --
    # errorBus.ts's describeError() surfaces an HTTPException's `detail` via
    # the global mutation-error toast, which is the frontend's existing
    # handling for this endpoint today (AccountsTab.tsx defines no
    # onSuccess-adjacent error rendering of its own).
    if not _bank_sync_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A sync is already running")
    try:
        # Errored connections are deliberately included -- sync_connection is
        # the only path that can restore `active`, so skipping them here
        # would make a transient failure permanent and leave "Sync Now"
        # reporting 0 forever.
        connections = db.query(models.BankConnection).filter(
            models.BankConnection.user_id == user.id,
            models.BankConnection.status != models.BankConnectionStatus.disconnected,
        ).all()
        errors = []
        total_imported = 0
        total_skipped = 0
        for connection in connections:
            imported, skipped = sync_connection(db, connection)
            total_imported += imported
            total_skipped += skipped
            if connection.last_error:
                errors.append(connection.last_error)
        return schemas.BankSyncNowResponse(
            synced_connections=len(connections), errors=errors,
            imported=total_imported, skipped_duplicates=total_skipped,
        )
    finally:
        _bank_sync_lock.release()


def _first_import_response(report) -> schemas.PlaidFirstImportResponse:
    return schemas.PlaidFirstImportResponse(
        imported=report.imported, matched=report.matched, ignored=report.ignored,
        rows=[
            schemas.PlaidFirstImportRow(
                date=r.date, amount=r.amount, description=r.description, outcome=r.outcome, target=r.target,
            )
            for r in report.rows
        ],
    )


@router.post("/{connection_id}/plaid/first-import", response_model=schemas.PlaidFirstImportResponse)
def plaid_first_import(
    connection_id: int,
    confirm: bool = False,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    connection = _get_owned_connection(db, user, connection_id)
    if connection.provider != "plaid":
        raise HTTPException(status_code=400, detail="Connection is not a Plaid connection")
    if connection.sync_cursor is not None:
        raise HTTPException(status_code=409, detail="First import already done")

    if not confirm:
        try:
            report = sync_plaid_connection(db, connection, dry_run=True)
        except PlaidError as exc:
            raise _plaid_http_error(exc)
        return _first_import_response(report)

    # Share _bank_sync_lock with /sync-now and the scheduled jobs: confirming
    # the first import still runs a real /transactions/sync, so it can race
    # them exactly the way sync_now already guards against. Non-blocking, so
    # a confirm click never queues behind a sync that could take a while.
    if not _bank_sync_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A sync is already running")
    try:
        try:
            report = sync_plaid_connection(db, connection, first_import=True)
        except PlaidError as exc:
            raise _plaid_http_error(exc)
    finally:
        _bank_sync_lock.release()
    return _first_import_response(report)


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def disconnect(
    connection_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    connection = _get_owned_connection(db, user, connection_id)
    if connection.provider == "plaid":
        try:
            remove_item(decrypt(connection.access_url_encrypted))
        except PlaidError as exc:
            logger.warning("Plaid remove_item failed for connection %s: %s", connection_id, exc.code)
        except Exception as exc:
            # Never let this block the local delete -- the user's record of
            # the connection must not become un-deletable because Plaid (or
            # our own decrypt) is unhappy. Logs the exception TYPE only, per
            # the global rule that nothing here logs raw exception text.
            logger.warning("Plaid remove_item failed for connection %s: %s", connection_id, type(exc).__name__)
    db.delete(connection)
    db.commit()
