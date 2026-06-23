"""Conversation session service — manage a persona's topic threads.

Distinct from session_service.py (which tracks coarse user-activity sessions
for engagement metrics). This manages topic-scoped CONVERSATION threads, like
GPT/Claude chat threads.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from buddle.core.exceptions import NotFound
from buddle.db.models.conversation_session import ConversationSession


async def create_session(
    db: AsyncSession,
    persona_id: uuid.UUID,
    *,
    title: str,
    topic: str | None = None,
) -> ConversationSession:
    sess = ConversationSession(persona_id=persona_id, title=title, topic=topic)
    db.add(sess)
    await db.commit()
    await db.refresh(sess)
    return sess


async def list_sessions(
    db: AsyncSession, persona_id: uuid.UUID, *, limit: int = 50
) -> list[ConversationSession]:
    """A persona's sessions, most recently active first (GPT thread list)."""
    rows = await db.execute(
        select(ConversationSession)
        .where(ConversationSession.persona_id == persona_id)
        .order_by(ConversationSession.last_active_at.desc())
        .limit(max(1, min(limit, 200)))
    )
    return list(rows.scalars())


async def get_session(db: AsyncSession, session_id: uuid.UUID) -> ConversationSession:
    sess = await db.get(ConversationSession, session_id)
    if sess is None:
        raise NotFound("Session not found.")
    return sess


async def delete_session(db: AsyncSession, session_id: uuid.UUID) -> bool:
    result = await db.execute(
        delete(ConversationSession).where(ConversationSession.id == session_id)
    )
    await db.commit()
    return bool(result.rowcount)
