import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import Base
from app.models import Candidate
from app.services.email_verify import VerifyResult
from app.workflow import agent as agent_mod


@pytest.mark.asyncio
async def test_agent_reextracts_email_when_first_verify_fails(monkeypatch, tmp_path):
    """When verify rejects the first email, the agent should re-extract and re-verify."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'t.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    verify_calls: list[str] = []

    async def fake_verify(email: str) -> VerifyResult:
        """First email fails (no MX), second one is fine."""
        verify_calls.append(email)
        if email == "ghost@nodomain.fake":
            return VerifyResult(deliverable=False, reason="no mx records", mx=False)
        return VerifyResult(deliverable=True, reason="valid", mx=True)

    async def fake_reextract(_text, *, rejected, reason):
        """Pretend the LLM dug a better email out of the source text."""
        return {"email": "real@gmail.com", "confidence": 0.9}

    async def fake_send_email(to, subject, body):
        """Pretend SMTP/Brevo succeeded."""
        return True, None

    async def fake_chat(messages, **kw):
        """Force the agent to call send_email then log_request."""
        if any(m.get("role") == "tool" and m.get("name") == "send_email" for m in messages):
            return {"message": {"tool_calls": [{"function": {"name": "log_request", "arguments": "{\"status\":\"sent\"}"}}]}}
        return {"message": {"tool_calls": [{"function": {"name": "send_email", "arguments": "{\"to\":\"real@gmail.com\",\"subject\":\"s\",\"body\":\"b\"}"}}]}}

    monkeypatch.setattr(agent_mod, "verify_email_http", fake_verify)
    monkeypatch.setattr(agent_mod, "reextract_email", fake_reextract)
    monkeypatch.setattr(agent_mod, "send_email", fake_send_email)
    monkeypatch.setattr(agent_mod, "chat", fake_chat)

    async with SessionLocal() as session:
        c = Candidate(
            name="X", email="ghost@nodomain.fake",
            source_text="some resume text mentioning real@gmail.com",
            field_confidence_json={"email": {"score": 0.6, "source": "llm", "validated": True}},
        )
        session.add(c)
        await session.commit()
        await session.refresh(c)
        req = await agent_mod.run_request_agent(session, c)

    assert verify_calls == ["ghost@nodomain.fake", "real@gmail.com"]
    assert req.status == "sent"
    # candidate row was updated with the re-extracted email
    async with SessionLocal() as session:
        refreshed = await session.get(Candidate, c.id)
        assert refreshed.email == "real@gmail.com"
        assert refreshed.field_confidence_json["email"]["source"] == "reextract"


@pytest.mark.asyncio
async def test_agent_gives_up_after_max_retries(monkeypatch, tmp_path):
    """If every attempt fails verification, agent logs needs_email after the cap."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'t.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def fake_verify(email: str) -> VerifyResult:
        """Always reject."""
        return VerifyResult(deliverable=False, reason="no mx records", mx=False)

    reextract_calls: list[list[str]] = []

    async def fake_reextract(_text, *, rejected, reason):
        """Return a fresh fake address each time."""
        reextract_calls.append(list(rejected))
        return {"email": f"try{len(rejected)}@nope.fake", "confidence": 0.5}

    monkeypatch.setattr(agent_mod, "verify_email_http", fake_verify)
    monkeypatch.setattr(agent_mod, "reextract_email", fake_reextract)

    async with SessionLocal() as session:
        c = Candidate(name="X", email="first@nope.fake", source_text="text")
        session.add(c)
        await session.commit()
        await session.refresh(c)
        req = await agent_mod.run_request_agent(session, c)

    assert req.status == "needs_email"
    # we tried original + 2 retries = 3 verify calls, 2 reextract calls
    assert len(reextract_calls) == agent_mod.EMAIL_REEXTRACT_MAX_TRIES
