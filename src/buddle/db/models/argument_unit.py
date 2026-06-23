"""ArgumentUnit model — the dashboard's structured argument store.

One row per extracted argumentative unit (Toulmin-reduced: claim / ground /
rebuttal / question), linked to its source post and the topic tag it argues
under. Claims carry an embedding so the dashboard can cluster them into
conversation axes; non-claim units reference their parent claim.

  * topic_tag_id — which topic this argues under (the dashboard groups by tag).
  * kind / stance — the 4-way / 3-way classification.
  * emb — claim embedding (nullable; non-claims and embed-failures leave it
    null, and such claims fall back to the dominant axis).
  * parent_unit_id — a ground/rebuttal points at the claim it supports/attacks.

Why a separate table from posts/comments: arguments are a *derived analytic
view* of post content. Re-extraction can evolve without touching posts, and a
post can contribute several units across several topics.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from buddle.ai.embeddings.base import EMBED_DIM
from buddle.db.base import Base
from buddle.db.models.enums import ArgumentKindEnum, ArgumentStanceEnum


class ArgumentUnit(Base):
    __tablename__ = "argument_units"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa_text("gen_random_uuid()"),
    )
    # Nullable: most units come from a post, but a user can contribute a claim
    # directly to a topic's debate (편 나눠 주장 추가) with no source post.
    post_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    topic_tag_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tags.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[ArgumentKindEnum] = mapped_column(
        PGEnum(
            ArgumentKindEnum,
            name="argument_kind",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )
    stance: Mapped[ArgumentStanceEnum] = mapped_column(
        PGEnum(
            ArgumentStanceEnum,
            name="argument_stance",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    emb: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM), nullable=True)
    parent_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("argument_units.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_text("now()"), index=True
    )
