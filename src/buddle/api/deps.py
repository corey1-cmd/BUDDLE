"""Shared FastAPI dependencies."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Header, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from buddle.core.exceptions import Forbidden, Unauthorized
from buddle.core.types import RedisClient
from buddle.db.models.user import User
from buddle.db.session import AsyncSessionLocal
from buddle.security.jwt import decode_token

if TYPE_CHECKING:
    from buddle.db.models.ai_agent import AIAgent

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/v1/auth/login", auto_error=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    """Per-request async DB session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


def get_redis(request: Request) -> RedisClient:
    """Redis client attached to app.state at lifespan startup."""
    return request.app.state.redis


async def get_current_user(
    db: Annotated[AsyncSession, Depends(get_db)],
    token: Annotated[str | None, Depends(oauth2_scheme)],
) -> User:
    """Resolve the current user from an access token."""
    if not token:
        raise Unauthorized()

    claims = decode_token(token)
    if claims.get("type") != "access":
        raise Unauthorized("Wrong token type. Use an access token.")

    sub = claims.get("sub")
    if not sub:
        raise Unauthorized("Token missing subject.")

    try:
        user_id = uuid.UUID(sub)
    except ValueError as e:
        raise Unauthorized("Token subject is not a valid user id.") from e

    user = await db.get(User, user_id)
    if not user or not user.is_active:
        raise Unauthorized("User is inactive or not found.")
    return user


async def get_current_admin(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Require admin scope."""
    if not user.is_admin:
        raise Forbidden("Admin privilege required.")
    return user


async def get_current_super_admin(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Require super-admin scope — the only role that can manage admins."""
    if not user.is_super_admin:
        raise Forbidden("Super-admin privilege required.")
    return user


# Convenience type aliases for route handlers
DB = Annotated[AsyncSession, Depends(get_db)]
Redis = Annotated[RedisClient, Depends(get_redis)]
CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentAdmin = Annotated[User, Depends(get_current_admin)]
CurrentSuperAdmin = Annotated[User, Depends(get_current_super_admin)]


async def get_current_agent(
    db: Annotated[AsyncSession, Depends(get_db)],
    x_agent_key: Annotated[str | None, Header()] = None,
) -> AIAgent:
    """Authenticate a registered AI agent via the X-Agent-Key header."""
    from buddle.services import agent_service

    if not x_agent_key:
        raise Unauthorized("Missing X-Agent-Key header.")
    agent: AIAgent = await agent_service.authenticate_agent(db, x_agent_key)
    return agent


CurrentAgent = Annotated["AIAgent", Depends(get_current_agent)]
