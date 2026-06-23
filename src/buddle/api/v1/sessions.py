"""Conversation session routes — /v1/personas/{persona_id}/sessions.

Topic-scoped conversation threads under a persona (GPT/Claude-style). Owner
only. Listing returns most-recently-active first; each session has its own
isolated message history.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, ConfigDict, Field

from buddle.api.deps import DB, CurrentUser
from buddle.core.exceptions import NotFound
from buddle.db.models.persona import Persona
from buddle.services import conversation_session_service, dialogue_service

router = APIRouter(prefix="/personas/{persona_id}/sessions", tags=["sessions"])


class SessionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    topic: str | None = Field(default=None, max_length=64)


class SessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    persona_id: uuid.UUID
    title: str
    topic: str | None
    created_at: datetime
    last_active_at: datetime


class SessionMessage(BaseModel):
    role: str
    content: str


async def _owned_persona(db: DB, user_id: uuid.UUID, persona_id: uuid.UUID) -> Persona:
    p = await db.get(Persona, persona_id)
    if p is None or p.user_id != user_id:
        raise NotFound("Persona not found.")
    return p


async def _owned_session(
    db: DB, user_id: uuid.UUID, persona_id: uuid.UUID, session_id: uuid.UUID
) -> None:
    await _owned_persona(db, user_id, persona_id)
    sess = await conversation_session_service.get_session(db, session_id)
    if sess.persona_id != persona_id:
        raise NotFound("Session not found.")


@router.post("", response_model=SessionRead, status_code=status.HTTP_201_CREATED)
async def create_session(
    persona_id: uuid.UUID,
    payload: SessionCreate,
    user: CurrentUser,
    db: DB,
) -> object:
    await _owned_persona(db, user.id, persona_id)
    return await conversation_session_service.create_session(
        db, persona_id, title=payload.title, topic=payload.topic
    )


@router.get("", response_model=list[SessionRead])
async def list_sessions(
    persona_id: uuid.UUID,
    user: CurrentUser,
    db: DB,
    limit: int = Query(default=50, ge=1, le=200),
) -> Sequence[object]:
    await _owned_persona(db, user.id, persona_id)
    return await conversation_session_service.list_sessions(db, persona_id, limit=limit)


@router.get("/{session_id}/messages", response_model=list[SessionMessage])
async def session_messages(
    persona_id: uuid.UUID,
    session_id: uuid.UUID,
    user: CurrentUser,
    db: DB,
    limit: int = Query(default=40, ge=1, le=200),
) -> list[SessionMessage]:
    await _owned_session(db, user.id, persona_id, session_id)
    turns = await dialogue_service.load_recent_history(
        db, persona_id, session_id=session_id, limit=limit
    )
    return [SessionMessage(role=t.role, content=t.content) for t in turns]


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    persona_id: uuid.UUID,
    session_id: uuid.UUID,
    user: CurrentUser,
    db: DB,
) -> None:
    await _owned_session(db, user.id, persona_id, session_id)
    await conversation_session_service.delete_session(db, session_id)
