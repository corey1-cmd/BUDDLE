"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-17 12:00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

# revision identifiers
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ────────────── ENUM 정의 ──────────────
user_tier_enum = postgresql.ENUM(
    "free", "plus", "pro",
    name="user_tier", create_type=False,
)
post_visibility_enum = postgresql.ENUM(
    "public", "private",
    name="post_visibility", create_type=False,
)
message_role_enum = postgresql.ENUM(
    "user", "persona", "mediator_bundle",
    name="message_role", create_type=False,
)
alert_status_enum = postgresql.ENUM(
    "open", "reviewing", "resolved",
    name="alert_status", create_type=False,
)
authority_state_enum = postgresql.ENUM(
    "normal", "tech_elevated",
    name="authority_state", create_type=False,
)
transformation_type_enum = postgresql.ENUM(
    "weight_update", "content_modify", "delete", "inject",
    name="transformation_type", create_type=False,
)
ai_role_enum = postgresql.ENUM(
    "persona", "mediator", "leukocyte", "technician", "central_manager",
    name="ai_role", create_type=False,
)


def upgrade() -> None:
    # ───── 확장 ─────
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "citext"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "vector"')

    # ───── ENUM 생성 ─────
    user_tier_enum.create(op.get_bind(), checkfirst=True)
    post_visibility_enum.create(op.get_bind(), checkfirst=True)
    message_role_enum.create(op.get_bind(), checkfirst=True)
    alert_status_enum.create(op.get_bind(), checkfirst=True)
    authority_state_enum.create(op.get_bind(), checkfirst=True)
    transformation_type_enum.create(op.get_bind(), checkfirst=True)
    ai_role_enum.create(op.get_bind(), checkfirst=True)

    # ───── users ─────
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", postgresql.CITEXT(), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("tier", user_tier_enum, nullable=False, server_default="free"),
        sa.Column("persona_quota", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_users_email", "users", ["email"])

    # ───── personas ─────
    op.create_table(
        "personas",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("strategy_template", sa.String(64), nullable=False),
        sa.Column("context_emb", Vector(768), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_personas_user_id", "personas", ["user_id"])
    # ivfflat은 데이터 들어간 후 ANALYZE 필요. 베타 시점에 생성하는 것이 안전.
    # 여기서는 정의만 남기고 활성 인덱스는 추후 마이그레이션으로.

    # ───── messages ─────
    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("persona_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("personas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", message_role_enum, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("bundle_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_messages_persona_created",
                    "messages", ["persona_id", sa.text("created_at DESC")])

    # ───── posts ─────
    op.create_table(
        "posts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_persona_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("personas.id", ondelete="SET NULL"), nullable=True),
        sa.Column("content_raw", sa.Text(), nullable=False),
        sa.Column("content_transformed", sa.Text(), nullable=False),
        sa.Column("visibility", post_visibility_enum, nullable=False),
        sa.Column("content_emb", Vector(768), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_posts_visibility_created",
                    "posts", ["visibility", sa.text("created_at DESC")])

    # ───── tags ─────
    op.create_table(
        "tags",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "post_tags",
        sa.Column("post_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tag_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_index("idx_post_tags_tag", "post_tags", ["tag_id"])

    op.create_table(
        "persona_interest_tags",
        sa.Column("persona_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("personas.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tag_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("weight", sa.REAL(), nullable=False, server_default="1.0"),
    )

    # ───── importance ─────
    op.create_table(
        "importance_scores",
        sa.Column("post_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("raw_score", sa.REAL(), nullable=False, server_default="0"),
        sa.Column("normalized", sa.REAL(), nullable=False, server_default="0"),
        sa.Column("last_updated", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "importance_contributions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("post_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("posts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("delta", sa.REAL(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_imp_contrib_post", "importance_contributions", ["post_id"])

    # ───── distributions ─────
    op.create_table(
        "distributions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_post_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("posts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_persona_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("personas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relevance_score", sa.REAL(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_dist_target_delivered",
                    "distributions", ["target_persona_id", sa.text("delivered_at DESC")])

    # ───── ethics_alerts ─────
    op.create_table(
        "ethics_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_type", sa.String(16), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", alert_status_enum, nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_ethics_status_created",
                    "ethics_alerts", ["status", sa.text("created_at DESC")])

    # ───── security_events ─────
    op.create_table(
        "security_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("status", alert_status_enum, nullable=False, server_default="open"),
        sa.Column("detail", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_security_status_created",
                    "security_events", ["status", sa.text("created_at DESC")])

    # ───── authority_tokens ─────
    op.create_table(
        "authority_tokens",
        sa.Column("entity_type", ai_role_enum, nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("balance", sa.REAL(), nullable=False, server_default="0"),
        sa.Column("last_updated", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("entity_type", "entity_id"),
    )

    # ───── system_authority_state (singleton) ─────
    op.create_table(
        "system_authority_state",
        sa.Column("id", sa.SmallInteger(), primary_key=True, server_default="1"),
        sa.Column("state", authority_state_enum, nullable=False, server_default="normal"),
        sa.Column("changed_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_authority_singleton"),
    )

    # ───── transformation_logs ─────
    op.create_table(
        "transformation_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_ai", ai_role_enum, nullable=False),
        sa.Column("source_instance_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_data_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_data_type", sa.String(32), nullable=False),
        sa.Column("magnitude", sa.REAL(), nullable=False),
        sa.Column("transformation_type", transformation_type_enum, nullable=False),
        sa.Column("justification_signature", sa.LargeBinary(), nullable=True),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("verification_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_trans_target",
                    "transformation_logs", ["target_data_id", "target_data_type"])
    op.create_index("idx_trans_source_created",
                    "transformation_logs", ["source_ai", sa.text("created_at DESC")])

    # 권한 상태 singleton 초기 row 삽입
    op.execute("INSERT INTO system_authority_state (id, state) VALUES (1, 'normal') "
               "ON CONFLICT (id) DO NOTHING")


def downgrade() -> None:
    op.drop_index("idx_trans_source_created", table_name="transformation_logs")
    op.drop_index("idx_trans_target", table_name="transformation_logs")
    op.drop_table("transformation_logs")
    op.drop_table("system_authority_state")
    op.drop_table("authority_tokens")
    op.drop_index("idx_security_status_created", table_name="security_events")
    op.drop_table("security_events")
    op.drop_index("idx_ethics_status_created", table_name="ethics_alerts")
    op.drop_table("ethics_alerts")
    op.drop_index("idx_dist_target_delivered", table_name="distributions")
    op.drop_table("distributions")
    op.drop_index("idx_imp_contrib_post", table_name="importance_contributions")
    op.drop_table("importance_contributions")
    op.drop_table("importance_scores")
    op.drop_table("persona_interest_tags")
    op.drop_index("idx_post_tags_tag", table_name="post_tags")
    op.drop_table("post_tags")
    op.drop_table("tags")
    op.drop_index("idx_posts_visibility_created", table_name="posts")
    op.drop_table("posts")
    op.drop_index("idx_messages_persona_created", table_name="messages")
    op.drop_table("messages")
    op.drop_index("idx_personas_user_id", table_name="personas")
    op.drop_table("personas")
    op.drop_index("idx_users_email", table_name="users")
    op.drop_table("users")

    ai_role_enum.drop(op.get_bind(), checkfirst=True)
    transformation_type_enum.drop(op.get_bind(), checkfirst=True)
    authority_state_enum.drop(op.get_bind(), checkfirst=True)
    alert_status_enum.drop(op.get_bind(), checkfirst=True)
    message_role_enum.drop(op.get_bind(), checkfirst=True)
    post_visibility_enum.drop(op.get_bind(), checkfirst=True)
    user_tier_enum.drop(op.get_bind(), checkfirst=True)
