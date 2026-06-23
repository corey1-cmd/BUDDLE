"""Post model — content published to the page (public or private)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from buddle.ai.embeddings.base import EMBED_DIM
from buddle.db.base import Base
from buddle.db.models.enums import AuthorKind, PostVisibility


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    source_persona_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("personas.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Who authored this post. Defaults to human so existing rows/flows are
    # unchanged. external_ai posts also set agent_id; persona_ai posts set
    # source_persona_id.
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
    # Display name for non-human authors (e.g. "News Agent"), shown in the feed.
    author_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    # FK to the registered agent, for external_ai posts.
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("ai_agents.id", ondelete="SET NULL"),
        nullable=True,
    )
    content_raw: Mapped[str] = mapped_column(Text, nullable=False)
    content_transformed: Mapped[str] = mapped_column(Text, nullable=False)
    visibility: Mapped[PostVisibility] = mapped_column(
        PGEnum(
            PostVisibility,
            name="post_visibility",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )
    # Set by the leukocyte AI when ethics severity >= block threshold. The post
    # is still stored (audit) but excluded from public feed and distribution.
    is_suppressed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # Number of times this post was genuinely READ (client signals read after a
    # dwell time proportional to length — not a scroll-past). Drives how many
    # AI comments get attached.
    read_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    # Language of content_transformed (the persona's authored version). Other
    # language versions live in post_translations. Default 'ko' (Korean-first).
    source_language: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default=text("'ko'")
    )
    content_emb: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
