"""Ethics alerts — raised by the leukocyte AI, reviewed by human admin."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func, text
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from buddle.db.base import Base
from buddle.db.models.enums import AlertStatus


class EthicsAlert(Base):
    __tablename__ = "ethics_alerts"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    target_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)  # 'post' | 'user'
    severity: Mapped[str] = mapped_column(String(16), nullable=False)  # 'low' | 'mid' | 'high'
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[AlertStatus] = mapped_column(
        PGEnum(
            AlertStatus,
            name="alert_status",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        server_default=text("'open'::alert_status"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
