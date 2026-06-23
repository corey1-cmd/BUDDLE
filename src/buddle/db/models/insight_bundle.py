"""Insight bundle — a synthesized integration of knowledge units (Layer B).

Produced selectively (not for every pool) by recombining + reasoning over a
pool's units. Carries the summary, the reasoning trace (reproducibility), the
contributing unit ids (traceability), and a status set by the leukocyte gate.
visibility is inherited from the (homogeneous) input units, so a public bundle
is built only from public units.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from buddle.db.base import Base


class InsightBundle(Base):
    __tablename__ = "insight_bundles"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    pool_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("conversation_pools.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    topic: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    reasoning_trace: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    # CSV of contributing knowledge_unit ids (traceability).
    contributing_unit_ids: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    language: Mapped[str] = mapped_column(String(8), nullable=False, server_default="ko")
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, server_default="public")
    # draft -> approved (leukocyte ok) | blocked (leukocyte blocked)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="draft")
    integrity_sig: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
