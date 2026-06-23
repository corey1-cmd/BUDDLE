"""Post context-note routes — /v1/posts/{post_id}/context-notes.

Read the supporting context/evidence/clarification notes an argument-AI chat
saved onto a post; shown in the feed detail as "이 글의 부가 맥락".
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from buddle.api.deps import DB, CurrentUser
from buddle.services import argument_chat_service

router = APIRouter(prefix="/posts", tags=["context-notes"])


class ContextNoteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    content: str
    created_at: datetime


@router.get(
    "/{post_id}/context-notes",
    response_model=list[ContextNoteRead],
    summary="글의 부가 맥락 노트 조회",
)
async def read_context_notes(
    post_id: uuid.UUID, user: CurrentUser, db: DB
) -> list[ContextNoteRead]:
    notes = await argument_chat_service.list_context_notes(db, post_id=post_id)
    return [ContextNoteRead.model_validate(n) for n in notes]
