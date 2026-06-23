"""persona topic affinity (feedback loop)

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-18 09:30:00

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "persona_topic_affinity",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("persona_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("topic", sa.String(64), nullable=False),
        sa.Column("affinity", sa.Float(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["persona_id"], ["personas.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("persona_id", "topic", name="uq_persona_topic"),
    )
    op.create_index(
        "ix_persona_topic_affinity_persona_id",
        "persona_topic_affinity",
        ["persona_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_persona_topic_affinity_persona_id", table_name="persona_topic_affinity"
    )
    op.drop_table("persona_topic_affinity")
