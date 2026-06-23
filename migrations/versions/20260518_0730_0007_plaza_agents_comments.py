"""plaza: ai agents, comments, post author kind

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-18 07:30:00

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # New enum types
    author_kind = postgresql.ENUM(
        "human", "persona_ai", "external_ai", "bot", name="author_kind"
    )
    agent_kind = postgresql.ENUM(
        "news", "trend", "qna", "recommendation", "generic", name="agent_kind"
    )
    comment_kind = postgresql.ENUM(
        "inform", "empathize", "question", name="comment_kind"
    )
    bind = op.get_bind()
    author_kind.create(bind, checkfirst=True)
    agent_kind.create(bind, checkfirst=True)
    comment_kind.create(bind, checkfirst=True)

    # ai_agents registry
    op.create_table(
        "ai_agents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(80), nullable=False, unique=True),
        sa.Column(
            "kind",
            postgresql.ENUM(name="agent_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("api_key_hash", sa.String(255), nullable=False),
        sa.Column("trust_tier", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )

    # posts: author columns
    op.add_column(
        "posts",
        sa.Column(
            "author_kind",
            postgresql.ENUM(name="author_kind", create_type=False),
            nullable=False,
            server_default="human",
        ),
    )
    op.add_column("posts", sa.Column("author_label", sa.Text(), nullable=True))
    op.add_column(
        "posts",
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_posts_agent_id", "posts", "ai_agents", ["agent_id"], ["id"], ondelete="SET NULL"
    )

    # comments
    op.create_table(
        "comments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("post_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "kind",
            postgresql.ENUM(name="comment_kind", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "author_kind",
            postgresql.ENUM(name="author_kind", create_type=False),
            nullable=False,
            server_default="human",
        ),
        sa.Column("author_label", sa.Text(), nullable=True),
        sa.Column("author_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_persona_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "is_suppressed", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_id"], ["comments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["source_persona_id"], ["personas.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["ai_agents.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_comments_post_id", "comments", ["post_id"])
    op.create_index("ix_comments_created_at", "comments", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_comments_created_at", table_name="comments")
    op.drop_index("ix_comments_post_id", table_name="comments")
    op.drop_table("comments")
    op.drop_constraint("fk_posts_agent_id", "posts", type_="foreignkey")
    op.drop_column("posts", "agent_id")
    op.drop_column("posts", "author_label")
    op.drop_column("posts", "author_kind")
    op.drop_table("ai_agents")
    bind = op.get_bind()
    postgresql.ENUM(name="comment_kind").drop(bind, checkfirst=True)
    postgresql.ENUM(name="agent_kind").drop(bind, checkfirst=True)
    postgresql.ENUM(name="author_kind").drop(bind, checkfirst=True)
