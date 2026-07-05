"""User routes — /v1/users/me."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from buddle.api.deps import DB, CurrentUser, Redis
from buddle.schemas.user import AccountDeleteRequest, UserRead, UserUpdate
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


@router.delete(
    "/me",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Permanently delete my account (Google Play requirement)",
)
async def delete_me(
    payload: AccountDeleteRequest,
    user: CurrentUser,
    db: DB,
    redis: Redis,
) -> Response:
    """Delete the account + personal data after password confirmation.

    Cascades remove personas/sessions/likes/bookmarks/notifications; public
    posts and comments are de-identified (author link set NULL). All refresh
    tokens are revoked so any live session ends immediately.
    """
    await user_service.delete_account(db, redis, user, password=payload.password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
