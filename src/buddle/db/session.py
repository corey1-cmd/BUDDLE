"""Async DB engine + session factory + FastAPI dependency.

The engine + sessionmaker are built LAZILY on first use, not at import time, so
they bind to the settings in effect when the DB is first touched — not whatever
``get_settings()`` happened to read when this module was first imported. This
keeps imports cheap and, crucially, lets tests point ``DATABASE_URL`` at a
throwaway container even if some module imported this one at collection time
(otherwise the engine would bind to the .env URL before the test fixture runs).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from buddle.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _build() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    global _engine, _sessionmaker
    if _sessionmaker is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            echo=False,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_pre_ping=True,
            pool_recycle=settings.db_pool_recycle_s,
            connect_args={
                # Supabase Supavisor / pgbouncer compatibility: asyncpg's
                # client-side prepared-statement cache breaks behind a
                # transaction-mode pooler ("prepared statement __asyncpg__
                # already exists"). 0 is safe everywhere (direct Postgres too).
                "statement_cache_size": settings.db_statement_cache_size,
            },
        )
        _sessionmaker = async_sessionmaker(
            bind=_engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _engine, _sessionmaker  # type: ignore[return-value]


def get_engine() -> AsyncEngine:
    """Return the process-wide async engine (built on first call)."""
    return _build()[0]


class _LazySessionLocal:
    """Drop-in for ``async_sessionmaker``: calling it opens a session, building
    the engine + maker on first use. Keeps ``AsyncSessionLocal()`` working at
    every existing call site while deferring engine creation."""

    def __call__(self) -> AsyncSession:
        return _build()[1]()


AsyncSessionLocal = _LazySessionLocal()


def __getattr__(name: str) -> Any:
    # Back-compat: ``from buddle.db.session import engine`` still works, but the
    # engine is created only when the name is actually resolved.
    if name == "engine":
        return get_engine()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yields a session and ensures cleanup."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
