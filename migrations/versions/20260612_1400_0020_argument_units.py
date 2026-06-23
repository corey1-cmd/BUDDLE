"""argument units (debate dashboard — Toulmin reduced)

Revision ID: 0020
Revises: 0019
Create Date: 2026-06-12 14:00:00

Persists extracted argument units for the topic debate dashboard:

  * argument_units — one row per claim / ground / rebuttal / question
    (Stab & Gurevych 2017 reduction of Toulmin), linked to its source post and
    topic tag. Claims carry a BGE-M3 embedding so the dashboard can cluster
    them into conversation axes (대화 축); grounds/rebuttals point at the claim
    they support/attack via parent_unit_id.

Two enums (argument_kind, argument_stance) back the classification. The
ivfflat cosine index matches the posts/personas/memory index style.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBED_DIM = 1024  # BGE-M3 — keep in sync with src/buddle/ai/embeddings/base.py

kind_enum = postgresql.ENUM(
    "claim", "ground", "rebuttal", "question", name="argument_kind", create_type=False
)
stance_enum = postgresql.ENUM("pro", "con", "neutral", name="argument_stance", create_type=False)


def upgrade() -> None:
    kind_enum.create(op.get_bind(), checkfirst=True)
    stance_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "argument_units",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("post_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("topic_tag_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", kind_enum, nullable=False),
        sa.Column("stance", stance_enum, nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("emb", Vector(EMBED_DIM), nullable=True),
        sa.Column("parent_unit_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["topic_tag_id"], ["tags.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_unit_id"], ["argument_units.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_argument_units_post_id", "argument_units", ["post_id"])
    op.create_index("ix_argument_units_topic_tag_id", "argument_units", ["topic_tag_id"])
    op.create_index("ix_argument_units_created_at", "argument_units", ["created_at"])
    # The dashboard query: claims of a topic, by recency.
    op.create_index(
        "ix_argument_units_topic_kind_created",
        "argument_units",
        ["topic_tag_id", "kind", "created_at"],
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_argument_units_emb "
        "ON argument_units USING ivfflat (emb vector_cosine_ops) WITH (lists = 100)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_argument_units_emb")
    op.drop_index("ix_argument_units_topic_kind_created", table_name="argument_units")
    op.drop_index("ix_argument_units_created_at", table_name="argument_units")
    op.drop_index("ix_argument_units_topic_tag_id", table_name="argument_units")
    op.drop_index("ix_argument_units_post_id", table_name="argument_units")
    op.drop_table("argument_units")
    stance_enum.drop(op.get_bind(), checkfirst=True)
    kind_enum.drop(op.get_bind(), checkfirst=True)
