import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


def parse_recipients(value: str | None) -> list[str]:
    """Comma-separated email addresses -> a clean list. A User.email field
    holds one or more addresses this way -- "dan@x.com" for a single
    recipient, "dan@x.com, wife@x.com" to reach more than one person."""
    if not value:
        return []
    return [e.strip() for e in value.split(",") if e.strip()]


def deliver(cfg: dict, to: str, subject: str, html_body: str, text_body: str) -> tuple[bool, str | None]:
    """The actual SMTP conversation. Returns (ok, error) instead of raising so
    one bad recipient can't abort a multi-recipient send. Takes a config
    already resolved by smtp_config(db) so a background task can send after
    the request's DB session has closed."""
    if not cfg.get("host"):
        return False, "SMTP host is not configured"
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = cfg.get("sender") or cfg.get("user") or "noreply@offlinebudget"
        msg["To"] = to
        if text_body:
            msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))
        with smtplib.SMTP(cfg["host"], cfg.get("port") or 587, timeout=10) as smtp:
            smtp.ehlo()
            smtp.starttls()
            if cfg.get("user") and cfg.get("password"):
                smtp.login(cfg["user"], cfg["password"])
            smtp.sendmail(msg["From"], [to], msg.as_string())
        return True, None
    except Exception as exc:
        logger.error("Failed to send email to %s: %s", to, exc)
        return False, str(exc)


def smtp_config(db) -> dict:
    """Effective SMTP settings: Settings-page overrides on top of .env."""
    from backend.services import app_settings
    return {
        "host": app_settings.get_effective(db, "SMTP_HOST"),
        "port": app_settings.get_effective(db, "SMTP_PORT"),
        "user": app_settings.get_effective(db, "SMTP_USER"),
        "password": app_settings.get_effective(db, "SMTP_PASS"),
        "sender": app_settings.get_effective(db, "SMTP_FROM"),
    }


def send_email_via(db, to: str, subject: str, html_body: str, text_body: str = "") -> tuple[bool, str | None]:
    """Send using the DB-backed effective config. Preferred entry point."""
    return deliver(smtp_config(db), to, subject, html_body, text_body)
