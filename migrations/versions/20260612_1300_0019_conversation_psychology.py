"""relationships + conversation turns (conversation psychology)

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-12 13:00:00

Persists the persona<->user bond and a structured, re-readable turn log:

  * relationships — Social-Penetration-Theory level (0..4) + Gottman emotional
    bank account score (0..100) + recent-mood snapshot + cached user profile.
    One row per (persona, user); CASCADE on either delete.
  * conversation_turns — each turn with its analysis (situation, valence,
    intensity, follow-up flag, self-disclosure flag, salient topics, affinity
    delta). The single source for the recent window, mood, follow-up tracking,
    and the relationship score.

Three enums back the turn analysis: conversation_situation, turn_valence (both
new) and message_role (reused from 0001).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

situation_enum = postgresql.ENUM(
    "empathic",
    "objective",
    "assertive",
    "reflective",
    "social",
    name="conversation_situation",
    create_type=False,
)
valence_enum = postgresql.ENUM(
    "positive",
    "negative",
    "neutral",
    name="turn_valence",
    create_type=False,
)
# message_role already exists (0001); reference without creating.
message_role_enum = postgresql.ENUM(name="message_role", create_type=False)


def upgrade() -> None:
    situation_enum.create(op.get_bind(), checkfirst=True)
    valence_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "relationships",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("persona_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("affinity_score", sa.REAL(), nullable=False, server_default=sa.text("0")),
        sa.Column("level", sa.SmallInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("mood_valence", sa.REAL(), nullable=False, server_default=sa.text("0")),
        sa.Column("mood_energy", sa.REAL(), nullable=False, server_default=sa.text("0")),
        sa.Column("positive_turns", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("negative_turns", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("turn_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("user_snapshot", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["persona_id"], ["personas.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("persona_id", "user_id", name="uq_relationship_persona_user"),
    )
    op.create_index("ix_relationships_persona_id", "relationships", ["persona_id"])
    op.create_index("ix_relationships_user_id", "relationships", ["user_id"])

    op.create_table(
        "conversation_turns",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("persona_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", message_role_enum, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("situation", situation_enum, nullable=True),
        sa.Column("valence", valence_enum, nullable=True),
        sa.Column("intensity", sa.REAL(), nullable=True),
        sa.Column("was_followup", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "opened_disclosure", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("salient_topics", postgresql.ARRAY(sa.String(length=64)), nullable=True),
        sa.Column("affinity_delta", sa.REAL(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["session_id"], ["conversation_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["persona_id"], ["personas.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_conversation_turns_session_id", "conversation_turns", ["session_id"])
    op.create_index("ix_conversation_turns_created_at", "conversation_turns", ["created_at"])
    # The recent-window query: latest N turns of a session.
    op.create_index(
        "ix_conversation_turns_session_created",
        "conversation_turns",
        ["session_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_conversation_turns_session_created", table_name="conversation_turns")
    op.drop_index("ix_conversation_turns_created_at", table_name="conversation_turns")
    op.drop_index("ix_conversation_turns_session_id", table_name="conversation_turns")
    op.drop_table("conversation_turns")
    op.drop_index("ix_relationships_user_id", table_name="relationships")
    op.drop_index("ix_relationships_persona_id", table_name="relationships")
    op.drop_table("relationships")
    valence_enum.drop(op.get_bind(), checkfirst=True)
    situation_enum.drop(op.get_bind(), checkfirst=True)
