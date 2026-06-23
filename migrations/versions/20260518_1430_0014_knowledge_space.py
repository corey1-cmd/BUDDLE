"""knowledge space (layer B): units, edges, pools, refs, audits

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-18 14:30:00

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_units",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_post_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("persona_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gist", sa.Text(), nullable=False),
        sa.Column("language", sa.String(8), nullable=False, server_default="ko"),
        sa.Column("topic_tags", sa.Text(), nullable=False, server_default=""),
        sa.Column("embedding", Vector(768), nullable=True),
        sa.Column("visibility", sa.String(16), nullable=False, server_default="public"),
        sa.Column("retention_score", sa.REAL(), nullable=False, server_default="0"),
        sa.Column("integrity_sig", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["source_post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["persona_id"], ["personas.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_knowledge_units_source_post_id", "knowledge_units", ["source_post_id"])
    op.create_index("ix_knowledge_units_persona_id", "knowledge_units", ["persona_id"])

    op.create_table(
        "topic_edges",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("topic_a", sa.String(64), nullable=False),
        sa.Column("topic_b", sa.String(64), nullable=False),
        sa.Column("weight", sa.REAL(), nullable=False, server_default="0"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("topic_a", "topic_b", name="uq_topic_edge_pair"),
    )
    op.create_index("ix_topic_edges_topic_a", "topic_edges", ["topic_a"])
    op.create_index("ix_topic_edges_topic_b", "topic_edges", ["topic_b"])

    op.create_table(
        "conversation_pools",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("topic", sa.String(64), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("freshness", sa.REAL(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_served_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_conversation_pools_topic", "conversation_pools", ["topic"])

    op.create_table(
        "pool_units",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("pool_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("membership_score", sa.REAL(), nullable=False, server_default="0"),
    )
    op.create_index("ix_pool_units_pool_id", "pool_units", ["pool_id"])
    op.create_index("ix_pool_units_unit_id", "pool_units", ["unit_id"])

    op.create_table(
        "persona_context_refs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("persona_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pool_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relevance", sa.REAL(), nullable=False, server_default="0"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_persona_context_refs_persona_id", "persona_context_refs", ["persona_id"])

    op.create_table(
        "knowledge_audits",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("actor_ai", sa.String(16), nullable=False),
        sa.Column("action", sa.String(48), nullable=False),
        sa.Column("target_type", sa.String(24), nullable=False),
        sa.Column("target_id", sa.String(64), nullable=True),
        sa.Column("verdict", sa.String(24), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("knowledge_audits")
    op.drop_index("ix_persona_context_refs_persona_id", table_name="persona_context_refs")
    op.drop_table("persona_context_refs")
    op.drop_index("ix_pool_units_unit_id", table_name="pool_units")
    op.drop_index("ix_pool_units_pool_id", table_name="pool_units")
    op.drop_table("pool_units")
    op.drop_index("ix_conversation_pools_topic", table_name="conversation_pools")
    op.drop_table("conversation_pools")
    op.drop_index("ix_topic_edges_topic_b", table_name="topic_edges")
    op.drop_index("ix_topic_edges_topic_a", table_name="topic_edges")
    op.drop_table("topic_edges")
    op.drop_index("ix_knowledge_units_persona_id", table_name="knowledge_units")
    op.drop_index("ix_knowledge_units_source_post_id", table_name="knowledge_units")
    op.drop_table("knowledge_units")
