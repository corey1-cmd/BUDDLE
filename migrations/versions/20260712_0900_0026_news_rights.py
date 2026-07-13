"""news_items.rights — 문서 단위 공공누리/권리 등급

Revision ID: 0026
Revises: 0025
Create Date: 2026-07-12 09:00:00

공공누리 유형에 따라 원문 변경 가능 여부가 다르므로(3유형=변경 금지), 가공
단계(번역·요약·자연화)가 참조할 등급을 문서 단위로 영속한다. IF NOT EXISTS 로
멱등 처리(라이브 선반영 대비).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE news_items ADD COLUMN IF NOT EXISTS rights "
        "varchar(20) NOT NULL DEFAULT 'default_deny'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE news_items DROP COLUMN IF EXISTS rights")
