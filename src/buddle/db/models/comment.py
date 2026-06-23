"""Comment model — replies to public-plaza posts.

A comment has a CommentKind (inform / empathize / question) per the spec, and
the same author-kind taxonomy as posts (human / persona_ai / external_ai /
bot). Comments go through the same ethics gate as posts before being stored.

Threading is single-level for now (comments attach to a post); a parent_id is
included so nested replies can be added later without a migration.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Text, func, text
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from buddle.db.base import Base
from buddle.db.models.enums import AuthorKind, CommentKind


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    post_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Optional parent for future nested threads (single-level for now).
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("comments.id", ondelete="CASCADE"),
        nullable=True,
    )
    kind: Mapped[CommentKind] = mapped_column(
        PGEnum(
            CommentKind,
            name="comment_kind",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )
    author_kind: Mapped[AuthorKind] = mapped_column(
        PGEnum(
            AuthorKind,
            name="author_kind",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        server_default=AuthorKind.HUMAN.value,
    )
    author_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Author references (any may be null depending on author_kind).
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    source_persona_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("personas.id", ondelete="SET NULL"),
        nullable=True,
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ai_agents.id", ondelete="SET NULL"), nullable=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_suppressed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
