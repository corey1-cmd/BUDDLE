"""User self-service operations."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from buddle.core.exceptions import EmailAlreadyExists, InvalidCredentials, ValidationError
from buddle.core.types import RedisClient
from buddle.db.models.user import User
from buddle.schemas.user import UserUpdate
from buddle.security.jwt import revoke_all_user_families
from buddle.security.password import hash_password, verify_password


async def update_me(
    db: AsyncSession,
    redis_client: RedisClient,
    user: User,
    payload: UserUpdate,
) -> User:
    """Apply allowed self-updates. Password change revokes all refresh tokens."""
    changed = False
    password_changed = False

    if payload.email and payload.email.lower() != str(user.email).lower():
        user.email = payload.email
        changed = True

    if payload.new_password is not None:
        if not payload.current_password:
            raise ValidationError(
                "current_password is required to set a new password.",
                detail={"field": "current_password"},
            )
        if not verify_password(payload.current_password, user.password_hash):
            raise InvalidCredentials("Current password is incorrect.")
        user.password_hash = hash_password(payload.new_password)
        password_changed = True
        changed = True

    if not changed:
        return user

    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise EmailAlreadyExists() from e
    await db.refresh(user)

    # Password change forces all sessions to end.
    if password_changed:
        await revoke_all_user_families(redis_client, user.id)

    return user
