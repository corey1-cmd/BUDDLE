"""Persona model — user-owned persona AI configuration."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from buddle.ai.embeddings.base import EMBED_DIM
from buddle.db.base import Base

if TYPE_CHECKING:
    from buddle.db.models.persona_model import PersonaModel
    from buddle.db.models.tag import PersonaInterestTag
    from buddle.db.models.user import User


class Persona(Base):
    __tablename__ = "personas"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    # FK to persona_models.template_key. RESTRICT: a model cannot be deleted
    # while personas reference it; retire it instead.
    model_key: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("persona_models.template_key", ondelete="RESTRICT", onupdate="CASCADE"),
        nullable=False,
    )
    context_emb: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    # Virtual chat persona: same model/abilities as a normal persona, but not
    # bound to a real user. Posts in the plaza driven by mediator briefings.
    is_virtual: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    virtual_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Argument-AI opt-out (0021): when true, the author has disabled the
    # "talk to this person's AI" feature for their posts → such requests 404.
    # Data sovereignty + AI transparency: reconstruction is opt-out-able.
    argument_ai_opt_out: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # Location-based matching (opt-in). Exact coordinates are stored (precision
    # choice) but only ever EXPOSED in a coarsened form. Matching is active only
    # when location_sharing is true AND both lat/lon are set.
    # Preferred language for reading/writing (Korean-first default).
    preferred_language: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default=text("'ko'")
    )
    location_sharing: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    location_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    user: Mapped[User] = relationship(back_populates="personas")
    model: Mapped[PersonaModel] = relationship(
        primaryjoin="Persona.model_key == foreign(PersonaModel.template_key)",
        viewonly=True,
        lazy="joined",
    )
    interest_tags: Mapped[list[PersonaInterestTag]] = relationship(
        back_populates="persona",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Persona id={self.id} name={self.name} model_key={self.model_key}>"
