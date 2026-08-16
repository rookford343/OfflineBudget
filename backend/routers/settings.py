"""Server configuration API for the Settings page.

Admin-only throughout: these are server-wide values, not per-user
preferences, so a non-admin household member must not be able to read the
SMTP host or repoint the daily report at a different address.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from backend import models, schemas
from backend.dependencies import get_db, require_admin
from backend.services import app_settings
from backend.services.crypto import is_encryption_configured, EncryptionNotConfigured

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=schemas.AppSettingsOut)
def read_settings(db: Session = Depends(get_db), _: models.User = Depends(require_admin)):
    """Current effective config. Secrets are reported as set/unset only --
    the stored value never leaves the server, so opening this page cannot
    leak the SMTP password into a browser, a proxy log, or a screenshot."""
    values = {}
    for key, (_typ, is_secret) in app_settings.EDITABLE.items():
        if is_secret:
            continue
        values[key.lower()] = app_settings.get_effective(db, key)

    smtp_pass_set = bool(app_settings.get_effective(db, "SMTP_PASS"))

    return schemas.AppSettingsOut(
        **values,
        smtp_pass_set=smtp_pass_set,
        encryption_configured=is_encryption_configured(),
        env_status=[schemas.EnvStatusEntry(**e) for e in app_settings.env_status()],
    )


@router.patch("", response_model=schemas.AppSettingsOut)
def update_settings(
    body: schemas.AppSettingsUpdate,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_admin),
):
    payload = body.model_dump(exclude_unset=True)

    # The frontend echoes the mask back when the user didn't touch the
    # password field. Treating that as a real value would overwrite the
    # stored secret with literal asterisks and silently break SMTP login.
    if payload.get("smtp_pass") == app_settings.SECRET_PLACEHOLDER:
        payload.pop("smtp_pass")

    for field, value in payload.items():
        key = field.upper()
        if key not in app_settings.EDITABLE:
            raise HTTPException(status_code=400, detail=f"{key} is not an editable setting")
        try:
            app_settings.set_value(db, key, value)
        except EncryptionNotConfigured as exc:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Can't store a secret without an encryption key. Set "
                    "APP_ENCRYPTION_KEY in .env, then save again. "
                    f"({exc})"
                ),
            ) from exc

    db.commit()
    return read_settings(db=db, _=_)


@router.post("/test-email", status_code=status.HTTP_200_OK)
def send_test_email(db: Session = Depends(get_db), user: models.User = Depends(require_admin)):
    """Send a real test email through the CURRENT effective config, to the
    configured report recipients. The only honest way to verify SMTP: a
    green form field proves nothing about whether mail actually leaves."""
    from backend.services.email_service import send_email_via

    recipients = app_settings.get_recipients(db, user)
    if not recipients:
        raise HTTPException(status_code=400, detail="No report recipients configured")
    if not app_settings.get_effective(db, "SMTP_HOST"):
        raise HTTPException(status_code=400, detail="SMTP host is not configured")

    sent, errors = [], []
    for r in recipients:
        ok, err = send_email_via(
            db, r, "OfflineBudget test email",
            "<p>If you're reading this, OfflineBudget can send mail.</p>",
            "If you're reading this, OfflineBudget can send mail.",
        )
        (sent if ok else errors).append(r if ok else f"{r}: {err}")

    if errors and not sent:
        raise HTTPException(status_code=502, detail="; ".join(errors))
    return {"sent_to": sent, "errors": errors}


@router.post("/run-daily-summary", status_code=status.HTTP_200_OK)
def run_daily_summary_now(
    to_self_only: bool = False,
    include_digest: bool = False,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_admin),
):
    """Send the real Daily Summary on demand, outside the schedule.

    Exists because the scheduled job is the only thing that ever produced
    this email, so reviewing a formatting or figure change meant waiting for
    the next morning's run. Builds through the same generator the scheduler
    uses, so what arrives is what the schedule would have sent -- a preview
    that rendered differently would defeat the purpose.

    `to_self_only` restricts delivery to the admin's own address: a report
    being checked for accuracy usually should not reach the rest of the
    household first. It does NOT touch scheduler state, so a manual run
    neither satisfies nor suppresses that day's scheduled send.
    """
    from backend.services.email_service import send_email_via
    from backend.services.summary_generator import generate_daily_summary, generate_weekly_digest
    from datetime import date

    if not app_settings.get_effective(db, "SMTP_HOST"):
        raise HTTPException(status_code=400, detail="SMTP host is not configured")

    if to_self_only:
        recipients = [user.email] if user.email else []
    else:
        recipients = app_settings.get_recipients(db, user)
    if not recipients:
        raise HTTPException(status_code=400, detail="No report recipients configured")

    weekly_digest = None
    if include_digest:
        checking = db.query(models.Account).filter(
            models.Account.user_id == user.id,
            models.Account.type == models.AccountType.checking,
            models.Account.is_active == True,
        ).first()
        if checking:
            weekly_digest = generate_weekly_digest(db, user, checking.id)

    html_body, text_body = generate_daily_summary(db, user, weekly_digest=weekly_digest)
    subject = f"Daily Budget Summary \u2014 {date.today().strftime('%B %-d, %Y')}"
    if weekly_digest is not None:
        subject += " + Weekly Digest"

    sent, errors = [], []
    for r in recipients:
        ok, err = send_email_via(db, r, subject, html_body, text_body)
        (sent if ok else errors).append(r if ok else f"{r}: {err}")

    if errors and not sent:
        raise HTTPException(status_code=502, detail="; ".join(errors))
    return {"sent_to": sent, "errors": errors, "subject": subject}
