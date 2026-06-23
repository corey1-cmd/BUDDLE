"""Post translation — a language-specific rendering of a post.

A post is authored once (content_transformed in post.source_language); each
additional language the persona/mediator produces is stored here so the
mediator can deliver each recipient the version in THEIR language — the same
thought crossing the language barrier. One row per (post, language).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from buddle.db.base import Base


class PostTranslation(Base):
    __tablename__ = "post_translations"
    __table_args__ = (
        UniqueConstraint("post_id", "language", name="uq_post_translation_lang"),
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
    language: Mapped[str] = mapped_column(String(8), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
