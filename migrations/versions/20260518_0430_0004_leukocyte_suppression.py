"""leukocyte suppression flag

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-18 04:30:00

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "posts",
        sa.Column(
            "is_suppressed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # Partial index to make "visible public feed" queries cheap.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_posts_public_visible "
        "ON posts (created_at DESC) "
        "WHERE visibility = 'public' AND is_suppressed = false"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_posts_public_visible")
    op.drop_column("posts", "is_suppressed")
