"""UserProfile model — OCEAN soft estimates + interest centroid, per user.

One row per user. All trait values are SOFT estimates (text inference ceiling
r ≈ 0.3–0.4 — Mairesse 2007; Park 2015): `confidence` rises with evidence and
must gate any downstream use. Sovereignty is structural:

  * profile_opt_out  — observation stops AND matching must skip the profile
                       bucket (콘텐츠·위치만으로 재정규화 — §10-1 거부권).
  * is_user_edited   — the user corrected their traits; automatic EWMA
                       updates freeze (수정권: 사용자의 말이 최종).
  * row deletion     — 삭제권; CASCADE from users covers account deletion.

No demographic or protected attributes exist in this schema, on purpose —
connection-only profiling is enforced at the column level.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import REAL, Boolean, DateTime, ForeignKey, Integer, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from buddle.ai.embeddings.base import EMBED_DIM
from buddle.db.base import Base


class UserProfile(Base):
    __tablename__ = "user_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # OCEAN — neutral prior 0.5 until evidence accumulates.
    o: Mapped[float] = mapped_column(REAL, nullable=False, server_default=text("0.5"))
    c: Mapped[float] = mapped_column(REAL, nullable=False, server_default=text("0.5"))
    e: Mapped[float] = mapped_column(REAL, nullable=False, server_default=text("0.5"))
    a: Mapped[float] = mapped_column(REAL, nullable=False, server_default=text("0.5"))
    n: Mapped[float] = mapped_column(REAL, nullable=False, server_default=text("0.5"))
    confidence: Mapped[float] = mapped_column(REAL, nullable=False, server_default=text("0.0"))
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    # Interest centroid — EWMA of post content embeddings (no extra embed calls).
    interests_emb: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM), nullable=True)
    profile_opt_out: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    is_user_edited: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
    )
