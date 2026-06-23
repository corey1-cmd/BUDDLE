"""Persona topic affinity — the small, bounded state of the feedback loop.

One row per (persona, topic). `affinity` is a scalar in [-cap, +cap] that the
mediator nudges from plaza reactions (see ai/mediator/feedback.py). It feeds a
SMALL proactivity offset into the persona's dialogue cognition — fine-tuning
emphasis on topics the audience responds well/poorly to, never changing safety
or core character.

Kept deliberately minimal and append-light: bounded magnitude, updated in
place, with updated_at for observability.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from buddle.db.base import Base


class PersonaTopicAffinity(Base):
    __tablename__ = "persona_topic_affinity"
    __table_args__ = (UniqueConstraint("persona_id", "topic", name="uq_persona_topic"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    persona_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("personas.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    topic: Mapped[str] = mapped_column(String(64), nullable=False)
    # Bounded to [-AFFINITY_CAP, +AFFINITY_CAP] by the service; small by design.
    affinity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
