"""multilingual: post language + translations + persona preferred language

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-18 13:30:00

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "posts",
        sa.Column(
            "source_language",
            sa.String(8),
            nullable=False,
            server_default=sa.text("'ko'"),
        ),
    )
    op.add_column(
        "personas",
        sa.Column(
            "preferred_language",
            sa.String(8),
            nullable=False,
            server_default=sa.text("'ko'"),
        ),
    )
    op.create_table(
        "post_translations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("post_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("language", sa.String(8), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("post_id", "language", name="uq_post_translation_lang"),
    )
    op.create_index(
        "ix_post_translations_post_id", "post_translations", ["post_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_post_translations_post_id", table_name="post_translations")
    op.drop_table("post_translations")
    op.drop_column("personas", "preferred_language")
    op.drop_column("posts", "source_language")
