"""persona long-term memory (LTM)

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-12 09:00:00

Persists the EKB Retention stage so the EKB Search stage of later turns can
consult it (cognition pipeline already produced retained summaries per turn;
this gives them a durable store). Retrieval composition follows Park et al.
2023 (recency·importance·relevance); columns map 1:1 onto the score terms —
see src/buddle/ai/memory/scoring.py.

  * persona_memories.emb is nullable: an embedding-provider failure must not
    block remembering (recency-only fallback at recall time).
  * ON DELETE CASCADE from personas: deleting a persona forgets everything —
    data sovereignty by construction.
  * ivfflat cosine ANN index matches the posts/personas index style (0016).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBED_DIM = 1024  # BGE-M3 — keep in sync with src/buddle/ai/embeddings/base.py

memory_kind_enum = postgresql.ENUM(
    "fact",
    "preference",
    "event",
    "relation",
    name="memory_kind",
    create_type=False,
)


def upgrade() -> None:
    memory_kind_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "persona_memories",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("persona_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", memory_kind_enum, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("emb", Vector(EMBED_DIM), nullable=True),
        sa.Column("importance", sa.REAL(), nullable=False, server_default=sa.text("0.5")),
        sa.Column("strength", sa.REAL(), nullable=False, server_default=sa.text("1.0")),
        sa.Column("source_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_accessed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["persona_id"], ["personas.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_session_id"], ["conversation_sessions.id"], ondelete="SET NULL"
        ),
    )
    op.create_index("ix_persona_memories_persona_id", "persona_memories", ["persona_id"])
    # Recency fallback path (embedding unavailable) scans by last access.
    op.create_index(
        "ix_persona_memories_persona_last_accessed",
        "persona_memories",
        ["persona_id", "last_accessed_at"],
    )
    # ANN index — same style as posts/personas (0016).
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_persona_memories_emb "
        "ON persona_memories USING ivfflat (emb vector_cosine_ops) WITH (lists = 100)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_persona_memories_emb")
    op.drop_index("ix_persona_memories_persona_last_accessed", table_name="persona_memories")
    op.drop_index("ix_persona_memories_persona_id", table_name="persona_memories")
    op.drop_table("persona_memories")
    memory_kind_enum.drop(op.get_bind(), checkfirst=True)
