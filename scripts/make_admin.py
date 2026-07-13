"""관리자 계정 승격 스크립트.

Usage:
    # 지정 계정을 관리자로 승격 (기존 다른 관리자는 그대로 둔다)
    python scripts/make_admin.py 이메일@example.com

    # 지정 계정만 '유일한' 관리자로 만든다 (그 외 모든 관리자는 자동 해제)
    python scripts/make_admin.py --sole 이메일@example.com

이메일은 항상 명령행 인자로 받는다 — 특정 주소를 코드에 하드코딩하지 않는다.
--sole 은 관리자를 한 명으로 정리할 때 쓴다. 대상 계정이 존재하지 않으면
아무것도 바꾸지 않는다(관리자가 0명이 되는 사고 방지).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import select, update

from buddle.db.models.user import User
from buddle.db.session import AsyncSessionLocal, engine


async def main(email: str, *, sole: bool) -> None:
    async with AsyncSessionLocal() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()

        if user is None:
            # 대상이 없으면 아무것도 바꾸지 않는다 — --sole 이 다른 관리자를
            # 먼저 내려버려 관리자가 0명이 되는 상황을 막는다.
            print(f"오류: '{email}' 계정을 찾을 수 없습니다. 먼저 회원가입을 완료하세요.")
            sys.exit(1)

        if sole:
            # 대상 외 모든 계정의 관리자 권한을 해제한다(유일 관리자 보장).
            await session.execute(update(User).where(User.email != email).values(is_admin=False))
        user.is_admin = True
        await session.commit()

        admins = (
            (await session.execute(select(User.email).where(User.is_admin.is_(True))))
            .scalars()
            .all()
        )
        print(f"관리자 권한 부여 완료: {email} (id={user.id})")
        print(f"현재 관리자 {len(admins)}명: {', '.join(sorted(admins))}")

    await engine.dispose()


if __name__ == "__main__":
    argv = sys.argv[1:]
    sole_flag = "--sole" in argv
    positional = [a for a in argv if a != "--sole"]
    if len(positional) != 1:
        print("사용법: python scripts/make_admin.py [--sole] 이메일@example.com")
        sys.exit(1)
    asyncio.run(main(positional[0], sole=sole_flag))
