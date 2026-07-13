"""Notification service — recipient-scoped activity events (알림).

Creation is *best-effort and side-channel*: a failed notification must never
fail the action that triggered it (like/comment), so creators are invoked
inside the caller's transaction before its commit (one atomic write) and the
helpers here never raise for missing recipients. Self-actions are skipped —
you don't get notified about your own like on your own post.

Read state is a timestamp (read_at NULL = unread): marking read is one UPDATE,
the badge is one filtered COUNT, and "when was it seen" comes for free.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from buddle.db.models.enums import AuthorKind, NotificationKind
from buddle.db.models.notification import Notification
from buddle.db.models.persona import Persona
from buddle.db.models.post import Post

_PREVIEW_LEN = 120


async def post_owner_user_id(db: AsyncSession, post: Post) -> uuid.UUID | None:
    """The human user behind a post, via its source persona (None for AI/agent posts)."""
    if post.source_persona_id is None:
        return None
    persona = await db.get(Persona, post.source_persona_id)
    return persona.user_id if persona else None


def _make(
    *,
    user_id: uuid.UUID,
    kind: NotificationKind,
    actor_kind: AuthorKind,
    actor_label: str | None,
    post_id: uuid.UUID | None,
    preview: str | None,
) -> Notification:
    return Notification(
        user_id=user_id,
        kind=kind,
        actor_kind=actor_kind,
        actor_label=actor_label,
        post_id=post_id,
        preview=preview[:_PREVIEW_LEN] if preview else None,
    )


async def notify_post_event(
    db: AsyncSession,
    post: Post,
    *,
    kind: NotificationKind,
    actor_kind: AuthorKind,
    actor_label: str | None,
    actor_user_id: uuid.UUID | None,
    preview: str | None = None,
) -> Notification | None:
    """Queue a notification to the post's owner (no commit — caller's tx).

    Returns None (skips) when the post has no human owner or the actor is the
    owner (self-action). The row is only add()ed; the caller's commit makes it
    atomic with the action itself.
    """
    recipient = await post_owner_user_id(db, post)
    if recipient is None or recipient == actor_user_id:
        return None
    row = _make(
        user_id=recipient,
        kind=kind,
        actor_kind=actor_kind,
        actor_label=actor_label,
        post_id=post.id,
        preview=preview,
    )
    db.add(row)
    return row


async def list_notifications(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    limit: int = 30,
    unread_only: bool = False,
) -> list[Notification]:
    limit = max(1, min(limit, 100))
    stmt = select(Notification).where(Notification.user_id == user_id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    stmt = stmt.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit)
    return list((await db.execute(stmt)).scalars())


async def unread_count(db: AsyncSession, user_id: uuid.UUID) -> int:
    return int(
        await db.scalar(
            select(func.count(Notification.id)).where(
                Notification.user_id == user_id, Notification.read_at.is_(None)
            )
        )
        or 0
    )


async def mark_read(db: AsyncSession, user_id: uuid.UUID, notification_id: uuid.UUID) -> bool:
    """Mark one of *my* notifications read. Returns False if not mine/unknown."""
    result = await db.execute(
        update(Notification)
        .where(
            Notification.id == notification_id,
            Notification.user_id == user_id,  # scoping: can't read others' rows
            Notification.read_at.is_(None),
        )
        .values(read_at=datetime.now(UTC))
    )
    await db.commit()
    return bool(result.rowcount)


async def mark_all_read(db: AsyncSession, user_id: uuid.UUID) -> int:
    """Mark all my unread notifications read. Returns how many changed."""
    result = await db.execute(
        update(Notification)
        .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    await db.commit()
    return int(result.rowcount or 0)
