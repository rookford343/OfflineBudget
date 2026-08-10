from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session
from backend import models
from backend import schemas
from backend.auth import hash_password, verify_password, create_access_token
from backend.dependencies import get_db, get_current_user, get_requester
from backend.seed import seed_default_categories
from backend.config import settings
from backend.services.email_service import send_email
from backend.services.password_reset import (
    create_reset_token,
    consume_reset_token,
    issue_recovery_code,
    verify_and_consume_recovery_code,
)
from backend.services.rate_limiter import allow as rate_limit_allow

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=schemas.TokenOut, status_code=status.HTTP_201_CREATED)
def register(body: schemas.UserCreate, db: Session = Depends(get_db)):
    if db.query(models.User).filter(models.User.username == body.username).first():
        raise HTTPException(status_code=400, detail="Username already taken")
    user = models.User(
        username=body.username,
        hashed_password=hash_password(body.password),
        display_name=body.display_name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    seed_default_categories(db, user)
    token = create_access_token(user.id, user.username)
    return schemas.TokenOut(access_token=token, user=schemas.UserOut.model_validate(user))


@router.post("/login", response_model=schemas.TokenOut)
def login(body: schemas.LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == body.username).first()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")
    token = create_access_token(user.id, user.username)
    return schemas.TokenOut(access_token=token, user=schemas.UserOut.model_validate(user))


@router.get("/me", response_model=schemas.UserOut)
def me(current_user: models.User = Depends(get_requester)):
    return current_user


@router.patch("/me", response_model=schemas.UserOut)
def update_me(
    body: schemas.UserUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_requester),
):
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(current_user, field, value)
    db.commit()
    db.refresh(current_user)
    return current_user


@router.patch("/me/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: schemas.UserPasswordChange,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_requester),
):
    if not verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    current_user.hashed_password = hash_password(body.new_password)
    db.commit()


@router.post("/me/send-test-email", status_code=status.HTTP_204_NO_CONTENT)
def send_test_email(
    current_user: models.User = Depends(get_requester),
):
    if not current_user.email:
        raise HTTPException(status_code=400, detail="No email address set on your account")
    from backend.services.email_service import parse_recipients
    for recipient in parse_recipients(current_user.email):
        send_email(
            recipient,
            "OfflineBudget — Test Email",
            "<h2 style='color:#4f46e5'>It works!</h2><p>Your OfflineBudget email is configured correctly.</p>",
            "OfflineBudget — Test Email\n\nYour email is configured correctly.",
        )


@router.post("/forgot-password", status_code=status.HTTP_204_NO_CONTENT)
def forgot_password(
    body: schemas.ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Always returns 204, whether or not the account/email/SMTP exist or
    the rate limit was hit — prevents enumeration and abuse signals alike.
    The email send is deferred to a background task so a slow/blackholed
    SMTP host can't hold the request (and a threadpool worker) open."""
    if not rate_limit_allow(f"forgot:{body.username}", limit=5, window_seconds=3600):
        return
    user = db.query(models.User).filter(models.User.username == body.username).first()
    if user and user.email and settings.SMTP_HOST:
        raw_token = create_reset_token(db, user)
        link = f"{settings.frontend_url}/reset-password?token={raw_token}"
        background_tasks.add_task(
            send_email,
            user.email,
            "OfflineBudget — Reset Your Password",
            f"<p>Click below to reset your password. This link expires in 15 minutes.</p>"
            f"<p><a href='{link}'>{link}</a></p>",
            f"Reset your password (expires in 15 minutes): {link}",
        )


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(body: schemas.ResetPasswordRequest, db: Session = Depends(get_db)):
    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    if not consume_reset_token(db, body.token, body.new_password):
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")


@router.post("/reset-password-with-code", status_code=status.HTTP_204_NO_CONTENT)
def reset_password_with_code(body: schemas.ResetPasswordWithCodeRequest, db: Session = Depends(get_db)):
    if not rate_limit_allow(f"reset-code:{body.username}", limit=5, window_seconds=3600):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")
    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    user = db.query(models.User).filter(models.User.username == body.username).first()
    if not user or not verify_and_consume_recovery_code(db, user, body.code, body.new_password):
        raise HTTPException(status_code=400, detail="Invalid recovery code")


@router.post("/me/recovery-code", response_model=schemas.RecoveryCodeOut)
def generate_recovery_code(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_requester),
):
    code = issue_recovery_code(db, current_user)
    return schemas.RecoveryCodeOut(code=code, created_at=current_user.recovery_code_created_at)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    body: schemas.DeleteAccountRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_requester),
):
    if not verify_password(body.password, current_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Incorrect password")
    db.delete(current_user)
    db.commit()
