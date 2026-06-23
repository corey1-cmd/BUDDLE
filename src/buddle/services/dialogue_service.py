"""Dialogue service — persistence and history loading for persona conversations.

History and message persistence are SESSION-scoped: each topic session has its
own isolated context window (like a GPT/Claude thread). The session's
last_active_at is bumped on each new message so threads sort most-recent-first.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from buddle.ai.interfaces import DialogueTurn
from buddle.db.models.conversation_session import ConversationSession
from buddle.db.models.enums import MessageRole
from buddle.db.models.message import Message


async def load_recent_history(
    db: AsyncSession,
    persona_id: uuid.UUID,
    *,
    session_id: uuid.UUID | None = None,
    limit: int = 40,
) -> list[DialogueTurn]:
    """Most recent `limit` messages, oldest first.

    Scoped to a session when session_id is given (each topic has its own
    memory); falls back to the persona-wide stream otherwise (backward compat).
    """
    q = select(Message)
    if session_id is not None:
        q = q.where(Message.session_id == session_id)
    else:
        q = q.where(Message.persona_id == persona_id)
    result = await db.execute(q.order_by(Message.created_at.desc()).limit(limit))
    rows = list(result.scalars().all())
    rows.reverse()
    return [DialogueTurn(role=r.role.value, content=r.content) for r in rows]


async def _touch_session(db: AsyncSession, session_id: uuid.UUID | None) -> None:
    if session_id is None:
        return
    sess = await db.get(ConversationSession, session_id)
    if sess is not None:
        sess.last_active_at = datetime.now(UTC)


async def record_user_message(
    db: AsyncSession,
    persona_id: uuid.UUID,
    content: str,
    *,
    session_id: uuid.UUID | None = None,
) -> Message:
    msg = Message(
        persona_id=persona_id,
        session_id=session_id,
        role=MessageRole.USER,
        content=content,
    )
    db.add(msg)
    await _touch_session(db, session_id)
    await db.commit()
    await db.refresh(msg)
    return msg


async def record_persona_message(
    db: AsyncSession,
    persona_id: uuid.UUID,
    content: str,
    *,
    session_id: uuid.UUID | None = None,
) -> Message:
    msg = Message(
        persona_id=persona_id,
        session_id=session_id,
        role=MessageRole.PERSONA,
        content=content,
    )
    db.add(msg)
    await _touch_session(db, session_id)
    await db.commit()
    await db.refresh(msg)
    return msg
