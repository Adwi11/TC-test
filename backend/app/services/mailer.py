from __future__ import annotations
import logging
import ssl
from email.message import EmailMessage

import aiosmtplib
import httpx

from app.config import get_settings


log = logging.getLogger(__name__)


def _mask_email(addr: str) -> str:
    """Mask an email address for safe logging."""
    if "@" not in addr:
        return "***"
    local, domain = addr.split("@", 1)
    return f"{local[:2]}***@{domain}"


async def _send_via_resend(to: str, subject: str, body: str) -> tuple[bool, str | None]:
    """Send a plain-text email via Resend's HTTPS API; returns (ok, error)."""
    s = get_settings()
    payload = {
        "from": s.resend_from or s.smtp_from or "onboarding@resend.dev",
        "to": [to],
        "subject": subject,
        "text": body,
    }
    headers = {"Authorization": f"Bearer {s.resend_api_key}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=30) as cli:
            r = await cli.post("https://api.resend.com/emails", json=payload, headers=headers)
        if r.status_code >= 400:
            return False, f"resend {r.status_code}: {r.text[:200]}"
        log.info("email sent (resend) to=%s subject=%r", _mask_email(to), subject)
        return True, None
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:200]}"


async def _send_via_smtp(to: str, subject: str, body: str) -> tuple[bool, str | None]:
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
        await aiosmtplib.send(
            msg,
            hostname=s.smtp_host,
            port=s.smtp_port,
            start_tls=True,
            username=s.smtp_user,
            password=s.smtp_pass,
            tls_context=ssl.create_default_context(),
            timeout=30,
        )
        log.info("email sent (smtp) to=%s subject=%r", _mask_email(to), subject)
        return True, None
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:200]}"


async def send_email(to: str, subject: str, body: str) -> tuple[bool, str | None]:
    """Send via Resend HTTPS when configured (works on Render), otherwise Gmail SMTP."""
    s = get_settings()
    if s.resend_api_key:
        ok, err = await _send_via_resend(to, subject, body)
        if ok:
            return ok, err
        log.warning("email send failed (resend) to=%s err=%s", _mask_email(to), err)
        return ok, err
    ok, err = await _send_via_smtp(to, subject, body)
    if not ok:
        log.warning("email send failed (smtp) to=%s err=%s", _mask_email(to), err)
    return ok, err
