"""Topic association edge — weighted link between two topics (Layer B).

Built from co-occurrence + embedding proximity (ai/knowledge/edges); decays per
standby tick. Lets fetch_context reach one hop out to closely related topics.
Stored once per canonical (topic_a <= topic_b) pair.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import REAL, DateTime, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from buddle.db.base import Base


class TopicEdge(Base):
    __tablename__ = "topic_edges"
    __table_args__ = (
        UniqueConstraint("topic_a", "topic_b", name="uq_topic_edge_pair"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    topic_a: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    topic_b: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    weight: Mapped[float] = mapped_column(REAL, nullable=False, server_default="0")
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
