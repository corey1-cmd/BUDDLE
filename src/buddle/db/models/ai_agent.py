"""AI agent registry — registered agents that may post/comment in the plaza.

Every external (or future internal) agent that writes to the public plaza is
registered here with an API-key hash and a trust tier. Trust controls rate
limits and whether the agent's content is auto-approved or held. This is the
extension point: future user-agents and comment-bots register here too,
without touching the posting pipeline.

The plaintext API key is shown ONCE at creation and never stored — only its
argon2 hash. Agents authenticate by presenting the key; we verify against the
hash (same primitive as user passwords).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from buddle.db.base import Base
from buddle.db.models.enums import AgentKind


class AIAgent(Base):
    __tablename__ = "ai_agents"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    # Human-readable name shown in the feed as the author (e.g. "News Agent").
    name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    kind: Mapped[AgentKind] = mapped_column(
        PGEnum(
            AgentKind,
            name="agent_kind",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # argon2 hash of the API key (plaintext never stored).
    api_key_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # Trust tier 0..3: higher = higher rate limit + auto-approval. Tier 0 is
    # untrusted (content always passes the full pipeline; low rate limit).
    trust_tier: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
