"""Importance scoring — additive contributions + tanh-normalized final score."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import REAL, DateTime, ForeignKey, String, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from buddle.db.base import Base


class ImportanceScore(Base):
    """Per-post current importance: raw additive accumulator + normalized [-1, 1]."""

    __tablename__ = "importance_scores"

    post_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("posts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    raw_score: Mapped[float] = mapped_column(REAL, nullable=False, server_default=text("0"))
    normalized: Mapped[float] = mapped_column(REAL, nullable=False, server_default=text("0"))
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ImportanceContribution(Base):
    """Append-only log of importance deltas. raw_score = SUM(delta)."""

    __tablename__ = "importance_contributions"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    post_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    delta: Mapped[float] = mapped_column(REAL, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
