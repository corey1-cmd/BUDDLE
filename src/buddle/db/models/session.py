"""User session tracking — powers 'average continuous usage time' and
stickiness metrics for the central manager's human-facing dashboard.

A session is a contiguous span of user activity. We track it coarsely:
started_at on first activity, last_seen_at bumped on each activity, ended_at
when an idle gap exceeds the session timeout (closed lazily by the metrics
collector). duration = (ended_at or last_seen_at) - started_at.

Identity rules (documented to avoid metric drift): unit = user; a session is
attributed to user_id; activity = any authenticated request the app records
via touch_session(). Idle timeout is configurable (session_idle_timeout_min).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from buddle.db.base import Base


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Set when the session is closed (idle gap exceeded). NULL = open.
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Number of recorded activities in this session (engagement depth proxy).
    activity_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
