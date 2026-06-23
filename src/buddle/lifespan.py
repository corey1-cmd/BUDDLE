"""FastAPI lifespan: startup/shutdown hooks for DB and Redis.

Startup performs bounded retries against DB and Redis so the app can start
slightly ahead of its dependencies (common in container orchestration)
without crash-looping.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import redis.asyncio as aredis
from fastapi import FastAPI
from sqlalchemy import text

from buddle.config import get_settings
from buddle.core.logging import get_logger
from buddle.db.session import engine

log = get_logger(__name__)

_STARTUP_MAX_ATTEMPTS = 10
_STARTUP_BASE_DELAY_S = 0.5
_STARTUP_MAX_DELAY_S = 5.0


async def _retry(coro_factory, *, name: str) -> None:  # type: ignore[no-untyped-def]
    """Run an async check with exponential backoff up to MAX_ATTEMPTS."""
    last_exc: Exception | None = None
    for attempt in range(1, _STARTUP_MAX_ATTEMPTS + 1):
        try:
            await coro_factory()
            return
        except Exception as e:
            last_exc = e
            delay = min(_STARTUP_BASE_DELAY_S * 2 ** (attempt - 1), _STARTUP_MAX_DELAY_S)
            log.warning(
                "startup.dependency_not_ready",
                dependency=name,
                attempt=attempt,
                retry_in_s=round(delay, 2),
                error=str(e),
            )
            await asyncio.sleep(delay)
    raise RuntimeError(f"{name} not reachable after {_STARTUP_MAX_ATTEMPTS} attempts") from last_exc


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    log.info("app.startup", env=settings.app_env, version=settings.app_version)

    async def _db_ping() -> None:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    await _retry(_db_ping, name="postgres")
    log.info("db.connected", url=_sanitize_url(settings.database_url))

    redis_client = aredis.from_url(settings.redis_url, decode_responses=True)

    async def _redis_ping() -> None:
        await redis_client.ping()

    await _retry(_redis_ping, name="redis")
    app.state.redis = redis_client
    log.info("redis.connected", url=settings.redis_url)

    # ── In-app scheduler (opt-in; admin tick endpoints work regardless) ──
    scheduler = None
    if settings.scheduler_enabled:
        from buddle.core.scheduler import build_default_scheduler

        scheduler = build_default_scheduler(redis_client)
        scheduler.start()
        app.state.scheduler = scheduler

    try:
        yield
    finally:
        log.info("app.shutdown")
        if scheduler is not None:
            await scheduler.stop()
        await redis_client.aclose()
        await engine.dispose()


def _sanitize_url(url: str) -> str:
    """Redact password from a URL for safe logging."""
    if "@" not in url or "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    if "@" not in rest:
        return url
    creds, host = rest.rsplit("@", 1)
    if ":" in creds:
        user, _ = creds.split(":", 1)
        return f"{scheme}://{user}:***@{host}"
    return url
