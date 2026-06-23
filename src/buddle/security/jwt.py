"""JWT access/refresh token handling.

Access tokens are stateless JWTs. Refresh tokens are JWTs whose JTI is also
stored in Redis so they can be revoked (logout, password change, etc.).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt

from buddle.config import get_settings
from buddle.core.exceptions import TokenExpired, Unauthorized
from buddle.core.types import RedisClient

TokenType = Literal["access", "refresh"]

# Redis key for storing valid refresh token JTIs.
# Value is the user_id; presence = valid; absence = revoked/expired.
_REFRESH_KEY_PREFIX = "buddle:refresh:"


def _now() -> datetime:
    return datetime.now(UTC)


def _build_claims(
    *,
    sub: str,
    token_type: TokenType,
    expires_in: timedelta,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = _now()
    claims: dict[str, Any] = {
        "sub": sub,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_in).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    if extra:
        claims.update(extra)
    return claims


def _encode(claims: dict[str, Any]) -> str:
    settings = get_settings()
    return jwt.encode(
        claims,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def decode_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT. Raises Unauthorized / TokenExpired on failure.

    Hardening:
      * Algorithm is pinned to the configured one (no ``alg=none`` / RS↔HS
        confusion — PyJWT rejects any token whose header alg isn't listed).
      * Required claims are enforced so a token missing exp/iat/sub/type is
        rejected rather than silently treated as valid.
      * ``leeway=0`` — no clock-skew grace on expiry.
    """
    settings = get_settings()
    try:
        decoded: dict[str, Any] = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            leeway=0,
            options={
                "require": ["exp", "iat", "sub", "type"],
                "verify_exp": True,
                "verify_signature": True,
            },
        )
    except jwt.ExpiredSignatureError as e:
        raise TokenExpired() from e
    except jwt.InvalidTokenError as e:
        raise Unauthorized("Invalid token.") from e
    return decoded


def create_access_token(user_id: uuid.UUID | str, *, extra: dict[str, Any] | None = None) -> str:
    """Create a short-lived stateless access token."""
    settings = get_settings()
    claims = _build_claims(
        sub=str(user_id),
        token_type="access",
        expires_in=timedelta(minutes=settings.jwt_access_expire_min),
        extra=extra,
    )
    return _encode(claims)


def create_refresh_token(
    user_id: uuid.UUID | str, *, family_id: str | None = None
) -> tuple[str, str, str]:
    """Create a long-lived refresh token bound to a token family.

    Returns (token, jti, family_id). On initial login, omit family_id to mint a
    new family; on rotation, pass the existing family_id so the new token stays
    in the same family. The JTI must be registered as the family's current
    token (see register_refresh_family / rotate_refresh_family).
    """
    settings = get_settings()
    fid = family_id or str(uuid.uuid4())
    claims = _build_claims(
        sub=str(user_id),
        token_type="refresh",
        expires_in=timedelta(days=settings.jwt_refresh_expire_days),
        extra={"fid": fid},
    )
    return _encode(claims), claims["jti"], fid


# ── Redis-backed refresh token FAMILY lifecycle ────────────────────
#
# Rotation + reuse detection (RFC 9700 / OAuth 2.0 Security BCP):
#   family:{fid}          -> current_jti  (TTL = refresh lifetime)
#   family_user:{fid}     -> user_id      (TTL = refresh lifetime)
#   family_grace:{fid}:{jti} -> "1"       (short TTL = grace period)
#   family_revoked:{fid}  -> "1"          (TTL = refresh lifetime)
#
# A refresh presents (fid, jti). It is accepted if the family is not revoked
# AND (jti == current_jti OR jti is within the grace window). Any other jti
# for a live family means a rotated token was replayed -> theft -> revoke the
# whole family.


def _fam_current_key(fid: str) -> str:
    return f"buddle:family:{fid}"


def _fam_user_key(fid: str) -> str:
    return f"buddle:family_user:{fid}"


def _fam_grace_key(fid: str, jti: str) -> str:
    return f"buddle:family_grace:{fid}:{jti}"


def _fam_revoked_key(fid: str) -> str:
    return f"buddle:family_revoked:{fid}"


async def register_refresh_family(
    redis_client: RedisClient, *, family_id: str, jti: str, user_id: uuid.UUID | str
) -> None:
    """Initialize a new token family with its first current JTI."""
    settings = get_settings()
    ttl = int(timedelta(days=settings.jwt_refresh_expire_days).total_seconds())
    await redis_client.set(_fam_current_key(family_id), jti, ex=ttl)
    await redis_client.set(_fam_user_key(family_id), str(user_id), ex=ttl)


class RefreshOutcome:
    """Result of validating a presented refresh token."""

    VALID = "valid"
    REUSE_DETECTED = "reuse_detected"
    REVOKED = "revoked"
    UNKNOWN = "unknown"  # family missing/expired or user mismatch


async def validate_and_rotate_family(
    redis_client: RedisClient,
    *,
    family_id: str,
    presented_jti: str,
    expected_user_id: str,
) -> tuple[str, str | None]:
    """Validate a presented refresh token against its family and rotate it.

    Returns (outcome, new_jti). On VALID, new_jti is the freshly-issued current
    JTI (the caller mints the token with it). On REUSE_DETECTED the family is
    revoked here. On REVOKED/UNKNOWN the caller rejects.
    """
    if await redis_client.get(_fam_revoked_key(family_id)):
        return RefreshOutcome.REVOKED, None

    stored_user = await redis_client.get(_fam_user_key(family_id))
    current_jti = await redis_client.get(_fam_current_key(family_id))
    if not stored_user or not current_jti:
        return RefreshOutcome.UNKNOWN, None
    if stored_user != expected_user_id:
        return RefreshOutcome.UNKNOWN, None

    accepted = presented_jti == current_jti
    if not accepted:
        # Maybe it's the immediately-previous token still in its grace window.
        if await redis_client.get(_fam_grace_key(family_id, presented_jti)):
            accepted = True
        else:
            # A non-current, non-grace JTI for a live family => replay/theft.
            await revoke_refresh_family(redis_client, family_id)
            return RefreshOutcome.REUSE_DETECTED, None

    # Rotate: issue a new current JTI; keep the old one valid briefly (grace).
    settings = get_settings()
    new_jti = str(uuid.uuid4())
    ttl = int(timedelta(days=settings.jwt_refresh_expire_days).total_seconds())
    grace = settings.refresh_grace_period_seconds
    if grace > 0:
        await redis_client.set(_fam_grace_key(family_id, str(current_jti)), "1", ex=grace)
    await redis_client.set(_fam_current_key(family_id), new_jti, ex=ttl)
    return RefreshOutcome.VALID, new_jti


async def revoke_refresh_family(redis_client: RedisClient, family_id: str) -> None:
    """Revoke an entire token family (logout, theft, password change)."""
    settings = get_settings()
    ttl = int(timedelta(days=settings.jwt_refresh_expire_days).total_seconds())
    await redis_client.set(_fam_revoked_key(family_id), "1", ex=ttl)
    await redis_client.delete(_fam_current_key(family_id))


async def revoke_all_user_families(redis_client: RedisClient, user_id: uuid.UUID | str) -> int:
    """Best-effort: revoke every family belonging to a user.

    Used on password change / admin-forced logout. Returns count revoked.
    """
    pattern = "buddle:family_user:*"
    revoked = 0
    async for key in redis_client.scan_iter(match=pattern):
        if await redis_client.get(key) == str(user_id):
            fid = key.split("buddle:family_user:", 1)[-1]
            await revoke_refresh_family(redis_client, fid)
            revoked += 1
    return revoked
