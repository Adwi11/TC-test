from datetime import datetime
from sqlalchemy import String, Integer, ForeignKey, DateTime, LargeBinary, JSON, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Candidate(Base):
    """A candidate parsed from an uploaded resume."""

    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str | None] = mapped_column(String(256))
    email: Mapped[str | None] = mapped_column(String(256))
    phone: Mapped[str | None] = mapped_column(String(64))
    company: Mapped[str | None] = mapped_column(String(256))
    designation: Mapped[str | None] = mapped_column(String(256))
    skills_json: Mapped[list | None] = mapped_column(JSON)
    field_confidence_json: Mapped[dict | None] = mapped_column(JSON)
    extraction_route: Mapped[str | None] = mapped_column(String(16))
    source_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    requests: Mapped[list["DocumentRequest"]] = relationship(back_populates="candidate", cascade="all, delete-orphan")
    documents: Mapped[list["SubmittedDocument"]] = relationship(back_populates="candidate", cascade="all, delete-orphan")


class DocumentRequest(Base):
    """A logged outbound document-request message."""

    __tablename__ = "document_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    channel: Mapped[str] = mapped_column(String(16), default="email")
    recipient: Mapped[str | None] = mapped_column(String(256))
    subject: Mapped[str | None] = mapped_column(String(512))
    body: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32))
    error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    candidate: Mapped["Candidate"] = relationship(back_populates="requests")


class SubmittedDocument(Base):
    """A PAN or Aadhaar document uploaded by HR for a candidate."""

    __tablename__ = "submitted_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))
    mime_type: Mapped[str] = mapped_column(String(64))
    blob: Mapped[bytes] = mapped_column(LargeBinary)
    last4: Mapped[str | None] = mapped_column(String(4))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    candidate: Mapped["Candidate"] = relationship(back_populates="documents")
