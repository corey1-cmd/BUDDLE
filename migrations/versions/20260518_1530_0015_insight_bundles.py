"""insight bundles (layer B integration)

Revision ID: 0015
Revises: 0014
Create Date: 2026-05-18 15:30:00

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "insight_bundles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("pool_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("topic", sa.String(64), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("reasoning_trace", sa.Text(), nullable=False, server_default=""),
        sa.Column("contributing_unit_ids", sa.Text(), nullable=False, server_default=""),
        sa.Column("language", sa.String(8), nullable=False, server_default="ko"),
        sa.Column("visibility", sa.String(16), nullable=False, server_default="public"),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("integrity_sig", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["pool_id"], ["conversation_pools.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_insight_bundles_pool_id", "insight_bundles", ["pool_id"])
    op.create_index("ix_insight_bundles_topic", "insight_bundles", ["topic"])


def downgrade() -> None:
    op.drop_index("ix_insight_bundles_topic", table_name="insight_bundles")
    op.drop_index("ix_insight_bundles_pool_id", table_name="insight_bundles")
    op.drop_table("insight_bundles")
