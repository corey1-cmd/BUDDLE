"""Post bookmark — a user's private "save for later" on a post.

The intro spec lists 저장 (save) as a core feed interaction alongside like /
comment / debate entry. Bookmarks are private to the saving user (no author
notification, no importance signal) — saving is curation, not endorsement, so
it deliberately does NOT feed the mediator/importance loop the way likes do.

Same idempotency pattern as PostLike: the (user_id, post_id) UNIQUE constraint
makes save/unsave a toggle that double-taps can't inflate.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from buddle.db.base import Base


class PostBookmark(Base):
    __tablename__ = "post_bookmarks"
    __table_args__ = (
        # Idempotency: one bookmark per (user, post). A repeated save is a
        # no-op; unsave simply deletes the row.
        UniqueConstraint("user_id", "post_id", name="uq_post_bookmark_user_post"),
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
