"""Metric snapshot — a periodic, immutable record of system health produced by
the central manager. Storing snapshots gives the human admin trend lines
('how often is feedback produced', 'is usage growing') and lets the UI render
sparklines without recomputing history every time.

The payload is a JSONB blob of the SystemReport (golden signals, 5-AI status,
engagement, top conversation topics) so the schema can evolve without
migrations — snapshots are append-only and self-describing via `kind`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from buddle.db.base import Base


class MetricSnapshot(Base):
    __tablename__ = "metric_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    # 'scheduled' | 'on_demand' — how this snapshot was triggered.
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="on_demand")
    # Full SystemReport serialized; evolves without migration.
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # Denormalized health verdict for cheap filtering/alerting: ok|warn|critical
    health: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
