from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from backend import models, schemas
from backend.dependencies import get_db, get_current_user
from backend.services.crypto import encrypt, EncryptionNotConfigured
from backend.services.simplefin_client import claim_setup_token, fetch_accounts, SimpleFinError
from backend.services.bank_sync_service import sync_connection

router = APIRouter(prefix="/bank-sync", tags=["bank-sync"])


def _get_owned_connection(db: Session, user: models.User, connection_id: int) -> models.BankConnection:
    connection = db.get(models.BankConnection, connection_id)
    if not connection or connection.user_id != user.id:
        raise HTTPException(status_code=404, detail="Connection not found")
    return connection


@router.post("/connect", response_model=schemas.BankConnectionConnectResponse, status_code=status.HTTP_201_CREATED)
def connect(
    body: schemas.BankConnectionConnectRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    try:
        access_url = claim_setup_token(body.setup_token)
    except SimpleFinError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    try:
        encrypted = encrypt(access_url)
    except EncryptionNotConfigured as exc:
        raise HTTPException(status_code=400, detail=str(exc))

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
    connections = db.query(models.BankConnection).filter(
        models.BankConnection.user_id == user.id,
        models.BankConnection.status == models.BankConnectionStatus.active,
    ).all()
    errors = []
    for connection in connections:
        sync_connection(db, connection)
        if connection.last_error:
            errors.append(connection.last_error)
    return schemas.BankSyncNowResponse(synced_connections=len(connections), errors=errors)


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def disconnect(
    connection_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    connection = _get_owned_connection(db, user, connection_id)
    db.delete(connection)
    db.commit()
