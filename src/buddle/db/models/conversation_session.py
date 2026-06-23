"""Conversation session — a topic-scoped conversation under a persona.

buddle conversations are NOT 1:1. A user opens a topic, the AI carries the
conversation, and the topic is open for OTHER people to join with the same
endpoint (a person). So a session is keyed by TOPIC, not by a peer:

  - one persona can have many sessions (one per topic), like separate
    GPT/Claude/Gemini chat threads;
  - within a session, messages flow freely (multi-turn), with their own
    independent context window;
  - participation is expressed by message authorship (reusing the plaza
    author taxonomy), so multiple people can contribute to one session.

Messages gain a session_id (the old persona_id is kept for backward
compatibility / migration). History loading is per-session, so each topic has
its own isolated memory.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from buddle.db.base import Base


class ConversationSession(Base):
    __tablename__ = "conversation_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    # The persona that owns/opened this session.
    persona_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("personas.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Topic/title — what distinguishes sessions (GPT-style thread title).
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    # Optional free-text topic tag for grouping/recommendation.
    topic: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Bumped on each new message; used to sort threads "most recent first".
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
