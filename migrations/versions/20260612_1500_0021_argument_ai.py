"""post context notes + argument-AI opt-out (RAG conversation)

Revision ID: 0021
Revises: 0020
Create Date: 2026-06-12 15:00:00

Backs the argument/persona AI conversation (RAG):

  * post_context_notes — supporting context/evidence/clarification surfaced by
    an argument-AI chat, saved back onto the post and shown in the feed detail.
  * personas.argument_ai_opt_out — authors can disable "talk to this person's
    AI" for their posts; such requests then 404 (data sovereignty + AI
    transparency: reconstruction is opt-out-able).

One enum (context_note_kind) backs the note classification.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

note_kind_enum = postgresql.ENUM(
    "context", "evidence", "clarification", name="context_note_kind", create_type=False
)


def upgrade() -> None:
    note_kind_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "personas",
        sa.Column(
            "argument_ai_opt_out",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    op.create_table(
        "post_context_notes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("post_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", note_kind_enum, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_session_id"], ["conversation_sessions.id"], ondelete="SET NULL"
        ),
    )
    op.create_index("ix_post_context_notes_post_id", "post_context_notes", ["post_id"])
    op.create_index("ix_post_context_notes_created_at", "post_context_notes", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_post_context_notes_created_at", table_name="post_context_notes")
    op.drop_index("ix_post_context_notes_post_id", table_name="post_context_notes")
    op.drop_table("post_context_notes")
    op.drop_column("personas", "argument_ai_opt_out")
    note_kind_enum.drop(op.get_bind(), checkfirst=True)
