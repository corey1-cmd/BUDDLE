"""Memory service tests — model/migration contracts (no DB) + DB-backed flows.

The DB tests exercise the full EKB Retention→Search loop against Postgres +
pgvector: observe persists disclosures, near-duplicates reinforce instead of
duplicating, recall ranks and reinforces, capacity eviction forgets the
least-activated rows, and memories survive across sessions (the whole point).
They run when Docker/`BUDDLE_TEST_DATABASE_URL` is available, like every other
DB-backed suite here.
"""

from __future__ import annotations

import inspect
import uuid

# ── contracts (no DB) ──────────────────────────────────────────────────────


def test_memory_model_columns():
    from buddle.db.models.persona_memory import PersonaMemory

    cols = set(PersonaMemory.__table__.columns.keys())
    assert {
        "id",
        "persona_id",
        "kind",
        "content",
        "emb",
        "importance",
        "strength",
        "source_session_id",
        "created_at",
        "last_accessed_at",
    } <= cols
    # Graceful degradation contract: remembering must work without embeddings.
    assert PersonaMemory.__table__.columns["emb"].nullable


def test_memory_kind_enum_values():
    from buddle.db.models.enums import MemoryKind

    assert {k.value for k in MemoryKind} == {"fact", "preference", "event", "relation"}


def test_service_signatures():
    from buddle.services import memory_service

    recall_params = inspect.signature(memory_service.recall).parameters
    assert {"persona_id", "query_text", "k", "now"} <= set(recall_params)
    observe_params = inspect.signature(memory_service.observe_turn).parameters
    assert {"persona_id", "user_text", "session_id", "now"} <= set(observe_params)


def test_migration_0017_chains_after_0016():
    from pathlib import Path

    src = Path("migrations/versions/20260612_0900_0017_persona_memory.py").read_text(
        encoding="utf-8"
    )
    assert 'revision: str = "0017"' in src
    assert 'down_revision: str | None = "0016"' in src


# ── DB-backed flows ────────────────────────────────────────────────────────


async def _make_persona(db) -> uuid.UUID:  # type: ignore[no-untyped-def]
    """Minimal user+persona pair for memory rows (FK targets)."""
    from buddle.db.models.persona import Persona
    from buddle.db.models.user import User

    suffix = uuid.uuid4().hex[:10]
    user = User(email=f"mem_{suffix}@test.local", password_hash="x" * 32)
    db.add(user)
    await db.flush()
    persona = Persona(user_id=user.id, name=f"버들-{suffix}", model_key="friend")
    db.add(persona)
    await db.commit()
    return persona.id


async def test_observe_then_recall_roundtrip_across_sessions(db_session):  # type: ignore[no-untyped-def]
    """A disclosure made in session A is recalled later (no session filter) —
    the Atkinson-Shiffrin LTM contract the 20-turn window cannot satisfy."""
    from buddle.services import memory_service

    persona_id = await _make_persona(db_session)
    stored = await memory_service.observe_turn(
        db_session,
        persona_id=persona_id,
        user_text="오늘 강가를 걸었는데 참 좋더라. 비슷한 사람과 닿고 싶다.",
        session_id=None,  # session row not created in this minimal fixture
    )
    assert stored >= 2  # event + preference

    recalled = await memory_service.recall(
        db_session, persona_id=persona_id, query_text="강가 산책 어땠어?"
    )
    assert recalled, "stored disclosures must be recallable"
    assert any("강가" in m.content for m in recalled)
    assert all(0.0 <= m.score <= 1.0 for m in recalled)


async def test_duplicate_disclosure_reinforces_instead_of_duplicating(db_session):  # type: ignore[no-untyped-def]
    """Re-disclosure is rehearsal: one row, strength climbs (idempotency)."""
    from sqlalchemy import select

    from buddle.db.models.persona_memory import PersonaMemory
    from buddle.services import memory_service

    persona_id = await _make_persona(db_session)
    text = "나는 잔잔한 산책을 정말 좋아해"

    await memory_service.observe_turn(db_session, persona_id=persona_id, user_text=text)
    await memory_service.observe_turn(db_session, persona_id=persona_id, user_text=text)

    rows = (
        (
            await db_session.execute(
                select(PersonaMemory).where(PersonaMemory.persona_id == persona_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].strength >= 2.0


async def test_recall_reinforces_retrieved_memories(db_session):  # type: ignore[no-untyped-def]
    """ACT-R: retrieval itself raises activation (strength, last_accessed)."""
    from sqlalchemy import select

    from buddle.db.models.persona_memory import PersonaMemory
    from buddle.services import memory_service

    persona_id = await _make_persona(db_session)
    await memory_service.observe_turn(
        db_session, persona_id=persona_id, user_text="나는 잔잔한 산책을 정말 좋아해"
    )
    before = (
        (
            await db_session.execute(
                select(PersonaMemory).where(PersonaMemory.persona_id == persona_id)
            )
        )
        .scalars()
        .one()
    )
    strength_before = float(before.strength)

    recalled = await memory_service.recall(
        db_session, persona_id=persona_id, query_text="산책 좋아했지?"
    )
    assert recalled

    await db_session.refresh(before)
    assert float(before.strength) == strength_before + 1.0


async def test_capacity_eviction_forgets_least_activated(db_session):  # type: ignore[no-untyped-def]
    """Bounded forgetting: beyond the cap, the weakest rows are evicted."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from buddle.db.models.enums import MemoryKind
    from buddle.db.models.persona_memory import PersonaMemory
    from buddle.services.memory_service import _enforce_capacity

    persona_id = await _make_persona(db_session)
    now = datetime.now(UTC)
    for i in range(5):
        db_session.add(
            PersonaMemory(
                persona_id=persona_id,
                kind=MemoryKind.FACT,
                content=f"기억 {i}",
                emb=None,
                importance=0.5,
                strength=1.0 + i,  # 0 is weakest
                created_at=now - timedelta(hours=10 - i),
                last_accessed_at=now - timedelta(hours=10 - i),  # 0 is oldest
            )
        )
    await db_session.commit()

    await _enforce_capacity(db_session, persona_id=persona_id, cap=3)

    remaining = (
        (
            await db_session.execute(
                select(PersonaMemory.content).where(PersonaMemory.persona_id == persona_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(remaining) == 3
    assert "기억 0" not in remaining and "기억 1" not in remaining
