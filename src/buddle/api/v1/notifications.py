"""Notification routes — /v1/notifications (my activity feed).

All routes are scoped to the authenticated user: you can only list, count,
and mark-read your own notifications (the service filters on user_id, so a
guessed foreign id is a no-op rather than a leak).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from buddle.api.deps import DB, CurrentUser
from buddle.schemas.notification import NotificationRead, ReadReceipt, UnreadCount
from buddle.services import notification_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get(
    "",
    response_model=list[NotificationRead],
    summary="My notifications, newest first",
)
async def list_my_notifications(
    user: CurrentUser,
    db: DB,
    limit: int = Query(default=30, ge=1, le=100),
    unread_only: bool = Query(default=False),
) -> list[NotificationRead]:
    rows = await notification_service.list_notifications(
        db, user.id, limit=limit, unread_only=unread_only
    )
    return [NotificationRead.model_validate(r) for r in rows]


@router.get(
    "/unread-count",
    response_model=UnreadCount,
    summary="Number of unread notifications (badge)",
)
async def get_unread_count(user: CurrentUser, db: DB) -> UnreadCount:
    return UnreadCount(count=await notification_service.unread_count(db, user.id))


@router.post(
    "/{notification_id}/read",
    response_model=ReadReceipt,
    summary="Mark one notification read (idempotent)",
)
async def mark_one_read(
    notification_id: uuid.UUID,
    user: CurrentUser,
    db: DB,
) -> ReadReceipt:
    changed = await notification_service.mark_read(db, user.id, notification_id)
    return ReadReceipt(updated=1 if changed else 0)


@router.post(
    "/read-all",
    response_model=ReadReceipt,
    summary="Mark all my notifications read",
)
async def mark_all_read(user: CurrentUser, db: DB) -> ReadReceipt:
    return ReadReceipt(updated=await notification_service.mark_all_read(db, user.id))
