"""User routes — /v1/users/me."""

from __future__ import annotations

from fastapi import APIRouter

from buddle.api.deps import DB, CurrentUser, Redis
from buddle.schemas.user import UserRead, UserUpdate
from buddle.services import user_service

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserRead, summary="Get current user")
async def read_me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)


@router.patch("/me", response_model=UserRead, summary="Update current user")
async def update_me(
    payload: UserUpdate,
    user: CurrentUser,
    db: DB,
    redis: Redis,
) -> UserRead:
    updated = await user_service.update_me(db, redis, user, payload)
    return UserRead.model_validate(updated)
