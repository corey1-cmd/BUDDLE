"""Conversation pool — a topic's bag of reference units (Layer B).

NOT a summary: a curated set of knowledge units a persona can draw on when
talking about this topic. freshness decays per tick; last_served_at updates on
fetch. Member units are tracked via pool_units (many-to-many).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import REAL, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from buddle.db.base import Base


class ConversationPool(Base):
    __tablename__ = "conversation_pools"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    topic: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    size: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    freshness: Mapped[float] = mapped_column(REAL, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_served_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PoolUnit(Base):
    """Membership: which knowledge units are in which pool."""

    __tablename__ = "pool_units"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    pool_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False, index=True
    )
    unit_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False, index=True
    )
    membership_score: Mapped[float] = mapped_column(REAL, nullable=False, server_default="0")
