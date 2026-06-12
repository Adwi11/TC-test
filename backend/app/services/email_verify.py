from __future__ import annotations
import logging
from dataclasses import dataclass

import httpx


log = logging.getLogger(__name__)

VERIFY_URL = "https://api.mailcheck.ai/email/"


@dataclass
class VerifyResult:
    """Outcome of an HTTP-level email validity check."""

    deliverable: bool
    reason: str
    mx: bool | None = None
    disposable: bool | None = None
    fail_open: bool = False


async def verify_email(email: str) -> VerifyResult:
    """Check if the email's domain has MX records and isn't disposable; fail-open on errors."""
    try:
        async with httpx.AsyncClient(timeout=8.0) as cli:
            r = await cli.get(f"{VERIFY_URL}{email}")
    except Exception as e:
        log.warning("email verify request failed: %s", type(e).__name__)
        return VerifyResult(deliverable=True, reason=f"verify api error: {type(e).__name__}", fail_open=True)

    if r.status_code >= 400:
        log.warning("email verify api %s: %s", r.status_code, r.text[:200])
        return VerifyResult(deliverable=True, reason=f"verify api {r.status_code}", fail_open=True)

    try:
        data = r.json()
    except Exception:
        return VerifyResult(deliverable=True, reason="verify api: bad json", fail_open=True)

    mx = bool(data.get("mx"))
    disposable = bool(data.get("disposable"))
    api_reason = (data.get("reason") or "").strip() or "n/a"

    if not mx:
        return VerifyResult(deliverable=False, reason=f"no mx records ({api_reason})", mx=mx, disposable=disposable)
    if disposable:
        return VerifyResult(deliverable=False, reason=f"disposable domain ({api_reason})", mx=mx, disposable=disposable)
    return VerifyResult(deliverable=True, reason=api_reason or "mx ok", mx=mx, disposable=disposable)
