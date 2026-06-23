"""technician integrity hash chain

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-18 05:30:00

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "transformation_logs",
        sa.Column("sequence", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "transformation_logs",
        sa.Column("prev_hash", sa.String(64), nullable=True),
    )
    op.add_column(
        "transformation_logs",
        sa.Column("entry_hash", sa.String(64), nullable=True),
    )
    # Unique sequence enforces gap-free monotonic ordering of the chain.
    op.create_index(
        "uq_transformation_logs_sequence",
        "transformation_logs",
        ["sequence"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_transformation_logs_sequence", table_name="transformation_logs")
    op.drop_column("transformation_logs", "entry_hash")
    op.drop_column("transformation_logs", "prev_hash")
    op.drop_column("transformation_logs", "sequence")
