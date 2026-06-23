"""Persona model registry — each row represents a trained (or stub) persona AI
that users can adopt. New rows can be added at runtime via admin API; no
migration required.

Lifecycle: draft -> staging -> active -> retired.
Existing personas keep working even after their model is retired (RESTRICT FK).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, String, Text, func, text
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from buddle.db.base import Base
from buddle.db.models.enums import PersonaBackendKind, PersonaModelStatus


class PersonaModel(Base):
    __tablename__ = "persona_models"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    # Stable key used by Persona.model_key. Lowercase kebab/snake recommended.
    template_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'0.1.0'"))

    # How to serve inference for this persona
    backend_kind: Mapped[PersonaBackendKind] = mapped_column(
        PGEnum(
            PersonaBackendKind,
            name="persona_backend_kind",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        server_default=text("'stub'::persona_backend_kind"),
    )
    # Backend-specific config: {model_path, lora_adapter, endpoint_url, ...}
    backend_config: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[PersonaModelStatus] = mapped_column(
        PGEnum(
            PersonaModelStatus,
            name="persona_model_status",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        server_default=text("'draft'::persona_model_status"),
    )
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"<PersonaModel key={self.template_key} v{self.version} "
            f"backend={self.backend_kind.value} status={self.status.value}>"
        )
