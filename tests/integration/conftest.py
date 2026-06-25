"""Integration-test fixtures scoped to this directory."""

from __future__ import annotations

import contextlib

import pytest


@pytest.fixture(autouse=True)
async def _dispose_db_engine_after_test():  # type: ignore[no-untyped-def]
    """Dispose the lazy DB engine after each test so the next test rebuilds it on
    its own event loop.

    The engine + sessionmaker in ``buddle.db.session`` are process-global and
    built on first use. When pytest-asyncio runs tests on per-test event loops,
    an engine built on one loop and reused on another raises
    "got Future ... attached to a different loop". Disposing + clearing the
    singleton here makes the next test build a fresh engine bound to its loop.
    No-op for tests that never touched the DB.
    """
    yield
    import buddle.db.session as dbs

    if dbs._engine is not None:
        with contextlib.suppress(Exception):
            await dbs._engine.dispose()
        dbs._engine = None
        dbs._sessionmaker = None
