from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from backend import models, schemas
from backend.dependencies import get_db, get_current_user
from backend.services.crypto import assert_encryption_configured, decrypt, encrypt, EncryptionNotConfigured
from backend.services.simplefin_client import claim_setup_token, fetch_accounts, SimpleFinError
from backend.services.bank_sync_service import sync_connection

router = APIRouter(prefix="/bank-sync", tags=["bank-sync"])


def _get_owned_connection(db: Session, user: models.User, connection_id: int) -> models.BankConnection:
    connection = db.get(models.BankConnection, connection_id)
    if not connection or connection.user_id != user.id:
        raise HTTPException(status_code=404, detail="Connection not found")
    return connection


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
    """Re-discover the SimpleFIN accounts on an existing connection.

    /connect returns this list exactly once, and the setup token is consumed by
    then -- so without this endpoint, losing that response (refresh, navigating
    away, closing the mapping UI early) means the user can never map the
    remaining accounts without disconnecting and buying a new token.
    """
    connection = _get_owned_connection(db, user, connection_id)
    try:
        access_url = decrypt(connection.access_url_encrypted)
    except EncryptionNotConfigured as exc:
        raise HTTPException(status_code=400, detail=str(exc))
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


@router.post("/sync-now", response_model=schemas.BankSyncNowResponse)
def sync_now(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    # Errored connections are deliberately included -- sync_connection is the
    # only path that can restore `active`, so skipping them here would make a
    # transient failure permanent and leave "Sync Now" reporting 0 forever.
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


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def disconnect(
    connection_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    connection = _get_owned_connection(db, user, connection_id)
    db.delete(connection)
    db.commit()
