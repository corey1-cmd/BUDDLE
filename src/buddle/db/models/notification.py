"""Notification — an activity event delivered to a user (SNS 알림).

Row-per-event, recipient-scoped. The actor is stored as a display label plus
the AuthorKind taxonomy (human / persona_ai / external_ai / bot) rather than a
hard FK, so a notification survives the actor's deletion and AI actors fit the
same shape as humans. ``read_at`` doubles as the unread flag (NULL = unread),
so "mark read" is a single timestamp write and unread-count is one filtered
COUNT — no separate boolean to keep in sync.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, func, text
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from buddle.db.base import Base
from buddle.db.models.enums import AuthorKind, NotificationKind


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    # Who receives this notification (always a human user).
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[NotificationKind] = mapped_column(
        PGEnum(
            NotificationKind,
            name="notification_kind",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )
    # Who triggered it — display label + author taxonomy, no hard FK (survives
    # actor deletion; AI actors fit the same shape).
    actor_kind: Mapped[AuthorKind] = mapped_column(
        PGEnum(
            AuthorKind,
            name="author_kind",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        server_default=AuthorKind.HUMAN.value,
    )
    actor_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The post the event happened on. CASCADE: notifications about a deleted
    # post are noise, drop them with it.
    post_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    # Short preview text (e.g. comment excerpt) so the notification list
    # renders without joining back to the source row.
    preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    # NULL = unread. Set once on first read; also the "when" for the UI.
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
