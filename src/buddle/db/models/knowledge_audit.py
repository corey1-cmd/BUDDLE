"""Knowledge audit — append-only log of supervising-AI actions (Layer B).

Records what central / technician / leukocyte did in the space (retain checks,
integrity repairs, ethics re-screens, threshold autotune), for transparency
and reproducibility.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from buddle.db.base import Base


class KnowledgeAudit(Base):
    __tablename__ = "knowledge_audits"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    actor_ai: Mapped[str] = mapped_column(
        String(16), nullable=False
    )  # central|technician|leukocyte
    action: Mapped[str] = mapped_column(String(48), nullable=False)
    target_type: Mapped[str] = mapped_column(String(24), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verdict: Mapped[str | None] = mapped_column(String(24), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
