"""argument_units.post_id nullable (tag-level stance contributions)

Revision ID: 0022
Revises: 0021
Create Date: 2026-06-12 16:00:00

A user can contribute a claim (and grounds) directly to a topic's debate by
picking a side (편 나눠 주장 추가), with no source post. Such argument_units have
no post_id, so the column becomes nullable.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "argument_units",
        "post_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=True,
    )


def downgrade() -> None:
    # Note: rows with NULL post_id must be removed before tightening again.
    op.execute("DELETE FROM argument_units WHERE post_id IS NULL")
    op.alter_column(
        "argument_units",
        "post_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=False,
    )
