"""virtual personas + post read_count

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-18 08:30:00

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "personas",
        sa.Column(
            "is_virtual", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "personas", sa.Column("virtual_role", sa.String(32), nullable=True)
    )
    # Fast lookup of virtual personas for the scheduler.
    op.execute(
        "CREATE INDEX ix_personas_virtual ON personas (virtual_role) "
        "WHERE is_virtual = true"
    )
    op.add_column(
        "posts",
        sa.Column("read_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("posts", "read_count")
    op.execute("DROP INDEX IF EXISTS ix_personas_virtual")
    op.drop_column("personas", "virtual_role")
    op.drop_column("personas", "is_virtual")
