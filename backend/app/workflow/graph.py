from __future__ import annotations
import logging
from typing import TypedDict, Literal

from langgraph.graph import StateGraph, END

from app.services.extraction import (
    extract_pdf, extract_docx, route_decision, ExtractionStats,
)
from app.services.ocr import ocr_pdf
from app.services.vision import vision_extract, vision_extract_from_images
from app.services.llm import extract_fields
from app.services.confidence import score_fields


log = logging.getLogger(__name__)


class IngestionState(TypedDict, total=False):
    """State threaded through the LangGraph ingestion workflow."""

    file_bytes: bytes
    filename: str
    mime: str
    kind: Literal["pdf", "docx"]
    route: Literal["text", "ocr", "vision"]
    stats: ExtractionStats
    text: str
    raw_fields: dict
    scored: dict


async def n_detect(state: IngestionState) -> IngestionState:
    """Route the file through PyMuPDF or python-docx and pick the extraction lane."""
    mime = state.get("mime", "")
    filename = state.get("filename", "").lower()
    data = state["file_bytes"]
    if "pdf" in mime or filename.endswith(".pdf"):
        kind = "pdf"
        stats = extract_pdf(data)
    elif "word" in mime or filename.endswith(".docx"):
        kind = "docx"
        stats = extract_docx(data)
    else:
        raise ValueError("UNSUPPORTED_TYPE")
    if kind == "docx":
        sparse_text = stats.chars_per_page < 80
        has_images = bool(stats.docx_images)
        route = "vision" if (sparse_text and has_images) else "text"
    else:
        route = route_decision(stats)
    log.info(
        "graph[detect] filename=%s kind=%s pages=%d chars_per_page=%.0f image_area_ratio=%.2f → route=%s",
        state.get("filename"), kind, stats.pages, stats.chars_per_page, stats.image_area_ratio, route,
    )
    return {**state, "kind": kind, "stats": stats, "route": route, "text": stats.text}


async def n_ocr(state: IngestionState) -> IngestionState:
    """Fallback: run Tesseract OCR on the PDF and escalate to vision if junk."""
    if state.get("route") != "ocr":
        log.info("graph[ocr] skipped (route=%s)", state.get("route"))
        return state
    if state.get("kind") != "pdf":
        log.info("graph[ocr] skipped (kind=%s not pdf)", state.get("kind"))
        return state
    result = ocr_pdf(state["file_bytes"])
    log.info("graph[ocr] text_chars=%d junk=%s", len(result.text), result.junk)
    if result.junk:
        log.info("graph[ocr] escalating to vision")
        return {**state, "route": "vision", "text": result.text}
    return {**state, "text": result.text}


async def n_vision(state: IngestionState) -> IngestionState:
    """Fallback: send rasterised PDF pages or embedded DOCX images to the vision model."""
    if state.get("route") != "vision":
        log.info("graph[vision] skipped (route=%s)", state.get("route"))
        return state
    kind = state.get("kind")
    if kind == "pdf":
        vr = await vision_extract(state["file_bytes"])
    elif kind == "docx":
        images = state.get("stats").docx_images if state.get("stats") else []
        if not images:
            log.info("graph[vision] docx had no embedded images; skipping")
            return state
        log.info("graph[vision] docx image_count=%d", len(images))
        vr = await vision_extract_from_images(images)
    else:
        log.info("graph[vision] skipped (kind=%s)", kind)
        return state
    log.info("graph[vision] text_chars=%d fields_keys=%s", len(vr.text or ""), list((vr.fields or {}).keys()))
    text = vr.text or state.get("text", "")
    raw = vr.fields or {}
    return {**state, "text": text, "raw_fields": raw}


async def n_llm(state: IngestionState) -> IngestionState:
    """Run the text LLM extractor unless the vision step already produced fields."""
    if state.get("raw_fields"):
        log.info("graph[llm] skipped (vision already produced fields)")
        return state
    text = state.get("text") or ""
    if not text.strip():
        log.info("graph[llm] skipped (no text)")
        return {**state, "raw_fields": {}}
    raw = await extract_fields(text)
    log.info(
        "graph[llm] extracted name=%r email=%r phone=%r company=%r skills_n=%d",
        raw.get("name"), raw.get("email"), raw.get("phone"), raw.get("company"), len(raw.get("skills") or []),
    )
    return {**state, "raw_fields": raw}


async def n_score(state: IngestionState) -> IngestionState:
    """Validate fields and compute per-field confidence."""
    scored = score_fields(state.get("raw_fields") or {}, route=state.get("route", "text"))
    fc = scored.get("field_confidence", {})
    summary = {k: f"{v.get('score', 0):.2f}/{v.get('source', '?')}" for k, v in fc.items()}
    log.info("graph[score] %s", summary)
    return {**state, "scored": scored}


def build_graph():
    """Compile and return the LangGraph ingestion workflow."""
    g = StateGraph(IngestionState)
    g.add_node("detect", n_detect)
    g.add_node("ocr", n_ocr)
    g.add_node("vision", n_vision)
    g.add_node("llm", n_llm)
    g.add_node("score", n_score)
    g.set_entry_point("detect")
    g.add_edge("detect", "ocr")
    g.add_edge("ocr", "vision")
    g.add_edge("vision", "llm")
    g.add_edge("llm", "score")
    g.add_edge("score", END)
    return g.compile()


_graph = None


async def run_ingestion(*, file_bytes: bytes, filename: str, mime: str) -> dict:
    """Run the full ingestion workflow and return scored fields + metadata."""
    global _graph
    if _graph is None:
        _graph = build_graph()
    state: IngestionState = {"file_bytes": file_bytes, "filename": filename, "mime": mime}
    final = await _graph.ainvoke(state)
    return {
        "route": final.get("route", "text"),
        "text": final.get("text", ""),
        "scored": final.get("scored", {}),
    }
