"""Redis-backed sliding-window rate limiter.

Uses a sorted set per key, storing request timestamps (ms). On each call we
drop entries older than the window, count the rest, and reject if over the
limit. The whole operation is a single Lua script for atomicity.

Usage in a route:

    from buddle.core.ratelimit import RateLimit

    @router.post("/login", dependencies=[Depends(RateLimit("login", 10, 60))])
    async def login(...): ...

If Redis is unavailable the limiter fails OPEN (allows the request) and logs
a warning — availability is preferred over hard-blocking in a degraded state.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable

from fastapi import Request

from buddle.config import get_settings
from buddle.core.client_ip import resolve_client_ip
from buddle.core.exceptions import BuddleError
from buddle.core.logging import get_logger
from buddle.core.types import RedisClient

log = get_logger(__name__)

# KEYS[1] = bucket key
# ARGV[1] = now_ms, ARGV[2] = window_ms, ARGV[3] = limit, ARGV[4] = member
# returns 1 if allowed, 0 if rejected
_SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local count = redis.call('ZCARD', key)
if count >= limit then
  return 0
end
redis.call('ZADD', key, now, member)
redis.call('PEXPIRE', key, window)
return 1
"""


class RateLimited(BuddleError):
    code = "RATE_LIMITED"
    status_code = 429
    message = "Too many requests. Please slow down."


def _client_ip(request: Request) -> str:
    """Resolve the client IP for rate-limiting in a spoof-resistant way.

    Delegates to :func:`buddle.core.client_ip.resolve_client_ip`, which selects
    the configured strategy (socket / trusted-CIDR / fixed-hops). The leftmost
    X-Forwarded-For entry is attacker-controlled, so it is never trusted blindly.
    """
    settings = get_settings()
    peer = request.client.host if request.client else None
    return resolve_client_ip(
        peer=peer,
        xff=request.headers.get("x-forwarded-for"),
        mode=settings.trusted_proxy_mode,
        trusted_cidrs=settings.trusted_proxy_cidrs,
        hops=settings.trusted_proxy_hops,
    )


# ── Layer 2: process-local in-memory sliding-window backup ───────────────
#
# Works even when Redis is unavailable, bounding abuse against a SINGLE
# process (it can't see other replicas, but it stops one instance from being
# hammered with no ceiling). Independent of Redis, so a Redis outage doesn't
# remove ALL protection. Guarded by a lock for thread safety.

_local_lock = threading.Lock()
_local_buckets: dict[str, deque[float]] = defaultdict(deque)


def _local_allow(key: str, limit: int, window_s: float) -> bool:
    """Sliding-window check against the process-local bucket. Mutates state."""
    now = time.monotonic()
    with _local_lock:
        bucket = _local_buckets[key]
        cutoff = now - window_s
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        # Opportunistic cleanup to bound memory: drop empty buckets rarely.
        if len(_local_buckets) > 10000:
            _prune_local()
        return True


def _prune_local() -> None:
    """Remove empty buckets (called under lock)."""
    empty = [k for k, v in _local_buckets.items() if not v]
    for k in empty:
        del _local_buckets[k]


class RateLimit:
    """FastAPI dependency factory enforcing a sliding-window limit.

    Defense-in-depth:
      - Layer 1 (policy): `fail_closed=True` (default for auth) rejects when
        the Redis layer errors; `fail_closed=False` (general APIs) allows, for
        availability.
      - Layer 2 (local backup): a process-local in-memory limiter that applies
        regardless of Redis health, capping single-instance abuse.

    scope:       logical bucket name (e.g. 'login', 'post_create')
    limit:       max requests per window (Redis/distributed layer)
    window_s:    window length in seconds
    by:          'ip' (default) or 'user'
    fail_closed: on Redis error, reject (True) vs allow (False)
    local_limit: per-process backup ceiling (defaults to a multiple of limit)
    """

    def __init__(
        self,
        scope: str,
        limit: int,
        window_s: int,
        *,
        by: str = "ip",
        fail_closed: bool = False,
        local_limit: int | None = None,
    ):
        self.scope = scope
        self.limit = limit
        self.window_s = window_s
        self.window_ms = window_s * 1000
        self.by = by
        self.fail_closed = fail_closed
        # Backup ceiling: default to 2x the distributed limit so it only trips
        # when a single process is being pounded (a true outlier).
        self.local_limit = local_limit if local_limit is not None else max(limit * 2, limit + 1)

    async def __call__(self, request: Request) -> None:
        identity = self._identity(request)

        # Layer 2 first: always-on local backup (independent of Redis).
        settings = get_settings()
        if settings.ratelimit_local_backup_enabled:
            local_key = f"{self.scope}:{identity}"
            if not _local_allow(local_key, self.local_limit, float(self.window_s)):
                raise RateLimited(
                    detail={"scope": self.scope, "layer": "local", "limit": self.local_limit},
                )

        # Layer 1: distributed Redis sliding window with policy-based fail mode.
        redis: RedisClient | None = getattr(request.app.state, "redis", None)
        if redis is None:
            # No Redis configured at all: local backup already applied above.
            return

        key = f"buddle:rl:{self.scope}:{identity}"
        now_ms = int(time.time() * 1000)
        member = f"{now_ms}-{id(request)}"

        try:
            allowed = await redis.eval(
                _SLIDING_WINDOW_LUA,
                1,
                key,
                str(now_ms),
                str(self.window_ms),
                str(self.limit),
                member,
            )
        except Exception as e:
            if self.fail_closed:
                log.warning("ratelimit.redis_error.fail_closed", scope=self.scope, error=str(e))
                raise RateLimited(
                    detail={"scope": self.scope, "reason": "limiter_unavailable"},
                ) from e
            log.warning("ratelimit.redis_error.fail_open", scope=self.scope, error=str(e))
            return

        if int(allowed) == 0:
            raise RateLimited(
                detail={"scope": self.scope, "limit": self.limit},
            )

    def _identity(self, request: Request) -> str:
        if self.by == "user":
            uid = getattr(request.state, "user_id", None)
            if uid:
                return f"user:{uid}"
        return f"ip:{_client_ip(request)}"


# Convenience type for documentation
RateLimitDep = Callable[[Request], Awaitable[None]]
