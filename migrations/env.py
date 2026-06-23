"""Alembic env. Async + settings-driven."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from buddle.config import get_settings
from buddle.db.base import Base

# Alembic config object
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject DB URL from settings (so single source of truth = .env)
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)

# Import all models so Base.metadata sees them
from buddle.db.models import (  # noqa: F401, E402
    ai_agent,
    authority_token,
    conversation_session,
    conversation_pool,
    insight_bundle,
    knowledge_audit,
    knowledge_unit,
    persona_context_ref,
    topic_edge,
    comment,
    distribution,
    ethics_alert,
    importance,
    mediator_policy,
    message,
    metric_snapshot,
    persona,
    persona_model,
    persona_topic_affinity,
    post,
    post_like,
    post_translation,
    session,
    security_event,
    tag,
    transformation_log,
    user,
)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
