import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from backend.config import settings

logger = logging.getLogger(__name__)


def send_email(to: str, subject: str, html_body: str, text_body: str = "") -> None:
    """Send email via SMTP with STARTTLS. No-ops silently when SMTP_HOST is not configured."""
    if not settings.SMTP_HOST:
        return
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.SMTP_FROM or settings.SMTP_USER or "noreply@offlinebudget"
        msg["To"] = to
        if text_body:
            msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as smtp:
            smtp.ehlo()
            smtp.starttls()
            if settings.SMTP_USER and settings.SMTP_PASS:
                smtp.login(settings.SMTP_USER, settings.SMTP_PASS)
            smtp.sendmail(msg["From"], [to], msg.as_string())
    except Exception as exc:
        logger.error("Failed to send email to %s: %s", to, exc)
