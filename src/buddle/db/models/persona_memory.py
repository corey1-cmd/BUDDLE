"""PersonaMemory model — persona long-term memory (LTM).

Persists the EKB Retention stage (Engel·Kollat·Blackwell information
processing) so the EKB Search stage of later turns can consult it. Two-store
framing per Atkinson & Shiffrin (1968): the dialogue prompt window is STM;
this table is LTM.

Field semantics (each maps to one term of the retrieval score, see
``buddle.ai.memory.scoring``):

  * importance — memorability estimate at extraction time [0, 1].
  * strength   — retrieval count proxy; each recall (and each deduplicated
                 re-disclosure) increments it. Approximates ACT-R base-level
                 activation (Anderson & Schooler 1991): well-used memories
                 decay more slowly.
  * last_accessed_at — anchor of the Ebbinghaus recency decay; updated on
                 every recall, so "still being used" equals "still fresh".
  * emb        — BGE-M3 embedding (nullable: embedding-provider failure must
                 not block remembering; such rows fall back to recency-only
                 retrieval, the same graceful degradation the mediator uses).

Data sovereignty: CASCADE on persona delete — a removed persona forgets
everything, immediately, by construction.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import REAL, DateTime, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from buddle.ai.embeddings.base import EMBED_DIM
from buddle.db.base import Base
from buddle.db.models.enums import MemoryKind


class PersonaMemory(Base):
    __tablename__ = "persona_memories"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    persona_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("personas.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[MemoryKind] = mapped_column(
        PGEnum(
            MemoryKind,
            name="memory_kind",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    emb: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM), nullable=True)
    importance: Mapped[float] = mapped_column(REAL, nullable=False, server_default=text("0.5"))
    strength: Mapped[float] = mapped_column(REAL, nullable=False, server_default=text("1.0"))
    source_session_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("conversation_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_accessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
