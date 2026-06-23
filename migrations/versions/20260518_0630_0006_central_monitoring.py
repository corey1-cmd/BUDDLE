"""central manager: sessions + metric snapshots

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-18 06:30:00

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activity_count", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    # Fast lookup of a user's currently-open session.
    op.execute(
        "CREATE INDEX ix_user_sessions_open "
        "ON user_sessions (user_id) WHERE ended_at IS NULL"
    )

    op.create_table(
        "metric_snapshots",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("kind", sa.String(32), nullable=False, server_default="on_demand"),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("health", sa.String(16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_metric_snapshots_health", "metric_snapshots", ["health"])
    op.create_index(
        "ix_metric_snapshots_created_at", "metric_snapshots", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_metric_snapshots_created_at", table_name="metric_snapshots")
    op.drop_index("ix_metric_snapshots_health", table_name="metric_snapshots")
    op.drop_table("metric_snapshots")
    op.execute("DROP INDEX IF EXISTS ix_user_sessions_open")
    op.drop_index("ix_user_sessions_user_id", table_name="user_sessions")
    op.drop_table("user_sessions")
