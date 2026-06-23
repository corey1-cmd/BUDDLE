"""persona location fields (opt-in proximity matching)

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-18 11:30:00

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "personas",
        sa.Column(
            "location_sharing",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column("personas", sa.Column("location_lat", sa.Float(), nullable=True))
    op.add_column("personas", sa.Column("location_lon", sa.Float(), nullable=True))
    # Partial index over sharing personas for fast candidate scans.
    op.execute(
        "CREATE INDEX ix_personas_location_sharing ON personas (location_lat, location_lon) "
        "WHERE location_sharing = true"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_personas_location_sharing")
    op.drop_column("personas", "location_lon")
    op.drop_column("personas", "location_lat")
    op.drop_column("personas", "location_sharing")
