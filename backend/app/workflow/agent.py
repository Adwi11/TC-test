from __future__ import annotations
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Candidate, DocumentRequest
from app.services.confidence import EMAIL_RE
from app.services.email_verify import verify_email as verify_email_http
from app.services.llm import chat, reextract_email
from app.services.mailer import send_email


EMAIL_REEXTRACT_MAX_TRIES = 2


log = logging.getLogger(__name__)

COOLDOWN_SECONDS = 30
AUTO_REQUEST_THRESHOLD = 0.75


def should_auto_request(candidate: Candidate) -> tuple[bool, str]:
    """Decide whether ingestion confidence is high enough to skip HR confirmation."""
    if not candidate.email or not EMAIL_RE.match(candidate.email):
        return False, "email missing or invalid"
    fc = candidate.field_confidence_json or {}
    if not fc:
        return False, "no confidence data"
    below = [
        (k, v.get("score", 0.0))
        for k, v in fc.items()
        if isinstance(v, dict) and v.get("score") is not None and v.get("score", 0.0) < AUTO_REQUEST_THRESHOLD
    ]
    if below:
        return False, f"fields below {AUTO_REQUEST_THRESHOLD:.0%}: " + ", ".join(f"{k}={s:.2f}" for k, s in below)
    return True, "all fields >= threshold"


AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": "Send a plain-text email to the candidate.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email address."},
                    "subject": {"type": "string", "description": "Email subject line."},
                    "body": {"type": "string", "description": "Plain text body of the email."},
                },
                "required": ["to", "subject", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "log_request",
            "description": "Persist the outcome of this document request.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["sent", "failed", "needs_email"]},
                    "recipient": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                    "error": {"type": "string"},
                },
                "required": ["status"],
            },
        },
    },
]


SYSTEM_PROMPT = (
    "You are an HR assistant. You will be given a candidate's profile and must request "
    "their PAN and Aadhaar copies via email.\n\n"
    "Rules:\n"
    "- Compose a SHORT, polite, professional email in plain text that:\n"
    "  (a) addresses the candidate by first name when available,\n"
    "  (b) asks for clear scans or photos of PAN card and Aadhaar card,\n"
    "  (c) reassures that documents will be handled confidentially,\n"
    "  (d) signs off as 'HR Team'.\n"
    "- DO NOT congratulate the candidate, do not mention a job offer, role, position, "
    "designation, company name, or onboarding status. The email is strictly a "
    "document-collection request and nothing more.\n"
    "- Subject line: 'PAN and Aadhaar documents request'.\n"
    "- Call send_email first, then call log_request with status='sent' on success or "
    "status='failed' (and the returned error) on failure.\n"
    "- Output ONLY tool calls; do not write prose to the user."
)


def _candidate_brief(c: Candidate) -> dict:
    """Compact JSON view of the candidate for the agent."""
    return {
        "id": c.id,
        "name": c.name,
        "email": c.email,
        "phone": c.phone,
        "company": c.company,
        "designation": c.designation,
        "skills": c.skills_json or [],
    }


def _extract_tool_calls(message: dict) -> list[dict]:
    """Pull tool_calls out of an Ollama assistant message regardless of shape."""
    calls = message.get("tool_calls") or []
    out: list[dict] = []
    for call in calls:
        fn = call.get("function") or {}
        name = fn.get("name")
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {}
        out.append({"name": name, "arguments": args or {}})
    return out


async def _recent_request(session: AsyncSession, candidate_id: int) -> DocumentRequest | None:
    """Return the most recent document request for a candidate, if any."""
    result = await session.execute(
        select(DocumentRequest).where(DocumentRequest.candidate_id == candidate_id)
        .order_by(desc(DocumentRequest.sent_at)).limit(1)
    )
    return result.scalars().first()


class CooldownError(Exception):
    """Raised when a request is attempted inside the cooldown window."""


async def run_request_agent(session: AsyncSession, candidate: Candidate) -> DocumentRequest:
    """Drive the tool-using agent to compose+send a document request and persist it."""
    recent = await _recent_request(session, candidate.id)
    if recent and recent.sent_at and recent.status == "sent":
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=COOLDOWN_SECONDS)
        if recent.sent_at.replace(tzinfo=timezone.utc) > cutoff:
            raise CooldownError("recent request still within cooldown")

    if not candidate.email or not EMAIL_RE.match(candidate.email):
        reason = "candidate has no email" if not candidate.email else f"invalid email format: {candidate.email}"
        req = DocumentRequest(
            candidate_id=candidate.id, channel="email",
            recipient=candidate.email, subject=None, body=None,
            status="needs_email", error=reason,
        )
        session.add(req)
        await session.commit()
        await session.refresh(req)
        return req

    rejected: list[str] = []
    final_reason = ""
    for attempt in range(EMAIL_REEXTRACT_MAX_TRIES + 1):
        verify = await verify_email_http(candidate.email)
        log.info(
            "agent[verify_email] attempt=%d email=%s deliverable=%s mx=%s disposable=%s reason=%s fail_open=%s",
            attempt, candidate.email, verify.deliverable, verify.mx, verify.disposable, verify.reason, verify.fail_open,
        )
        if verify.deliverable:
            final_reason = ""
            break
        final_reason = verify.reason
        rejected.append(candidate.email)
        if attempt >= EMAIL_REEXTRACT_MAX_TRIES or not candidate.source_text:
            break
        guess = await reextract_email(candidate.source_text, rejected=rejected, reason=verify.reason)
        new_email = (guess.get("email") or "").strip() or None
        log.info("agent[reextract_email] attempt=%d candidate=%s new=%s confidence=%.2f",
                 attempt, candidate.email, new_email, float(guess.get("confidence") or 0.0))
        if not new_email or new_email in rejected or not EMAIL_RE.match(new_email):
            break
        candidate.email = new_email
        fc = dict(candidate.field_confidence_json or {})
        fc["email"] = {
            "score": round(float(guess.get("confidence") or 0.0), 3),
            "source": "reextract",
            "validated": True,
        }
        candidate.field_confidence_json = fc
        await session.commit()
        await session.refresh(candidate)

    if final_reason:
        req = DocumentRequest(
            candidate_id=candidate.id, channel="email",
            recipient=candidate.email, subject=None, body=None,
            status="needs_email",
            error=f"http verify failed after retries; tried={rejected}; last reason={final_reason}",
        )
        session.add(req)
        await session.commit()
        await session.refresh(req)
        return req

    settings = get_settings()
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "Candidate profile JSON:\n" + json.dumps(_candidate_brief(candidate))},
    ]

    persisted: DocumentRequest | None = None
    last_email_args: dict | None = None
    last_send_ok: bool | None = None
    last_send_err: str | None = None

    for turn in range(4):
        try:
            resp = await chat(messages, model=settings.agent_model, tools=AGENT_TOOLS)
        except Exception as e:
            log.warning("agent llm failed: %s", e)
            break
        message = resp.get("message", {}) or {}
        calls = _extract_tool_calls(message)
        log.info("agent[turn=%d] tool_calls=%s", turn, [c["name"] for c in calls])
        if not calls:
            break
        messages.append({"role": "assistant", "content": message.get("content", "") or "", "tool_calls": message.get("tool_calls", [])})
        terminated = False
        for call in calls:
            name = call["name"]
            args = call["arguments"]
            if name == "send_email":
                to = args.get("to") or candidate.email
                subject = args.get("subject") or "Onboarding documents"
                body = args.get("body") or ""
                ok, err = await send_email(to, subject, body)
                log.info("agent[send_email] ok=%s err=%s subject=%r", ok, err, subject)
                last_email_args = {"to": to, "subject": subject, "body": body}
                last_send_ok = ok
                last_send_err = err
                messages.append({
                    "role": "tool", "name": "send_email",
                    "content": json.dumps({"ok": ok, "error": err}),
                })
            elif name == "log_request":
                status_v = args.get("status") or ("sent" if last_send_ok else "failed")
                log.info("agent[log_request] status=%s", status_v)
                recipient = args.get("recipient") or (last_email_args or {}).get("to") or candidate.email
                subject = args.get("subject") or (last_email_args or {}).get("subject")
                body = args.get("body") or (last_email_args or {}).get("body")
                error = args.get("error") or last_send_err
                persisted = DocumentRequest(
                    candidate_id=candidate.id, channel="email",
                    recipient=recipient, subject=subject, body=body,
                    status=status_v, error=error,
                )
                session.add(persisted)
                await session.commit()
                await session.refresh(persisted)
                messages.append({"role": "tool", "name": "log_request", "content": json.dumps({"id": persisted.id})})
                terminated = True
            else:
                messages.append({"role": "tool", "name": name, "content": json.dumps({"error": "unknown tool"})})
        if terminated:
            break

    if persisted is None:
        status_v = "sent" if last_send_ok else ("failed" if last_send_ok is False else "failed")
        if last_email_args is None:
            recipient = candidate.email
            subject = "PAN and Aadhaar documents request"
            body = (
                f"Hi {(candidate.name or 'there').split()[0]},\n\n"
                "Please share clear scans or photos of your PAN card and Aadhaar card at your earliest convenience. "
                "These will be handled confidentially and used only for verification.\n\nThanks,\nHR Team"
            )
            ok, err = await send_email(recipient, subject, body)
            status_v = "sent" if ok else "failed"
            last_send_err = err
        else:
            recipient = last_email_args["to"]
            subject = last_email_args["subject"]
            body = last_email_args["body"]
        persisted = DocumentRequest(
            candidate_id=candidate.id, channel="email",
            recipient=recipient, subject=subject, body=body,
            status=status_v, error=last_send_err,
        )
        session.add(persisted)
        await session.commit()
        await session.refresh(persisted)
    return persisted
