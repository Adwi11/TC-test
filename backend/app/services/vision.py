from __future__ import annotations
import base64
import json
import logging
from dataclasses import dataclass

import httpx
import fitz

from app.config import get_settings
from app.services.llm import _strip_json


log = logging.getLogger(__name__)


@dataclass
class VisionResult:
    """Vision-model extraction result with text + structured guess."""

    text: str
    fields: dict


VISION_SYSTEM = (
    "You read a resume image and extract structured candidate data. "
    "Return ONLY a single JSON object, no prose. "
    "Schema: {name: string|null, email: string|null, phone: string|null, "
    "company: string|null, designation: string|null, skills: string[], "
    "raw_text: string, confidence: {name: number, email: number, phone: number, "
    "company: number, designation: number, skills: number}}."
)


def _pdf_to_png_b64(data: bytes, max_pages: int = 2) -> list[str]:
    """Render the first N PDF pages to base64-encoded PNGs."""
    out: list[str] = []
    with fitz.open(stream=data, filetype="pdf") as doc:
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            pix = page.get_pixmap(dpi=160)
            out.append(base64.b64encode(pix.tobytes("png")).decode("ascii"))
    return out


def _guess_image_mime(data: bytes) -> str:
    """Detect a common image MIME type from raw magic bytes."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:2] == b"BM":
        return "image/bmp"
    return "image/jpeg"


def _raw_images_b64(images: list[bytes], max_images: int = 4) -> list[tuple[str, str]]:
    """Return (mime, base64) pairs for raw image bytes (e.g. from a DOCX)."""
    out: list[tuple[str, str]] = []
    for b in images[:max_images]:
        if not b:
            continue
        out.append((_guess_image_mime(b), base64.b64encode(b).decode("ascii")))
    return out


async def vision_extract(data: bytes) -> VisionResult:
    """Send rasterised PDF pages to the configured vision provider."""
    pngs = _pdf_to_png_b64(data, max_pages=2)
    if not pngs:
        return VisionResult(text="", fields={})
    return await _dispatch_vision([("image/png", b64) for b64 in pngs])


async def vision_extract_from_images(images: list[bytes]) -> VisionResult:
    """Send raw image bytes (e.g. from a DOCX) to the configured vision provider."""
    if not images:
        return VisionResult(text="", fields={})
    parts = _raw_images_b64(images, max_images=4)
    if not parts:
        return VisionResult(text="", fields={})
    return await _dispatch_vision(parts)


async def _dispatch_vision(parts: list[tuple[str, str]]) -> VisionResult:
    """Route a list of (mime, base64) image parts to the chosen provider."""
    s = get_settings()
    provider = (s.vision_provider or "ollama").lower()
    log.info("vision[dispatch] provider=%s n_images=%d", provider, len(parts))
    if provider == "gemini":
        if not s.gemini_api_key:
            log.warning("vision provider=gemini but GEMINI_API_KEY is empty; falling back to ollama")
        else:
            return await _gemini_call(parts)
    return await _ollama_call([b64 for _mime, b64 in parts])


async def _ollama_call(images_b64: list[str]) -> VisionResult:
    """Send base64 PNGs to Ollama Cloud Qwen3-VL via the native /api/chat endpoint."""
    s = get_settings()
    payload = {
        "model": s.vision_model,
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": VISION_SYSTEM},
            {"role": "user", "content": "Extract from this resume image.", "images": images_b64},
        ],
    }
    async with httpx.AsyncClient(
        base_url=s.ollama_base_url.rstrip("/"),
        headers={"Authorization": f"Bearer {s.ollama_api_key}", "Content-Type": "application/json"},
        timeout=httpx.Timeout(180.0, connect=15.0),
    ) as cli:
        r = await cli.post("/api/chat", json=payload)
    if r.status_code >= 400:
        log.warning("ollama vision failed %s: %s", r.status_code, r.text[:300])
        return VisionResult(text="", fields={})
    content = r.json().get("message", {}).get("content", "") or ""
    return _parse_vision_json(content)


async def _gemini_call(images: list[tuple[str, str]]) -> VisionResult:
    """Send (mime, base64) image parts to Google Gemini generateContent for JSON extraction."""
    s = get_settings()
    parts: list[dict] = [{"text": VISION_SYSTEM + "\n\nExtract from these resume images."}]
    for mime, b64 in images:
        parts.append({"inline_data": {"mime_type": mime, "data": b64}})
    body = {
        "contents": [{"parts": parts}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.0},
    }
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{s.gemini_vision_model}:generateContent"
    )
    headers = {"Content-Type": "application/json", "x-goog-api-key": s.gemini_api_key}
    try:
        async with httpx.AsyncClient(timeout=60) as cli:
            r = await cli.post(url, json=body, headers=headers)
    except Exception as e:
        log.warning("gemini vision request failed: %s", type(e).__name__)
        return VisionResult(text="", fields={})
    if r.status_code >= 400:
        log.warning("gemini vision %s: %s", r.status_code, r.text[:300])
        return VisionResult(text="", fields={})
    try:
        data = r.json()
        content = data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        log.warning("gemini vision response shape unexpected: %r", r.text[:300])
        return VisionResult(text="", fields={})
    return _parse_vision_json(content)


def _parse_vision_json(content: str) -> VisionResult:
    """Parse a vision-model JSON reply and wrap it in a VisionResult."""
    try:
        parsed = json.loads(_strip_json(content))
    except Exception as e:
        log.warning("vision json parse failed: %s; raw=%r", e, content[:200])
        return VisionResult(text=content or "", fields={})
    if not isinstance(parsed, dict):
        return VisionResult(text=content or "", fields={})
    return VisionResult(text=parsed.get("raw_text", "") or "", fields=parsed)
