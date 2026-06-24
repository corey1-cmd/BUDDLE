"""관리자 계정 승격 스크립트.

Usage:
    docker compose exec api python scripts/make_admin.py 이메일@example.com

이미 관리자인 경우 아무 변화 없이 확인 메시지만 출력합니다.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import select

from buddle.db.models.user import User
from buddle.db.session import AsyncSessionLocal, engine


async def main(email: str) -> None:
    async with AsyncSessionLocal() as session:
        user = (
            await session.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()

        if user is None:
            print(f"오류: '{email}' 계정을 찾을 수 없습니다. 먼저 회원가입을 완료하세요.")
            sys.exit(1)

        if user.is_admin:
            print(f"이미 관리자입니다: {email} (id={user.id})")
        else:
            user.is_admin = True
            await session.commit()
            print(f"관리자 권한 부여 완료: {email} (id={user.id})")

    await engine.dispose()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("사용법: python scripts/make_admin.py 이메일@example.com")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
