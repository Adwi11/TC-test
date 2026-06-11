from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict


class CandidateSummary(BaseModel):
    """Lightweight candidate row used in list endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: Optional[str] = None
    email: Optional[str] = None
    company: Optional[str] = None
    extraction_route: Optional[str] = None
    created_at: datetime


class CandidateDetail(BaseModel):
    """Full candidate detail including per-field confidence."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    designation: Optional[str] = None
    skills_json: Optional[list[Any]] = None
    field_confidence_json: Optional[dict[str, Any]] = None
    extraction_route: Optional[str] = None
    created_at: datetime


class DocumentRequestOut(BaseModel):
    """A persisted outbound document request."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    candidate_id: int
    channel: str
    recipient: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    status: str
    error: Optional[str] = None
    sent_at: datetime


class SubmittedDocumentOut(BaseModel):
    """Metadata for a submitted PAN/Aadhaar document."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    candidate_id: int
    kind: str
    mime_type: str
    last4: Optional[str] = None
    uploaded_at: datetime


class ErrorOut(BaseModel):
    """Standard error response shape."""

    error: str
    code: str
