"""Authentication service — signup, login (with lockout), refresh (rotation), logout."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from buddle.config import get_settings
from buddle.core.exceptions import (
    EmailAlreadyExists,
    InvalidCredentials,
    Unauthorized,
)
from buddle.core.logging import get_logger
from buddle.core.types import RedisClient
from buddle.db.models.user import User
from buddle.schemas.auth import (
    LoginRequest,
    SignupRequest,
    SignupResponse,
    TokenPair,
)
from buddle.security.account_lockout import (
    clear_failures,
    is_locked,
    record_failure,
)
from buddle.security.jwt import (
    RefreshOutcome,
    create_access_token,
    create_refresh_token,
    decode_token,
    register_refresh_family,
    revoke_refresh_family,
    validate_and_rotate_family,
)
from buddle.security.password import hash_password, verify_dummy, verify_password
from buddle.services import security_event_service as sec

log = get_logger(__name__)


async def signup(db: AsyncSession, payload: SignupRequest) -> SignupResponse:
    """Create a new user account."""
    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise EmailAlreadyExists() from e
    await db.refresh(user)
    return SignupResponse(user_id=user.id, email=user.email, tier=user.tier)


async def login(
    db: AsyncSession,
    redis_client: RedisClient,
    payload: LoginRequest,
    *,
    ip: str | None = None,
) -> TokenPair:
    """Verify credentials and issue an access+refresh token pair.

    Defenses:
      - Layer 3 account lockout: too many consecutive failures locks the
        account for a cooldown, defeating IP-rotating credential stuffing.
      - Constant-time: a missing user still runs a dummy argon2 verification so
        response time doesn't reveal whether the email is registered.
      - Audit: failures, lockouts, and successes are recorded.
    """
    # Layer 3: per-account lockout (keyed by email; applies pre-auth).
    if await is_locked(redis_client, payload.email):
        await sec.record(sec.ACCOUNT_LOCKED, severity="warning", email=payload.email, ip=ip)
        raise InvalidCredentials("Account temporarily locked. Try again later.")

    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if user is None:
        verify_dummy()  # equalize timing for non-existent users
        await record_failure(redis_client, payload.email)
        await sec.record(
            sec.LOGIN_FAILED,
            severity="warning",
            email=payload.email,
            ip=ip,
            extra={"reason": "no_user"},
        )
        raise InvalidCredentials()

    if not verify_password(payload.password, user.password_hash):
        await record_failure(redis_client, payload.email)
        await sec.record(
            sec.LOGIN_FAILED,
            severity="warning",
            user_id=user.id,
            email=payload.email,
            ip=ip,
            extra={"reason": "bad_password"},
        )
        raise InvalidCredentials()

    if not user.is_active:
        raise InvalidCredentials("Account is inactive.")

    await clear_failures(redis_client, payload.email)
    await sec.record(sec.LOGIN_SUCCEEDED, user_id=user.id, email=payload.email, ip=ip)
    return await _issue_token_pair(redis_client, user.id)


async def refresh_access_token(redis_client: RedisClient, refresh_token: str) -> TokenPair:
    """Validate a refresh token, rotate it, and issue a new token pair.

    Implements refresh-token rotation with reuse detection: each refresh yields
    a NEW refresh token in the same family; replaying a rotated token revokes
    the whole family (theft response). Returns a full TokenPair because the
    refresh token itself changes on every call.
    """
    claims = decode_token(refresh_token)
    if claims.get("type") != "refresh":
        raise Unauthorized("Wrong token type. Use a refresh token.")

    jti = claims.get("jti")
    sub = claims.get("sub")
    fid = claims.get("fid")
    if not jti or not sub or not fid:
        raise Unauthorized("Refresh token is malformed.")

    outcome, new_jti = await validate_and_rotate_family(
        redis_client, family_id=fid, presented_jti=jti, expected_user_id=sub
    )

    if outcome == RefreshOutcome.REUSE_DETECTED:
        log.warning("auth.refresh_reuse_detected", family_id=fid, user_id=sub)
        await sec.record(
            sec.REFRESH_REUSE,
            severity="critical",
            user_id=sub,
            extra={"family_id": fid},
        )
        raise Unauthorized("Refresh token reuse detected; session revoked.")
    if outcome != RefreshOutcome.VALID or new_jti is None:
        raise Unauthorized("Refresh token is revoked or expired.")

    settings = get_settings()
    user_uuid = uuid.UUID(sub)
    access = create_access_token(user_uuid)
    # Mint the rotated refresh token carrying the family's NEW current jti.
    refresh, _, _ = _mint_refresh_with_jti(user_uuid, family_id=fid, jti=new_jti)
    return TokenPair(
        access_token=access,
        refresh_token=refresh,
        expires_in=int(timedelta(minutes=settings.jwt_access_expire_min).total_seconds()),
    )


async def logout(redis_client: RedisClient, refresh_token: str) -> None:
    """Revoke the token's entire family. Idempotent."""
    try:
        claims = decode_token(refresh_token)
    except Unauthorized:
        return
    fid = claims.get("fid")
    if fid:
        await revoke_refresh_family(redis_client, fid)


async def _issue_token_pair(redis_client: RedisClient, user_id: uuid.UUID) -> TokenPair:
    settings = get_settings()
    access = create_access_token(user_id)
    refresh, jti, fid = create_refresh_token(user_id)
    await register_refresh_family(redis_client, family_id=fid, jti=jti, user_id=user_id)
    return TokenPair(
        access_token=access,
        refresh_token=refresh,
        expires_in=int(timedelta(minutes=settings.jwt_access_expire_min).total_seconds()),
    )


def _mint_refresh_with_jti(user_id: uuid.UUID, *, family_id: str, jti: str) -> tuple[str, str, str]:
    """Encode a refresh token carrying a specific (family_id, jti).

    Used during rotation, where the new current JTI was already chosen by the
    family-rotation step and registered in Redis.
    """
    from datetime import UTC, datetime

    from buddle.security.jwt import _encode  # internal reuse

    settings = get_settings()
    now = datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "type": "refresh",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=settings.jwt_refresh_expire_days)).timestamp()),
        "jti": jti,
        "fid": family_id,
    }
    return _encode(claims), jti, family_id
