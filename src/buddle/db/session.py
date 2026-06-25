"""Async DB engine + session factory + FastAPI dependency."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from buddle.config import get_settings

_settings = get_settings()

engine = create_async_engine(
    _settings.database_url,
    echo=False,
    pool_size=_settings.db_pool_size,
    max_overflow=_settings.db_max_overflow,
    pool_pre_ping=True,
    pool_recycle=_settings.db_pool_recycle_s,
    connect_args={
        # Supabase Supavisor / pgbouncer compatibility: asyncpg's client-side
        # prepared-statement cache breaks behind a transaction-mode pooler
        # ("prepared statement __asyncpg__ already exists"). Disabling it (0)
        # makes the engine safe behind any pooler; harmless for direct Postgres.
        "statement_cache_size": _settings.db_statement_cache_size,
    },
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yields a session and ensures cleanup."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
