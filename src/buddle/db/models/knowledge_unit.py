"""Knowledge unit — an atomic thought extracted from a post (Layer B).

One post yields 1..5 units (ai/knowledge/extraction). A unit that passes the
selection gate is stored here with its embedding (for novelty/redundancy and
topic-edge proximity) and inherits the source post's visibility so private
thoughts stay within the private boundary. retention_score is frozen at the
moment of storage (the score that earned its place).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import REAL, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from buddle.ai.embeddings.base import EMBED_DIM
from buddle.db.base import Base
from buddle.db.models.enums import PostVisibility


class KnowledgeUnit(Base):
    __tablename__ = "knowledge_units"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    source_post_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    persona_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("personas.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    gist: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False, server_default="ko")
    # Comma-separated topic tags (kept simple; tags come from the mediator).
    topic_tags: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM), nullable=True)
    # Inherited from the source post — gates what may be served/recombined.
    visibility: Mapped[PostVisibility] = mapped_column(
        String(16), nullable=False, server_default=PostVisibility.PUBLIC.value
    )
    # The retention score that earned storage (frozen at insert).
    retention_score: Mapped[float] = mapped_column(REAL, nullable=False, server_default="0")
    # Technician integrity signature (set by the trigger gate).
    integrity_sig: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
