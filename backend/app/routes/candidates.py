from __future__ import annotations
import io
import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.models import Candidate, DocumentRequest, SubmittedDocument
from app.schemas import (
    CandidateSummary, CandidateDetail, DocumentRequestOut, SubmittedDocumentOut, ErrorOut,
)
from app.workflow.graph import run_ingestion


log = logging.getLogger(__name__)
router = APIRouter(prefix="/candidates", tags=["candidates"])


def _err(code: str, message: str, http: int) -> JSONResponse:
    """Return a standard error response."""
    return JSONResponse(status_code=http, content={"error": message, "code": code})


_ALLOWED_RESUME_MIME = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@router.get("", response_model=list[CandidateSummary])
async def list_candidates(session: AsyncSession = Depends(get_session)):
    """Return all candidates in descending creation order."""
    result = await session.execute(select(Candidate).order_by(desc(Candidate.created_at)))
    rows = result.scalars().all()
    return [CandidateSummary.model_validate(r) for r in rows]


@router.get("/{candidate_id}", response_model=CandidateDetail)
async def get_candidate(candidate_id: int, session: AsyncSession = Depends(get_session)):
    """Return a single candidate with extracted fields and confidence."""
    c = await session.get(Candidate, candidate_id)
    if not c:
        raise HTTPException(status_code=404, detail="not_found")
    return CandidateDetail.model_validate(c)


@router.post("/upload", response_model=CandidateDetail)
async def upload_candidate(file: UploadFile = File(...), session: AsyncSession = Depends(get_session)):
    """Run the ingestion workflow on an uploaded resume and persist a new candidate."""
    s = get_settings()
    if file.content_type not in _ALLOWED_RESUME_MIME and not (file.filename or "").lower().endswith((".pdf", ".docx")):
        return _err("UNSUPPORTED_TYPE", "only pdf or docx accepted", 415)
    data = await file.read()
    if not data:
        return _err("BAD_FILE", "empty upload", 400)
    if len(data) > s.max_upload_mb * 1024 * 1024:
        return _err("OVERSIZE", f"max {s.max_upload_mb} mb", 413)

    try:
        result = await run_ingestion(file_bytes=data, filename=file.filename or "resume", mime=file.content_type or "")
    except ValueError as e:
        if str(e) == "UNSUPPORTED_TYPE":
            return _err("UNSUPPORTED_TYPE", "unsupported file type", 415)
        return _err("BAD_FILE", "could not parse file", 400)
    except Exception as e:
        log.exception("ingestion failure")
        return _err("INGESTION_FAILED", f"{type(e).__name__}", 500)

    scored = result.get("scored") or {}
    candidate = Candidate(
        name=scored.get("name"),
        email=scored.get("email"),
        phone=scored.get("phone"),
        company=scored.get("company"),
        designation=scored.get("designation"),
        skills_json=scored.get("skills") or [],
        field_confidence_json=scored.get("field_confidence") or {},
        extraction_route=result.get("route"),
        source_text=(result.get("text") or "")[:50000],
    )
    session.add(candidate)
    await session.commit()
    await session.refresh(candidate)

    from app.workflow.agent import should_auto_request, run_request_agent, CooldownError
    ok, reason = should_auto_request(candidate)
    log.info("auto_request candidate_id=%s eligible=%s reason=%s", candidate.id, ok, reason)
    if ok:
        try:
            await run_request_agent(session, candidate)
        except CooldownError:
            pass
        except Exception as e:
            log.warning("auto_request agent failure: %s", e)

    return CandidateDetail.model_validate(candidate)


@router.get("/{candidate_id}/requests", response_model=list[DocumentRequestOut])
async def list_requests(candidate_id: int, session: AsyncSession = Depends(get_session)):
    """Return the request history for a candidate."""
    result = await session.execute(
        select(DocumentRequest).where(DocumentRequest.candidate_id == candidate_id).order_by(desc(DocumentRequest.sent_at))
    )
    return [DocumentRequestOut.model_validate(r) for r in result.scalars().all()]


@router.post("/{candidate_id}/request-documents", response_model=DocumentRequestOut)
async def request_documents(candidate_id: int, session: AsyncSession = Depends(get_session)):
    """Invoke the document-request agent and persist the resulting request."""
    from app.workflow.agent import run_request_agent, CooldownError
    c = await session.get(Candidate, candidate_id)
    if not c:
        raise HTTPException(status_code=404, detail="not_found")
    try:
        req = await run_request_agent(session, c)
    except CooldownError:
        return _err("COOLDOWN", "another request was sent recently; try again shortly", 429)
    except Exception as e:
        log.exception("agent failure")
        return _err("AGENT_FAILED", f"{type(e).__name__}", 500)
    return DocumentRequestOut.model_validate(req)


@router.get("/{candidate_id}/documents", response_model=list[SubmittedDocumentOut])
async def list_documents(candidate_id: int, session: AsyncSession = Depends(get_session)):
    """Return metadata for all submitted documents (no blobs)."""
    result = await session.execute(
        select(SubmittedDocument).where(SubmittedDocument.candidate_id == candidate_id).order_by(SubmittedDocument.uploaded_at)
    )
    return [SubmittedDocumentOut.model_validate(r) for r in result.scalars().all()]


@router.get("/{candidate_id}/documents/{doc_id}/file")
async def stream_document(candidate_id: int, doc_id: int, session: AsyncSession = Depends(get_session)):
    """Stream a single document blob inline."""
    doc = await session.get(SubmittedDocument, doc_id)
    if not doc or doc.candidate_id != candidate_id:
        raise HTTPException(status_code=404, detail="not_found")
    return Response(content=doc.blob, media_type=doc.mime_type,
                    headers={"Content-Disposition": f'inline; filename="{doc.kind}-{doc.id}"'})


_ALLOWED_DOC_MIME = {"image/jpeg", "image/png", "application/pdf"}


@router.post("/{candidate_id}/submit-documents", response_model=list[SubmittedDocumentOut])
async def submit_documents(
    candidate_id: int,
    pan: UploadFile | None = File(default=None),
    aadhaar: UploadFile | None = File(default=None),
    session: AsyncSession = Depends(get_session),
):
    """Persist PAN and/or Aadhaar uploads as DB blobs."""
    s = get_settings()
    c = await session.get(Candidate, candidate_id)
    if not c:
        raise HTTPException(status_code=404, detail="not_found")
    if not pan and not aadhaar:
        return _err("BAD_FILE", "no files provided", 400)

    saved: list[SubmittedDocument] = []
    for kind, f in (("pan", pan), ("aadhaar", aadhaar)):
        if f is None:
            continue
        if f.content_type not in _ALLOWED_DOC_MIME:
            return _err("UNSUPPORTED_TYPE", f"{kind}: unsupported mime", 415)
        data = await f.read()
        if not data:
            return _err("BAD_FILE", f"{kind}: empty file", 400)
        if len(data) > s.max_upload_mb * 1024 * 1024:
            return _err("OVERSIZE", f"{kind}: exceeds {s.max_upload_mb} mb", 413)
        doc = SubmittedDocument(candidate_id=candidate_id, kind=kind, mime_type=f.content_type, blob=data, last4=None)
        session.add(doc)
        saved.append(doc)
    await session.commit()
    for d in saved:
        await session.refresh(d)
    return [SubmittedDocumentOut.model_validate(d) for d in saved]
