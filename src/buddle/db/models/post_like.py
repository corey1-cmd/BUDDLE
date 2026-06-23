"""Post like — explicit reaction signal for the plaza/feedback loop.

Replaces the previous "distribution count" proxy with a real per-user like.
The (user_id, post_id) UNIQUE constraint guarantees idempotency: a user can
like a post at most once, so a like/unlike toggle and accidental double-taps
never inflate the count (industry-standard pattern). Likes are a positive
endorsement signal the mediator feeds into persona topic affinity.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from buddle.db.base import Base


class PostLike(Base):
    __tablename__ = "post_likes"
    __table_args__ = (
        # Idempotency: one like per (user, post). A repeated like is a no-op;
        # unlike simply deletes the row.
        UniqueConstraint("user_id", "post_id", name="uq_post_like_user_post"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    post_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
