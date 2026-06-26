"""Integration test fixtures.

Strategy:
  - One Postgres container per test session (pgvector image).
  - Apply both migrations (0001 + 0002 — registry incl. 4 stub models).
  - Fake Redis via fakeredis injected onto app.state.
  - httpx.AsyncClient hits the app in-process via ASGITransport.
  - Lifespan is bypassed; DB/Redis attachment happens in the `app` fixture.
"""

from __future__ import annotations

import os
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def event_loop_policy():  # type: ignore[no-untyped-def]
    """asyncpg needs the Selector loop on Windows — the default Proactor loop
    breaks connection teardown ("'NoneType' object has no attribute 'send'").
    No-op elsewhere. pytest-asyncio uses this fixture to build the loop."""
    import asyncio

    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.get_event_loop_policy()


def _testcontainers_available() -> bool:
    try:
        import testcontainers.postgres  # noqa: F401

        return True
    except ImportError:
        return False


@pytest.fixture(scope="session", autouse=True)
def _configure_env() -> Iterator[None]:
    """Inject non-DB test env vars before any buddle module reads settings.

    DATABASE_URL is set later by the `postgres_url` fixture, so pure unit
    tests (importance math, ethics stub) don't require a Postgres container.
    """
    os.environ.setdefault("REDIS_URL", "redis://unused-fakeredis:6379/0")
    os.environ.setdefault("JWT_SECRET_KEY", "test_secret_key_at_least_32_bytes_long_!")
    os.environ.setdefault("APP_ENV", "development")
    os.environ.setdefault("LOG_LEVEL", "WARNING")
    os.environ.setdefault("FREE_PERSONA_QUOTA", "3")
    # The rate limiter's process-local backup bucket is module-global and so
    # persists across tests in a session (each test gets a fresh fakeredis, but
    # not a fresh local bucket) — it would trip after a handful of signups and
    # fail unrelated tests. Disable that backup layer; tests exercise the Redis
    # layer (reset per test) and the limiter logic directly.
    os.environ.setdefault("RATELIMIT_LOCAL_BACKUP_ENABLED", "false")
    # Tests register persona/ethics backends at loopback URLs to exercise the
    # backend path; allow private hosts so the SSRF guard doesn't reject them.
    os.environ.setdefault("ALLOW_PRIVATE_BACKEND_HOSTS", "true")

    from buddle.config import get_settings

    get_settings.cache_clear()
    yield


def _to_asyncpg_url(raw: str) -> str:
    """Normalize any Postgres URL to the asyncpg driver form."""
    url = raw.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):  # some providers use this scheme
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


def _bind_db_to(async_url: str) -> None:
    """Point DATABASE_URL at `async_url` and force buddle.db.session to rebuild
    its lazy engine against it — discarding any engine an early top-level import
    may have bound to the .env (prod Supabase) URL at collection time."""
    os.environ["DATABASE_URL"] = async_url

    from buddle.config import get_settings

    get_settings.cache_clear()

    import buddle.db.session as _dbs

    _dbs._engine = None
    _dbs._sessionmaker = None


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """Provide a Postgres URL for the test session.

    Resolution order:
      1. BUDDLE_TEST_DATABASE_URL (an external Postgres + pgvector, e.g. Supabase
         or a local install) -> used directly, no Docker required.
      2. testcontainers pgvector container (requires Docker).
    Otherwise the DB-backed tests skip.
    """
    external = os.environ.get("BUDDLE_TEST_DATABASE_URL", "").strip()
    if external:
        async_url = _to_asyncpg_url(external)
        _bind_db_to(async_url)
        yield async_url
        return

    if not _testcontainers_available():
        pytest.skip(
            "No BUDDLE_TEST_DATABASE_URL and testcontainers not available; "
            "set BUDDLE_TEST_DATABASE_URL (e.g. Supabase) or install Docker+testcontainers"
        )

    from testcontainers.postgres import PostgresContainer

    try:
        # DockerClient pings the daemon at construction, so both the
        # constructor and start() can raise when Docker is absent.
        container = PostgresContainer(
            image="pgvector/pgvector:pg16",
            username="buddle_test",
            password="buddle_test",
            dbname="buddle_test",
        )
        container.start()
    except Exception as e:
        # testcontainers is importable but the Docker daemon isn't reachable
        # (CI sandboxes, machines without Docker). Same skip path as "not
        # installed" so the gate numbers are identical everywhere.
        pytest.skip(f"testcontainers installed but Docker unavailable: {e}")
    try:
        raw = container.get_connection_url()
        async_url = raw.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
        async_url = async_url.replace("postgresql://", "postgresql+asyncpg://")
        _bind_db_to(async_url)
        yield async_url
    finally:
        container.stop()


@pytest.fixture(scope="session")
def _migrated_db(_configure_env: None, postgres_url: str) -> Iterator[None]:
    """Apply Alembic migrations to the test container once per session."""
    from alembic import command
    from alembic.config import Config

    project_root = Path(__file__).resolve().parent.parent
    cfg = Config(str(project_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(project_root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", postgres_url)
    command.upgrade(cfg, "head")
    yield


@pytest.fixture
async def db_session(_migrated_db: None) -> AsyncIterator:  # type: ignore[type-arg]
    """Per-test session. Does not roll back — tests are append-only and use
    unique emails / per-user data, so cross-test contamination is bounded."""
    from buddle.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        yield session


@pytest.fixture
async def app(_migrated_db: None):  # type: ignore[no-untyped-def]
    """Build a FastAPI app WITHOUT the production lifespan (which would try to
    connect to a real Redis). Attach fakeredis directly."""
    import fakeredis.aioredis
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    from buddle.api.errors import register_exception_handlers
    from buddle.api.v1 import api_v1_router
    from buddle.config import get_settings
    from buddle.main import RequestIdMiddleware

    settings = get_settings()
    app_instance = FastAPI(title=settings.app_name, version=settings.app_version)
    app_instance.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app_instance.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app_instance)
    app_instance.include_router(api_v1_router)

    @app_instance.get("/health")
    async def _health() -> dict[str, str]:
        return {"status": "ok", "version": settings.app_version}

    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    app_instance.state.redis = fake

    yield app_instance

    await fake.aclose()


@pytest.fixture
async def client(app):  # type: ignore[no-untyped-def]
    """httpx.AsyncClient targeting the app in-process."""
    from httpx import ASGITransport, AsyncClient

    # raise_app_exceptions=False: let the app's exception handlers turn errors
    # into HTTP responses (e.g. 422) instead of re-raising them through the
    # transport. Newer httpx defaults this True, which made handled validation
    # errors propagate as exceptions and fail status-code assertions.
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ── Helpers ─────────────────────────────────────────────────────────


@pytest.fixture
async def signup_and_login(client):  # type: ignore[no-untyped-def]
    """Factory: create a fresh user and return tokens + identifiers."""
    counter = {"n": 0}

    async def _factory(
        *, email: str | None = None, password: str = "TestPass123!"
    ) -> dict[str, str]:
        counter["n"] += 1
        # Use a real gTLD (.app), not the reserved .test TLD (RFC 2606): the
        # required email-validator (>=2.2) rejects special-use domains, which
        # would fail every signup-based test on a fresh install.
        email = email or f"user{counter['n']}-{id(counter):x}@buddle.app"

        r = await client.post(
            "/v1/auth/signup",
            json={"email": email, "password": password, "password_confirm": password},
        )
        assert r.status_code == 201, r.text
        user_id = r.json()["user_id"]

        r = await client.post(
            "/v1/auth/login",
            json={"email": email, "password": password},
        )
        assert r.status_code == 200, r.text
        tokens = r.json()
        return {
            "user_id": user_id,
            "email": email,
            "password": password,
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
        }

    return _factory
