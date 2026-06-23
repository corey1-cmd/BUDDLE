"""conversation sessions + message.session_id

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-18 12:30:00

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversation_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("persona_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("topic", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_active_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["persona_id"], ["personas.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_conversation_sessions_persona_id", "conversation_sessions", ["persona_id"]
    )

    op.add_column(
        "messages",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_messages_session_id",
        "messages",
        "conversation_sessions",
        ["session_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_messages_session_id", "messages", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_messages_session_id", table_name="messages")
    op.drop_constraint("fk_messages_session_id", "messages", type_="foreignkey")
    op.drop_column("messages", "session_id")
    op.drop_index(
        "ix_conversation_sessions_persona_id", table_name="conversation_sessions"
    )
    op.drop_table("conversation_sessions")
