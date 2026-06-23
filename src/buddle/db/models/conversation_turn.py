"""ConversationTurn model — the structured, re-readable turn log.

`messages` stores raw text; this stores each turn *with its analysis* so a
persona can re-read the conversation as structured data (situation, affect,
whether it was a follow-up, whether it opened self-disclosure, salient topics,
and the affinity delta it produced). This single table feeds the recent
window, mood, follow-up tracking, and the relationship score.

Why separate from `messages`: messages are the user-facing transcript;
conversation_turns is the persona's analytic memory of the dialogue. Keeping
them apart means analysis can evolve (new fields) without touching the
transcript, and a turn can be re-analyzed without rewriting history.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ARRAY, REAL, Boolean, DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from buddle.db.base import Base
from buddle.db.models.enums import ConversationSituationEnum, MessageRole, TurnValenceEnum


class ConversationTurn(Base):
    __tablename__ = "conversation_turns"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("conversation_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    persona_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("personas.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[MessageRole] = mapped_column(
        PGEnum(
            MessageRole,
            name="message_role",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Analysis metadata (null for persona turns where it doesn't apply).
    situation: Mapped[ConversationSituationEnum | None] = mapped_column(
        PGEnum(
            ConversationSituationEnum,
            name="conversation_situation",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=True,
    )
    valence: Mapped[TurnValenceEnum | None] = mapped_column(
        PGEnum(
            TurnValenceEnum,
            name="turn_valence",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=True,
    )
    intensity: Mapped[float | None] = mapped_column(REAL, nullable=True)
    was_followup: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    opened_disclosure: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    salient_topics: Mapped[list[str] | None] = mapped_column(ARRAY(String(64)), nullable=True)
    affinity_delta: Mapped[float | None] = mapped_column(REAL, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"), index=True
    )
