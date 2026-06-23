"""mediator policy + embedding indexes

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-18 03:30:00

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mediator_policy",
        sa.Column("id", sa.SmallInteger(), primary_key=True, server_default="1"),
        sa.Column("alpha", sa.REAL(), nullable=False, server_default="0.4"),
        sa.Column("beta", sa.REAL(), nullable=False, server_default="0.4"),
        sa.Column("gamma", sa.REAL(), nullable=False, server_default="0.2"),
        sa.Column("max_targets", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("min_relevance", sa.REAL(), nullable=False, server_default="0.05"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("id = 1", name="mediator_policy_singleton"),
    )
    op.execute(
        "INSERT INTO mediator_policy (id) VALUES (1) ON CONFLICT (id) DO NOTHING"
    )

    # Approximate-nearest-neighbour indexes for cosine similarity on embeddings.
    # ivfflat needs ANALYZE after data is present; lists=100 is a sane default
    # for up to ~1M rows. Created here so Stage 3 similarity queries are fast.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_posts_content_emb "
        "ON posts USING ivfflat (content_emb vector_cosine_ops) WITH (lists = 100)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_personas_context_emb "
        "ON personas USING ivfflat (context_emb vector_cosine_ops) WITH (lists = 100)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_personas_context_emb")
    op.execute("DROP INDEX IF EXISTS idx_posts_content_emb")
    op.drop_table("mediator_policy")
