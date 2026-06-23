"""user profiles (OCEAN soft estimates + sovereignty flags)

Revision ID: 0018
Revises: 0017
Create Date: 2026-06-12 11:00:00

One row per user: Big Five / OCEAN soft estimates (EWMA-updated, η=0.1 —
single utterances cannot flip a trait; Fleeson 2001), saturating confidence
(1 − exp(−n/30)), and an interest-embedding centroid fed by post embeddings
the mediator already computes. Sovereignty columns are structural:
profile_opt_out (거부), is_user_edited (수정 = 자동 갱신 동결), row delete
(삭제), GET /v1/me/profile (열람). No demographic / protected attributes by
design — connection-only profiling (§10-1).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBED_DIM = 1024  # BGE-M3 — keep in sync with src/buddle/ai/embeddings/base.py


def upgrade() -> None:
    op.create_table(
        "user_profiles",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("o", sa.REAL(), nullable=False, server_default=sa.text("0.5")),
        sa.Column("c", sa.REAL(), nullable=False, server_default=sa.text("0.5")),
        sa.Column("e", sa.REAL(), nullable=False, server_default=sa.text("0.5")),
        sa.Column("a", sa.REAL(), nullable=False, server_default=sa.text("0.5")),
        sa.Column("n", sa.REAL(), nullable=False, server_default=sa.text("0.5")),
        sa.Column("confidence", sa.REAL(), nullable=False, server_default=sa.text("0.0")),
        sa.Column("evidence_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("interests_emb", Vector(EMBED_DIM), nullable=True),
        sa.Column("profile_opt_out", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_user_edited", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("user_profiles")
