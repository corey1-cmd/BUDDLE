"""persona model registry

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-17 12:30:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


backend_kind_enum = postgresql.ENUM(
    "stub", "local_hf", "vllm_endpoint", "ondevice_webllm",
    name="persona_backend_kind", create_type=False,
)
model_status_enum = postgresql.ENUM(
    "draft", "staging", "active", "retired",
    name="persona_model_status", create_type=False,
)


def upgrade() -> None:
    backend_kind_enum.create(op.get_bind(), checkfirst=True)
    model_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "persona_models",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("template_key", sa.String(64), nullable=False, unique=True),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version", sa.String(32), nullable=False, server_default="0.1.0"),
        sa.Column("backend_kind", backend_kind_enum, nullable=False, server_default="stub"),
        sa.Column("backend_config", postgresql.JSONB(), nullable=True),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("status", model_status_enum, nullable=False, server_default="draft"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_persona_models_status", "persona_models", ["status"])

    # Seed the four built-in stub models so existing personas can FK to them.
    op.execute("""
        INSERT INTO persona_models
          (template_key, display_name, description, version,
           backend_kind, status, is_default, system_prompt)
        VALUES
          ('poet',     '시인',     '시적이고 감성적인 표현으로 글을 재해석합니다.',
           '0.1.0', 'stub'::persona_backend_kind, 'active'::persona_model_status, true,
           '당신은 시적인 감수성을 가진 페르소나입니다. 사용자의 글을 시적으로 재해석하세요.'),
          ('analyst',  '분석가',   '논리적이고 분석적으로 사실 위주로 정리합니다.',
           '0.1.0', 'stub'::persona_backend_kind, 'active'::persona_model_status, true,
           '당신은 분석가 페르소나입니다. 사실과 논리에 집중해 정리하세요.'),
          ('friend',   '친구',     '편안하고 친근한 대화체로 풀어줍니다.',
           '0.1.0', 'stub'::persona_backend_kind, 'active'::persona_model_status, true,
           '당신은 친구 페르소나입니다. 따뜻하고 친근하게 응답하세요.'),
          ('critic',   '비평가',   '날카로운 시선으로 한계와 함의를 짚어줍니다.',
           '0.1.0', 'stub'::persona_backend_kind, 'active'::persona_model_status, true,
           '당신은 비평가 페르소나입니다. 한계·함의·반론을 짚으세요.')
        ON CONFLICT (template_key) DO NOTHING
    """)

    # Rename personas.strategy_template -> personas.model_key
    op.alter_column("personas", "strategy_template", new_column_name="model_key")

    # Add FK to persona_models(template_key). RESTRICT delete (retire instead).
    op.create_foreign_key(
        constraint_name="fk_personas_model_key_persona_models",
        source_table="personas",
        referent_table="persona_models",
        local_cols=["model_key"],
        remote_cols=["template_key"],
        ondelete="RESTRICT",
        onupdate="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_personas_model_key_persona_models", "personas", type_="foreignkey"
    )
    op.alter_column("personas", "model_key", new_column_name="strategy_template")
    op.drop_index("idx_persona_models_status", table_name="persona_models")
    op.drop_table("persona_models")
    model_status_enum.drop(op.get_bind(), checkfirst=True)
    backend_kind_enum.drop(op.get_bind(), checkfirst=True)
