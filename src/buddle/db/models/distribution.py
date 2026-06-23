"""Distribution events — private posts routed by mediator to target personas."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import REAL, DateTime, ForeignKey, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from buddle.db.base import Base


class Distribution(Base):
    __tablename__ = "distributions"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    source_post_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_persona_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("personas.id", ondelete="CASCADE"),
        nullable=False,
    )
    relevance_score: Mapped[float] = mapped_column(REAL, nullable=False)
    delivered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
