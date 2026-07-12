"""super admin flag on users

Revision ID: 0025
Revises: 0024
Create Date: 2026-07-11 13:00:00

슈퍼 관리자(is_super_admin) 컬럼 추가 — 다른 사용자에게 관리자 권한을 부여/회수할
수 있는 상위 권한. IF NOT EXISTS 로 멱등하게 처리해, 라이브에서 컬럼을 먼저
추가해 둔 경우에도 배포 시 마이그레이션이 충돌 없이 통과한다.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_super_admin "
        "boolean NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS is_super_admin")
