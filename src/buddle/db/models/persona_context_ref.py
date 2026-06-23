"""Persona context reference — what a persona drew on while conversing (Layer B).

Tracks which pool a persona referenced and when, supporting the "flexibility"
goal (and technician reproducibility: why a given pool was served).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import REAL, DateTime, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from buddle.db.base import Base


class PersonaContextRef(Base):
    __tablename__ = "persona_context_refs"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    persona_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    pool_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    relevance: Mapped[float] = mapped_column(REAL, nullable=False, server_default="0")
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
