"""Authentication routes — /v1/auth/{signup,login,refresh,logout}."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status

from buddle.api.deps import DB, CurrentUser, Redis
from buddle.core.ratelimit import RateLimit
from buddle.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    SignupRequest,
    SignupResponse,
    TokenPair,
)
from buddle.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/signup",
    response_model=SignupResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new account",
    dependencies=[Depends(RateLimit("signup", limit=5, window_s=60, fail_closed=True))],
)
async def signup(payload: SignupRequest, db: DB) -> SignupResponse:
    return await auth_service.signup(db, payload)


@router.post(
    "/login",
    response_model=TokenPair,
    summary="Exchange credentials for access+refresh tokens",
    dependencies=[Depends(RateLimit("login", limit=10, window_s=60, fail_closed=True))],
)
async def login(payload: LoginRequest, request: Request, db: DB, redis: Redis) -> TokenPair:
    ip = request.client.host if request.client else None
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        ip = fwd.split(",")[0].strip()
    return await auth_service.login(db, redis, payload, ip=ip)


@router.post(
    "/refresh",
    response_model=TokenPair,
    summary="Rotate refresh token and issue a new access+refresh pair",
    dependencies=[Depends(RateLimit("refresh", limit=30, window_s=60, fail_closed=True))],
)
async def refresh(payload: RefreshRequest, redis: Redis) -> TokenPair:
    return await auth_service.refresh_access_token(redis, payload.refresh_token)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a refresh token",
)
async def logout(
    payload: LogoutRequest,
    redis: Redis,
    _: CurrentUser,
) -> None:
    await auth_service.logout(redis, payload.refresh_token)
