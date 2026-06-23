"""Session service — track contiguous user activity for engagement metrics.

touch_session() is called on authenticated activity. It either bumps the
user's open session (if within the idle window) or opens a new one. The
metrics collector closes stale sessions lazily. This coarse model is enough
for 'average continuous usage time' without per-request overhead.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from buddle.config import get_settings
from buddle.db.models.session import UserSession


async def touch_session(db: AsyncSession, user_id: uuid.UUID) -> UserSession:
    """Record activity for a user, extending or opening a session."""
    timeout = timedelta(minutes=get_settings().session_idle_timeout_min)
    now = datetime.now(UTC)

    open_session = (
        await db.execute(
            select(UserSession)
            .where(UserSession.user_id == user_id, UserSession.ended_at.is_(None))
            .order_by(UserSession.last_seen_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if open_session is not None:
        last_seen = open_session.last_seen_at
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=UTC)
        if now - last_seen <= timeout:
            open_session.last_seen_at = now
            open_session.activity_count += 1
            await db.commit()
            await db.refresh(open_session)
            return open_session
        # Idle gap exceeded -> close the stale session
        open_session.ended_at = last_seen
        await db.flush()

    new_session = UserSession(user_id=user_id, started_at=now, last_seen_at=now, activity_count=1)
    db.add(new_session)
    await db.commit()
    await db.refresh(new_session)
    return new_session


async def close_stale_sessions(db: AsyncSession) -> int:
    """Close any open sessions whose idle gap has elapsed. Returns count closed.

    Run by the metrics collector before computing session-duration stats so
    open-but-idle sessions don't skew the average.
    """
    timeout = timedelta(minutes=get_settings().session_idle_timeout_min)
    cutoff = datetime.now(UTC) - timeout

    result = await db.execute(
        update(UserSession)
        .where(UserSession.ended_at.is_(None), UserSession.last_seen_at < cutoff)
        .values(ended_at=UserSession.last_seen_at)
    )
    await db.commit()
    return int(result.rowcount or 0)
