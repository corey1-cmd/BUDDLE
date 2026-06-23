"""Transformation logs — every data mutation is recorded with signature.

Verified vs unverified mutations drive the dynamic authority computation.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import REAL, BigInteger, Boolean, DateTime, LargeBinary, String, func, text
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from buddle.db.base import Base
from buddle.db.models.enums import AIRole, TransformationTypeEnum


class TransformationLog(Base):
    __tablename__ = "transformation_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    source_ai: Mapped[AIRole] = mapped_column(
        PGEnum(
            AIRole,
            name="ai_role",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )
    source_instance_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    target_data_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    target_data_type: Mapped[str] = mapped_column(String(32), nullable=False)
    magnitude: Mapped[float] = mapped_column(REAL, nullable=False)
    transformation_type: Mapped[TransformationTypeEnum] = mapped_column(
        PGEnum(
            TransformationTypeEnum,
            name="transformation_type",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )
    justification_signature: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    verification_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # ── Tamper-evident hash chain (HMAC-SHA256 over canonical bytes ‖ prev_hash) ──
    # Monotonic per-stream sequence; chain links each entry to its predecessor.
    sequence: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    prev_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entry_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
