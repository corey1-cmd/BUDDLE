"""Relationship endpoint tests — schema/route contracts + DB-backed reads.

The endpoint is read-only by design (a relationship you set with a slider is
not a relationship), so the tests verify: the schema maps levels to stages,
the route is registered GET-only, reading a non-existent bond returns the
neutral starting point WITHOUT creating a row, and an owned bond reads back
its real level.
"""

from __future__ import annotations

import uuid

# ── contracts (no DB) ──────────────────────────────────────────────────────


def test_schema_maps_level_to_stage():
    from buddle.schemas.relationship import STAGE_LABELS, RelationshipRead

    class _Fake:
        level = 2
        affinity_score = 30.0
        positive_turns = 5
        negative_turns = 1
        turn_count = 8
        mood_valence = 0.3
        mood_energy = 0.5

    r = RelationshipRead.from_relationship(_Fake())
    assert r.level == 2
    assert r.stage_label == STAGE_LABELS[2]
    assert r.closeness_pct == 30


def test_schema_neutral_is_orientation_zero():
    from buddle.schemas.relationship import RelationshipRead

    r = RelationshipRead.neutral()
    assert r.level == 0
    assert r.affinity_score == 0.0
    assert r.turn_count == 0


def test_route_is_registered_get_only():
    from buddle.main import app

    from tests.integration._routes import route_methods

    methods = route_methods(app, "/v1/personas/{persona_id}/relationship")
    assert "GET" in methods
    # No write methods — the bond is shaped only by conversation.
    assert not ({"POST", "PUT", "PATCH", "DELETE"} & methods)


def test_find_relationship_is_read_only_signature():
    import inspect

    from buddle.services import conversation_service as cs

    assert hasattr(cs, "find_relationship")
    params = set(inspect.signature(cs.find_relationship).parameters)
    assert {"persona_id", "user_id"} <= params


# ── DB-backed flows ────────────────────────────────────────────────────────


async def _make_user_persona(db):  # type: ignore[no-untyped-def]
    from buddle.db.models.persona import Persona
    from buddle.db.models.user import User

    suffix = uuid.uuid4().hex[:10]
    user = User(email=f"rel_{suffix}@test.local", password_hash="x" * 32)
    db.add(user)
    await db.flush()
    persona = Persona(user_id=user.id, name=f"버들-{suffix}", model_key="friend")
    db.add(persona)
    await db.commit()
    return user.id, persona.id


async def test_find_does_not_create_a_row(db_session):  # type: ignore[no-untyped-def]
    from sqlalchemy import func, select

    from buddle.db.models.relationship import Relationship
    from buddle.services import conversation_service as cs

    user_id, persona_id = await _make_user_persona(db_session)

    found = await cs.find_relationship(db_session, persona_id=persona_id, user_id=user_id)
    assert found is None  # reading doesn't bring a bond into existence

    count = (
        await db_session.execute(
            select(func.count(Relationship.id)).where(Relationship.persona_id == persona_id)
        )
    ).scalar_one()
    assert int(count) == 0


async def test_owned_bond_reads_back_its_level(db_session):  # type: ignore[no-untyped-def]
    from buddle.ai.affect.perception import Valence
    from buddle.ai.conversation import TurnAffect
    from buddle.schemas.relationship import RelationshipRead
    from buddle.services import conversation_service as cs

    user_id, persona_id = await _make_user_persona(db_session)

    # Drive the bond up with positive turns, then read it back.
    for _ in range(3):
        await cs.update_relationship(
            db_session,
            persona_id=persona_id,
            user_id=user_id,
            affect=TurnAffect(Valence.POSITIVE, 0.7),
        )
    rel = await cs.find_relationship(db_session, persona_id=persona_id, user_id=user_id)
    assert rel is not None
    view = RelationshipRead.from_relationship(rel)
    assert view.affinity_score > 0
    assert view.positive_turns == 3
    assert view.level == rel.level
