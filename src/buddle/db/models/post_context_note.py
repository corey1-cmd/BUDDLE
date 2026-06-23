"""PostContextNote model — context/evidence surfaced by argument-AI chats.

When an argument-AI conversation produces a useful supporting fact or
clarification, it can be saved back onto the post ("포스트에 근거·맥락 함께
저장"), then shown in the feed detail as "이 글의 부가 맥락". One row per saved
note, linked to its post and (optionally) the session it came from.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from buddle.db.base import Base
from buddle.db.models.enums import ContextNoteKind


class PostContextNote(Base):
    __tablename__ = "post_context_notes"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa_text("gen_random_uuid()"),
    )
    post_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[ContextNoteKind] = mapped_column(
        PGEnum(
            ContextNoteKind,
            name="context_note_kind",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_session_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("conversation_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_text("now()"), index=True
    )
