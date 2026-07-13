"""AdminUserRead 직렬화 — 예약 TLD 이메일도 목록에서 500 나지 않아야 한다."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from buddle.schemas.admin import AdminUserRead


def test_admin_user_read_allows_reserved_tld_email():
    # '@buddle.local' 은 EmailStr 이 거부하는 예약 TLD — 출력 스키마는 str 라
    # 이미 저장된 계정을 그대로 표시할 수 있어야 한다(목록 500 회귀 방지).
    m = AdminUserRead(
        id=uuid.uuid4(),
        email="admin@buddle.local",
        is_admin=True,
        is_super_admin=False,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    assert m.email == "admin@buddle.local"
    assert m.is_admin is True and m.is_super_admin is False
