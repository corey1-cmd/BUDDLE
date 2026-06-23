"""Seed development data.

Idempotent: safe to re-run. Inserts:
  - 1 admin user                (admin@buddle.local / Admin123!Admin)
  - 2 regular users             (alice@buddle.local, bob@buddle.local)
  - 20 baseline tags
  - 1 persona per regular user, each with a few interest tags

Persona model rows (poet/analyst/friend/critic) are already inserted by
migration 0002, so this script only references them.

Usage (locally):
    uv run python scripts/seed_dev_data.py

Inside the docker-compose api container:
    docker compose exec api python scripts/seed_dev_data.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Allow `python scripts/seed_dev_data.py` directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import select

from buddle.db.models.enums import UserTier
from buddle.db.models.persona import Persona
from buddle.db.models.tag import PersonaInterestTag, Tag
from buddle.db.models.user import User
from buddle.db.session import AsyncSessionLocal, engine
from buddle.security.password import hash_password

ADMIN_EMAIL = "admin@buddle.local"
ADMIN_PASSWORD = "Admin123!Admin"

USERS = [
    ("alice@buddle.local", "Alice123!Alice", "alice", "poet",
     ["외로움", "글쓰기", "음악", "산책"]),
    ("bob@buddle.local", "Bob12345!Bob", "bob_analyst", "analyst",
     ["기술", "독서", "여행", "커피"]),
]

TAGS = [
    "외로움", "글쓰기", "음악", "산책", "기술", "독서", "여행", "커피",
    "음식", "운동", "영화", "사진", "게임", "예술", "공부", "일상",
    "친구", "가족", "감정", "취미",
]


async def _get_or_create_user(
    session,  # type: ignore[no-untyped-def]
    *,
    email: str,
    password: str,
    is_admin: bool,
    tier: UserTier,
) -> User:
    existing = (
        await session.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if existing:
        return existing
    user = User(
        email=email,
        password_hash=hash_password(password),
        is_admin=is_admin,
        tier=tier,
    )
    session.add(user)
    await session.flush()
    return user


async def _get_or_create_tag(session, name: str) -> Tag:  # type: ignore[no-untyped-def]
    existing = (
        await session.execute(select(Tag).where(Tag.name == name))
    ).scalar_one_or_none()
    if existing:
        return existing
    tag = Tag(name=name)
    session.add(tag)
    await session.flush()
    return tag


async def _ensure_persona(  # type: ignore[no-untyped-def]
    session,
    *,
    user: User,
    name: str,
    model_key: str,
    interest_tag_names: list[str],
) -> Persona:
    existing = (
        await session.execute(
            select(Persona).where(Persona.user_id == user.id, Persona.name == name)
        )
    ).scalar_one_or_none()
    if existing:
        return existing

    persona = Persona(user_id=user.id, name=name, model_key=model_key)
    session.add(persona)
    await session.flush()

    for tag_name in interest_tag_names:
        tag = await _get_or_create_tag(session, tag_name)
        session.add(PersonaInterestTag(persona_id=persona.id, tag_id=tag.id))

    return persona


async def main() -> None:
    print("seeding dev data...")
    async with AsyncSessionLocal() as session:
        # Admin
        admin = await _get_or_create_user(
            session,
            email=ADMIN_EMAIL,
            password=ADMIN_PASSWORD,
            is_admin=True,
            tier=UserTier.PRO,
        )
        print(f"  admin: {admin.email} (id={admin.id})")

        # Baseline tags
        for name in TAGS:
            await _get_or_create_tag(session, name)
        print(f"  tags : {len(TAGS)} baseline names ensured")

        # Regular users + personas
        for email, pw, persona_name, model_key, interest_names in USERS:
            user = await _get_or_create_user(
                session,
                email=email,
                password=pw,
                is_admin=False,
                tier=UserTier.FREE,
            )
            persona = await _ensure_persona(
                session,
                user=user,
                name=persona_name,
                model_key=model_key,
                interest_tag_names=interest_names,
            )
            print(
                f"  user : {user.email} (id={user.id}) "
                f"-> persona '{persona.name}' [{persona.model_key}]"
            )

        await session.commit()
    await engine.dispose()
    print("done.")


if __name__ == "__main__":
    asyncio.run(main())
