from __future__ import annotations
import base64
import io
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


def _raw_images_to_b64(images: list[bytes], max_images: int = 4) -> list[str]:
    """Base64-encode raw image bytes (already PNG/JPG/etc) for the vision model."""
    return [base64.b64encode(b).decode("ascii") for b in images[:max_images] if b]


async def vision_extract(data: bytes) -> VisionResult:
    """Send rasterised pages to Ollama Cloud Qwen3-VL and parse the JSON reply."""
    return await _vision_call(_pdf_to_png_b64(data, max_pages=2))


async def vision_extract_from_images(images: list[bytes]) -> VisionResult:
    """Send raw image bytes (e.g. from a DOCX) to Qwen3-VL and parse the JSON reply."""
    return await _vision_call(_raw_images_to_b64(images, max_images=4))


async def _vision_call(images: list[str]) -> VisionResult:
    """Shared base64-PNG → Qwen3-VL chat call."""
    s = get_settings()
    if not images:
        return VisionResult(text="", fields={})
    payload = {
        "model": s.vision_model,
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": VISION_SYSTEM},
            {"role": "user", "content": "Extract from this resume image.", "images": images},
        ],
    }
    async with httpx.AsyncClient(
        base_url=s.ollama_base_url.rstrip("/"),
        headers={"Authorization": f"Bearer {s.ollama_api_key}", "Content-Type": "application/json"},
        timeout=httpx.Timeout(180.0, connect=15.0),
    ) as cli:
        r = await cli.post("/api/chat", json=payload)
    if r.status_code >= 400:
        log.warning("vision call failed %s: %s", r.status_code, r.text[:300])
        return VisionResult(text="", fields={})
    content = r.json().get("message", {}).get("content", "") or ""
    try:
        parsed = json.loads(_strip_json(content))
    except Exception as e:
        log.warning("vision json parse failed: %s", e)
        return VisionResult(text=content, fields={})
    return VisionResult(text=parsed.get("raw_text", "") or "", fields=parsed)
