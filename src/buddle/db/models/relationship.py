"""Relationship model — the running bond between a persona and its user.

One row per (persona, user). Persists the Social-Penetration-Theory level and
the Gottman emotional-bank-account score, plus the recent-mood snapshot and a
small cache of the user's profile so the persona can stay in character without
re-deriving everything each turn.

  * affinity_score — Gottman emotional bank account (0..100). Updated per user
    turn by buddle.ai.conversation.relationship.affinity_delta.
  * level — SPT stage (0..4), derived from the score with downgrade hysteresis.
  * mood_valence / mood_energy — the recent window's emotional weather, so the
    persona matches energy (not amplifies it).
  * positive_turns / negative_turns — running tallies, so the 5:1 ratio is
    observable and explainable.
  * user_snapshot — small JSON cache of the central user profile (OCEAN +
    interests summary) captured for this persona; "사용자 대응 성격 특성".
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, REAL, DateTime, ForeignKey, Integer, SmallInteger, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from buddle.db.base import Base


class Relationship(Base):
    __tablename__ = "relationships"

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
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    affinity_score: Mapped[float] = mapped_column(REAL, nullable=False, server_default=text("0"))
    level: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    mood_valence: Mapped[float] = mapped_column(REAL, nullable=False, server_default=text("0"))
    mood_energy: Mapped[float] = mapped_column(REAL, nullable=False, server_default=text("0"))
    positive_turns: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    negative_turns: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    turn_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    user_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
    )
