from __future__ import annotations
from dataclasses import dataclass
import re
import io

try:
    import pytesseract
    from pdf2image import convert_from_bytes
    OCR_AVAILABLE = True
except Exception:
    OCR_AVAILABLE = False


@dataclass
class OcrResult:
    """OCR extraction result with a junk-score signal."""

    text: str
    junk: bool


_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_DIGIT_RUN = re.compile(r"\d{10,}")


def ocr_pdf(data: bytes) -> OcrResult:
    """Rasterise the PDF and OCR each page via Tesseract."""
    if not OCR_AVAILABLE:
        return OcrResult(text="", junk=True)
    try:
        images = convert_from_bytes(data, dpi=200)
    except Exception:
        return OcrResult(text="", junk=True)
    chunks: list[str] = []
    for img in images:
        try:
            chunks.append(pytesseract.image_to_string(img))
        except Exception:
            continue
    text = "\n".join(chunks)
    alpha_count = sum(1 for c in text if c.isalpha())
    alpha_ratio = (alpha_count / max(len(text), 1)) if text else 0.0
    junk = (alpha_ratio < 0.4) or (not _EMAIL_RE.search(text) and not _DIGIT_RUN.search(text))
    return OcrResult(text=text, junk=junk)
