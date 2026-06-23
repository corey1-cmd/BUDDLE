"""Relationship routes — /v1/personas/{persona_id}/relationship.

Read-only view of the persona<->user bond, so the chat UI can show the real
Social-Penetration level (and stage label) instead of a demo placeholder.

  GET /v1/personas/{persona_id}/relationship
      → 200 with the current bond; orientation/zero when no turns yet.
      → 404 if the persona isn't owned by the caller.

There is no write endpoint: the bond is shaped only by actual conversation
(via the WS dialogue flow), never set directly — a relationship you can edit
with a slider isn't a relationship.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from buddle.api.deps import DB, CurrentUser
from buddle.schemas.relationship import RelationshipRead
from buddle.services import conversation_service, persona_service

router = APIRouter(prefix="/personas", tags=["relationship"])


@router.get(
    "/{persona_id}/relationship",
    response_model=RelationshipRead,
    summary="페르소나와의 관계 상태 조회",
)
async def read_relationship(persona_id: uuid.UUID, user: CurrentUser, db: DB) -> RelationshipRead:
    # Ownership check (raises PersonaNotFound -> 404 if not the caller's).
    await persona_service.get_persona(db, user, persona_id)

    rel = await conversation_service.find_relationship(db, persona_id=persona_id, user_id=user.id)
    if rel is None:
        # Reading a bond that hasn't formed yet is fine — no side effect, just
        # the neutral starting point.
        return RelationshipRead.neutral()
    return RelationshipRead.from_relationship(rel)
