from __future__ import annotations
import re
from typing import Any


EMAIL_RE = re.compile(r"^[\w.+-]+@[A-Za-z0-9-]+\.[A-Za-z0-9.-]+$")


def _normalize_phone(raw: str | None) -> str | None:
    """Normalise an Indian phone number into a 10-digit local form when possible."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits if len(digits) == 10 else raw.strip()


def _clamp(x: float) -> float:
    """Clamp a float to [0,1]."""
    return max(0.0, min(1.0, float(x)))


def score_fields(raw: dict[str, Any], *, route: str) -> dict[str, Any]:
    """Score per-field confidence using LLM self-confidence; rule-check email only."""
    name = (raw.get("name") or None)
    email = (raw.get("email") or None)
    phone_in = (raw.get("phone") or None)
    company = (raw.get("company") or None)
    designation = (raw.get("designation") or None)
    skills = raw.get("skills") or []
    if isinstance(skills, str):
        skills = [s.strip() for s in skills.split(",") if s.strip()]
    skills = [s for s in skills if isinstance(s, str) and s.strip()][:30]

    phone = _normalize_phone(phone_in) if phone_in else None
    self_conf = raw.get("confidence") or {}
    route_src = "ocr" if route == "ocr" else ("vision" if route == "vision" else "llm")

    def passthrough(key: str, value) -> dict:
        """Confidence record using only the LLM's self-reported score."""
        present = value is not None and (value != "" if isinstance(value, str) else True)
        score = _clamp(float(self_conf.get(key, 0.0) or 0.0)) if present else 0.0
        return {"score": round(score, 3), "source": route_src, "validated": None}

    email_valid = bool(email and EMAIL_RE.match(email))
    email_self = _clamp(float(self_conf.get("email", 0.0) or 0.0))
    if email:
        email_score = _clamp(0.5 * email_self + (0.5 if email_valid else 0.1))
        email_src = "regex" if email_valid else route_src
    else:
        email_score = 0.0
        email_src = route_src
    email_record = {"score": round(email_score, 3), "source": email_src, "validated": email_valid}

    confidences = {
        "name": passthrough("name", name),
        "email": email_record,
        "phone": passthrough("phone", phone),
        "company": passthrough("company", company),
        "designation": passthrough("designation", designation),
        "skills": passthrough("skills", skills),
    }

    return {
        "name": name,
        "email": email,
        "phone": phone,
        "company": company,
        "designation": designation,
        "skills": skills,
        "field_confidence": confidences,
    }
