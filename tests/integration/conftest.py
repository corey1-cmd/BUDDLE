"""Integration-test fixtures scoped to this directory."""

from __future__ import annotations

import pytest

# persona_models holds the 4 migration-seeded stub templates that personas FK to;
# we keep those rows (drop only test-added ones) and never truncate the table.
_SEEDED_MODEL_KEYS = ("poet", "analyst", "friend", "critic")
_PRESERVE = ("alembic_version", "persona_models")


@pytest.fixture(autouse=True)
async def _reset_db_after_test(_migrated_db):  # type: ignore[no-untyped-def]
    """Per-test data isolation + loop safety.

    After each test, TRUNCATE every data table (except the migration seed) and
    drop test-added persona models. Unlike a single-transaction SAVEPOINT scheme,
    each test's commits stay in their own transaction, so Postgres ``now()``
    keeps advancing and chronological (created_at-ordered) tests still work. Loop
    safety comes from the NullPool engine (see _bind_db_to), so no per-test
    engine disposal is needed.

    The singleton rows (mediator_policy, system_authority_state) are truncated
    then re-seeded to defaults — a clean reset between tests.
    """
    yield
    import buddle.db.session as dbs
    from sqlalchemy import text

    engine = dbs.get_engine()
    async with engine.begin() as conn:
        rows = await conn.execute(
            text(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                "AND tablename <> ALL(:preserve)"
            ),
            {"preserve": list(_PRESERVE)},
        )
        tables = [r[0] for r in rows]
        if tables:
            joined = ", ".join(f'"{t}"' for t in tables)
            await conn.execute(text(f"TRUNCATE {joined} RESTART IDENTITY CASCADE"))
        await conn.execute(
            text("DELETE FROM persona_models WHERE template_key <> ALL(:keys)"),
            {"keys": list(_SEEDED_MODEL_KEYS)},
        )
        # Re-seed the singleton rows that migrations create and whose admin
        # endpoints 404 without them (the services get-or-create, but the
        # GET/PATCH routes require the row). This also resets them to defaults
        # (authority -> normal, policy -> default weights).
        await conn.execute(
            text(
                "INSERT INTO system_authority_state (id, state) VALUES (1, 'normal') "
                "ON CONFLICT (id) DO NOTHING"
            )
        )
        await conn.execute(
            text("INSERT INTO mediator_policy (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
        )
