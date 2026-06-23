"""Authority tokens — central_manager vs technician dynamic authority via token balances.

This is the core mechanism that allows the technician to override the central
manager when unjustified transformations accumulate (e.g. central manager
compromised).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import REAL, CheckConstraint, DateTime, SmallInteger, Text, func, text
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from buddle.db.base import Base
from buddle.db.models.enums import AIRole, AuthorityStateEnum


class AuthorityToken(Base):
    """Per-(role, instance) authority balance."""

    __tablename__ = "authority_tokens"

    entity_type: Mapped[AIRole] = mapped_column(
        PGEnum(
            AIRole,
            name="ai_role",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        primary_key=True,
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    balance: Mapped[float] = mapped_column(REAL, nullable=False, server_default=text("0"))
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SystemAuthorityState(Base):
    """Singleton row holding the current global authority state."""

    __tablename__ = "system_authority_state"
    __table_args__ = (CheckConstraint("id = 1", name="authority_singleton"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, server_default=text("1"))
    state: Mapped[AuthorityStateEnum] = mapped_column(
        PGEnum(
            AuthorityStateEnum,
            name="authority_state",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        server_default=text("'normal'::authority_state"),
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
