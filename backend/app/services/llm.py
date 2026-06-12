from __future__ import annotations
import json
import logging
from typing import Any
import httpx

from app.config import get_settings


log = logging.getLogger(__name__)


class OllamaError(RuntimeError):
    """Raised when an Ollama Cloud call fails."""


def _client() -> httpx.AsyncClient:
    """Build an authenticated httpx client for Ollama Cloud."""
    s = get_settings()
    return httpx.AsyncClient(
        base_url=s.ollama_base_url.rstrip("/"),
        headers={"Authorization": f"Bearer {s.ollama_api_key}", "Content-Type": "application/json"},
        timeout=httpx.Timeout(120.0, connect=15.0),
    )


async def chat(messages: list[dict], *, model: str | None = None, tools: list[dict] | None = None,
               format_json: bool = False) -> dict:
    """Call Ollama Cloud /api/chat once and return the full response JSON."""
    s = get_settings()
    payload: dict[str, Any] = {
        "model": model or s.extraction_model,
        "messages": messages,
        "stream": False,
    }
    if tools:
        payload["tools"] = tools
    if format_json:
        payload["format"] = "json"
    async with _client() as cli:
        r = await cli.post("/api/chat", json=payload)
    if r.status_code >= 400:
        raise OllamaError(f"ollama {r.status_code}: {r.text[:300]}")
    return r.json()


EXTRACT_SYSTEM = (
    "You extract structured candidate information from a resume. "
    "Return ONLY a single JSON object, no prose, no markdown fences. "
    "Schema: {name: string|null, email: string|null, phone: string|null, "
    "company: string|null, designation: string|null, skills: string[], "
    "confidence: {name: number, email: number, phone: number, company: number, "
    "designation: number, skills: number}}. "
    "All confidence values are floats in [0,1] reflecting your certainty per field. "
    "Use null when a field is not present; never invent values."
)


def _strip_json(raw: str) -> str:
    """Strip markdown fences and leading text so json.loads can succeed."""
    s = raw.strip()
    if s.startswith("```"):
        s = s.strip("`")
        nl = s.find("\n")
        if nl != -1:
            s = s[nl + 1:]
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        s = s[start:end + 1]
    return s


async def extract_fields(text: str) -> dict:
    """Extract structured candidate fields from raw resume text."""
    trimmed = text[:18000]
    resp = await chat(
        [
            {"role": "system", "content": EXTRACT_SYSTEM},
            {"role": "user", "content": f"Resume text:\n{trimmed}"},
        ],
        format_json=True,
    )
    content = resp.get("message", {}).get("content", "") or ""
    try:
        return json.loads(_strip_json(content))
    except Exception as e:
        log.warning("llm json parse failed: %s; raw=%r", e, content[:300])
        return {
            "name": None, "email": None, "phone": None, "company": None,
            "designation": None, "skills": [],
            "confidence": {k: 0.0 for k in ("name", "email", "phone", "company", "designation", "skills")},
        }


REEXTRACT_EMAIL_SYSTEM = (
    "You are re-reading raw resume text to find the candidate's correct email address. "
    "A previous attempt produced an email that failed validation, so look harder.\n\n"
    "Rules:\n"
    "- Scan the entire text including headers, footers, contact lines, and any URL-like tokens.\n"
    "- Normalise obfuscated forms: 'asha [at] gmail [dot] com' -> 'asha@gmail.com'; "
    "  collapse whitespace; strip surrounding punctuation.\n"
    "- Reject the previously rejected addresses. Pick the next-most-likely real candidate email.\n"
    "- Prefer addresses that look personal (real names, common providers) over generic or "
    "  template placeholders (e.g. 'example.com', 'yourname@', 'firstname.lastname@company').\n"
    "- If you cannot find any plausible email, return {\"email\": null, \"confidence\": 0}.\n"
    "- Return ONLY a JSON object: {\"email\": string|null, \"confidence\": number 0..1}."
)


async def reextract_email(text: str, *, rejected: list[str], reason: str) -> dict:
    """Re-scan the source text for a better email after the previous one failed verification."""
    trimmed = text[:18000]
    user = (
        f"Resume text:\n{trimmed}\n\n"
        f"Previously rejected emails: {rejected}\n"
        f"Rejection reason: {reason}\n\n"
        "Find a different, valid email address from the resume."
    )
    resp = await chat(
        [
            {"role": "system", "content": REEXTRACT_EMAIL_SYSTEM},
            {"role": "user", "content": user},
        ],
        format_json=True,
    )
    content = resp.get("message", {}).get("content", "") or ""
    try:
        data = json.loads(_strip_json(content))
        return {"email": data.get("email"), "confidence": float(data.get("confidence") or 0.0)}
    except Exception as e:
        log.warning("reextract json parse failed: %s; raw=%r", e, content[:300])
        return {"email": None, "confidence": 0.0}
