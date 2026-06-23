"""Per-account login lockout (defense-in-depth Layer 3).

IP-based rate limiting (Layers 1-2) is defeated by an attacker who rotates
source IPs while hammering a single account (credential stuffing). This layer
counts consecutive failed logins per ACCOUNT (keyed by email) and locks the
account for a cooldown once a threshold is crossed — independent of source IP.

Keyed by email rather than user_id so it also applies before we know whether
the user exists (and the email is normalized to avoid trivial bypass via
case). Counts live in Redis; if Redis is down this layer is simply absent
(the other layers still apply), matching the system's degrade-gracefully
posture for non-critical signals.
"""

from __future__ import annotations

from buddle.config import get_settings
from buddle.core.logging import get_logger
from buddle.core.types import RedisClient

log = get_logger(__name__)


def _norm(email: str) -> str:
    return email.strip().lower()


def _fail_key(email: str) -> str:
    return f"buddle:lockout:fail:{_norm(email)}"


def _lock_key(email: str) -> str:
    return f"buddle:lockout:locked:{_norm(email)}"


async def is_locked(redis_client: RedisClient | None, email: str) -> bool:
    if redis_client is None:
        return False
    try:
        return bool(await redis_client.get(_lock_key(email)))
    except Exception as e:  # degrade gracefully — other layers still apply
        log.warning("lockout.redis_error", op="is_locked", error=str(e))
        return False


async def record_failure(redis_client: RedisClient | None, email: str) -> None:
    """Increment the consecutive-failure counter; lock if threshold reached."""
    if redis_client is None:
        return
    settings = get_settings()
    try:
        key = _fail_key(email)
        count = await redis_client.incr(key)
        if count == 1:
            await redis_client.expire(key, settings.account_lockout_window_min * 60)
        if count >= settings.account_lockout_threshold:
            await redis_client.set(
                _lock_key(email),
                "1",
                ex=settings.account_lockout_duration_min * 60,
            )
            await redis_client.delete(key)
            log.warning("lockout.account_locked", email=_norm(email), failures=count)
    except Exception as e:
        log.warning("lockout.redis_error", op="record_failure", error=str(e))


async def clear_failures(redis_client: RedisClient | None, email: str) -> None:
    """Reset failures on successful login."""
    if redis_client is None:
        return
    try:
        await redis_client.delete(_fail_key(email))
    except Exception as e:
        log.warning("lockout.redis_error", op="clear_failures", error=str(e))
