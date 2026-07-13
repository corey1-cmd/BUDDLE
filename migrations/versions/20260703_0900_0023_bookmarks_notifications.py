"""post bookmarks + user notifications

Revision ID: 0023
Revises: 0022
Create Date: 2026-07-03 09:00:00

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    notification_kind = postgresql.ENUM("like", "comment", name="notification_kind")
    notification_kind.create(op.get_bind(), checkfirst=True)

    # ── post_bookmarks: private save-for-later (same idempotency shape as
    # post_likes — one row per (user, post)) ──────────────────────────────
    op.create_table(
        "post_bookmarks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("post_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "post_id", name="uq_post_bookmark_user_post"),
    )
    op.create_index("ix_post_bookmarks_post_id", "post_bookmarks", ["post_id"])
    op.create_index("ix_post_bookmarks_user_id", "post_bookmarks", ["user_id"])

    # ── notifications: recipient-scoped activity events (read_at NULL = unread) ──
    op.create_table(
        "notifications",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "kind",
            postgresql.ENUM(name="notification_kind", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "actor_kind",
            postgresql.ENUM(name="author_kind", create_type=False),
            nullable=False,
            server_default="human",
        ),
        sa.Column("actor_label", sa.Text(), nullable=True),
        sa.Column("post_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("preview", sa.Text(), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_notifications_post_id", "notifications", ["post_id"])
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])
    # Serves both the badge (unread count) and the default list ordering.
    op.create_index(
        "ix_notifications_user_unread",
        "notifications",
        ["user_id", "created_at"],
        postgresql_where=sa.text("read_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_user_unread", table_name="notifications")
    op.drop_index("ix_notifications_created_at", table_name="notifications")
    op.drop_index("ix_notifications_post_id", table_name="notifications")
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_post_bookmarks_user_id", table_name="post_bookmarks")
    op.drop_index("ix_post_bookmarks_post_id", table_name="post_bookmarks")
    op.drop_table("post_bookmarks")
    postgresql.ENUM(name="notification_kind").drop(op.get_bind(), checkfirst=True)
