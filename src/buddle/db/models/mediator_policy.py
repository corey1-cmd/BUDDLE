"""Mediator policy — singleton row holding the distribution algorithm weights.

relevance = alpha*tag_overlap + beta*content_similarity + gamma*user_growth

Stage 1 kept these in process memory; Stage 3 persists them so admin changes
survive restarts and apply across replicas.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import REAL, CheckConstraint, DateTime, Integer, SmallInteger, func, text
from sqlalchemy.orm import Mapped, mapped_column

from buddle.db.base import Base


class MediatorPolicy(Base):
    __tablename__ = "mediator_policy"
    __table_args__ = (CheckConstraint("id = 1", name="mediator_policy_singleton"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, server_default=text("1"))
    alpha: Mapped[float] = mapped_column(REAL, nullable=False, server_default=text("0.4"))
    beta: Mapped[float] = mapped_column(REAL, nullable=False, server_default=text("0.4"))
    gamma: Mapped[float] = mapped_column(REAL, nullable=False, server_default=text("0.2"))
    max_targets: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("5"))
    # Minimum relevance a target must reach to receive a private distribution.
    min_relevance: Mapped[float] = mapped_column(REAL, nullable=False, server_default=text("0.05"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
