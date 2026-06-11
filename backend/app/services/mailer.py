from __future__ import annotations
import logging
import ssl
from email.message import EmailMessage
import aiosmtplib

from app.config import get_settings


log = logging.getLogger(__name__)


def _mask_email(addr: str) -> str:
    """Mask an email address for safe logging."""
    if "@" not in addr:
        return "***"
    local, domain = addr.split("@", 1)
    keep = local[:2]
    return f"{keep}***@{domain}"


async def send_email(to: str, subject: str, body: str) -> tuple[bool, str | None]:
    """Send a plain-text email via Gmail SMTP using STARTTLS; returns (ok, error)."""
    s = get_settings()
    if not (s.smtp_user and s.smtp_pass and s.smtp_from):
        return False, "smtp not configured"
    msg = EmailMessage()
    msg["From"] = s.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        ctx = ssl.create_default_context()
        await aiosmtplib.send(
            msg,
            hostname=s.smtp_host,
            port=s.smtp_port,
            start_tls=True,
            username=s.smtp_user,
            password=s.smtp_pass,
            tls_context=ctx,
            timeout=30,
        )
        log.info("email sent to=%s subject=%r", _mask_email(to), subject)
        return True, None
    except Exception as e:
        detail = str(e)[:300]
        log.warning("email send failed to=%s err=%s detail=%s", _mask_email(to), type(e).__name__, detail)
        return False, f"{type(e).__name__}: {detail}"
