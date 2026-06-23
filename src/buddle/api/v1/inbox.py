"""Inbox routes — /v1/inbox (private distributions to your personas)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from buddle.api.deps import DB, CurrentUser
from buddle.schemas.inbox import InboxPage
from buddle.services import inbox_service

router = APIRouter(prefix="/inbox", tags=["inbox"])


@router.get(
    "",
    response_model=InboxPage,
    summary="List private deliveries across all your personas",
)
async def list_inbox(
    user: CurrentUser,
    db: DB,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
) -> InboxPage:
    return await inbox_service.list_inbox(db, user, cursor=cursor, limit=limit)


@router.get(
    "/persona/{persona_id}",
    response_model=InboxPage,
    summary="List private deliveries to a specific persona",
)
async def list_inbox_for_persona(
    persona_id: uuid.UUID,
    user: CurrentUser,
    db: DB,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
) -> InboxPage:
    return await inbox_service.list_inbox(
        db, user, persona_id=persona_id, cursor=cursor, limit=limit
    )


@router.post(
    "/{distribution_id}/seen",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Mark a delivered item as seen",
)
async def mark_seen(
    distribution_id: uuid.UUID,
    user: CurrentUser,
    db: DB,
) -> None:
    await inbox_service.mark_seen(db, user, distribution_id)
