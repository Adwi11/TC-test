import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import Base
from app.models import Candidate
from app.workflow.agent import run_request_agent


@pytest.mark.asyncio
async def test_agent_logs_needs_email_when_candidate_has_no_email(tmp_path):
    """The agent must not call SMTP when the candidate has no email."""
    url = f"sqlite+aiosqlite:///{tmp_path/'t.db'}"
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with SessionLocal() as session:
        c = Candidate(name="No Email Person", email=None, phone=None)
        session.add(c)
        await session.commit()
        await session.refresh(c)
        req = await run_request_agent(session, c)
    assert req.status == "needs_email"
    assert req.recipient is None
