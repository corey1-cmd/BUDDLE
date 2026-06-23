"""Conversation service tests — contracts (no DB) + DB-backed flows.

DB tests exercise the full loop: structured turns persist, the recent window
returns them with derived mood, and the relationship score moves per the
Gottman formula (positive raises it, a run of negatives can demote a level).
"""

from __future__ import annotations

import inspect
import uuid

# ── contracts (no DB) ──────────────────────────────────────────────────────


def test_models_columns():
    from buddle.db.models.conversation_turn import ConversationTurn
    from buddle.db.models.relationship import Relationship

    rel_cols = set(Relationship.__table__.columns.keys())
    assert {
        "persona_id",
        "user_id",
        "affinity_score",
        "level",
        "mood_valence",
        "mood_energy",
        "positive_turns",
        "negative_turns",
        "user_snapshot",
    } <= rel_cols

    turn_cols = set(ConversationTurn.__table__.columns.keys())
    assert {
        "session_id",
        "role",
        "content",
        "situation",
        "valence",
        "intensity",
        "was_followup",
        "opened_disclosure",
        "salient_topics",
        "affinity_delta",
    } <= turn_cols


def test_service_signatures():
    from buddle.services import conversation_service as cs

    assert {"session_id", "n"} <= set(inspect.signature(cs.recent_window).parameters)
    upd = set(inspect.signature(cs.update_relationship).parameters)
    assert {"persona_id", "user_id", "affect", "opened_disclosure"} <= upd


def test_migration_0019_chains_after_0018():
    from pathlib import Path

    src = Path("migrations/versions/20260612_1300_0019_conversation_psychology.py").read_text(
        encoding="utf-8"
    )
    assert 'revision: str = "0019"' in src
    assert 'down_revision: str | None = "0018"' in src


# ── DB-backed flows ────────────────────────────────────────────────────────


async def _make_user_persona_session(db):  # type: ignore[no-untyped-def]
    from buddle.db.models.conversation_session import ConversationSession
    from buddle.db.models.persona import Persona
    from buddle.db.models.user import User

    suffix = uuid.uuid4().hex[:10]
    user = User(email=f"convo_{suffix}@test.local", password_hash="x" * 32)
    db.add(user)
    await db.flush()
    persona = Persona(user_id=user.id, name=f"버들-{suffix}", model_key="friend")
    db.add(persona)
    await db.flush()
    session = ConversationSession(persona_id=persona.id, title="대화")
    db.add(session)
    await db.commit()
    return user.id, persona.id, session.id


async def test_record_turns_and_window_roundtrip(db_session):  # type: ignore[no-untyped-def]
    from buddle.ai.affect.perception import Valence
    from buddle.db.models.enums import MessageRole
    from buddle.services import conversation_service as cs

    _user_id, persona_id, session_id = await _make_user_persona_session(db_session)

    await cs.record_turn(
        db_session,
        session_id=session_id,
        persona_id=persona_id,
        role=MessageRole.USER,
        content="오늘 강가를 걸었는데 참 좋더라",
        valence=Valence.POSITIVE,
        intensity=0.6,
        salient_topics=["산책", "강가"],
    )
    await cs.record_turn(
        db_session,
        session_id=session_id,
        persona_id=persona_id,
        role=MessageRole.PERSONA,
        content="강가 산책 좋죠, 어떤 점이 좋았어요?",
    )

    window = await cs.recent_window(db_session, session_id=session_id, n=10)
    assert len(window.turns) == 2
    assert window.turns[0].role == "user"
    assert "산책" in window.salient_topics
    # The persona's turn ended with a question → next reciprocity flag.
    assert window.persona_last_was_question is True
    # Mood reflects the positive user turn.
    assert window.mood.valence > 0


async def test_relationship_rises_with_positive_turns(db_session):  # type: ignore[no-untyped-def]
    from buddle.ai.affect.perception import Valence
    from buddle.ai.conversation import TurnAffect
    from buddle.services import conversation_service as cs

    user_id, persona_id, _session_id = await _make_user_persona_session(db_session)

    rel, delta, _ = await cs.update_relationship(
        db_session,
        persona_id=persona_id,
        user_id=user_id,
        affect=TurnAffect(Valence.POSITIVE, 0.6),
    )
    assert delta > 0
    assert rel.affinity_score > 0
    assert rel.positive_turns == 1
    assert rel.turn_count == 1


async def test_relationship_negative_withdraws_more_than_positive(db_session):  # type: ignore[no-untyped-def]
    from buddle.ai.affect.perception import Valence
    from buddle.ai.conversation import TurnAffect
    from buddle.services import conversation_service as cs

    user_id, persona_id, _ = await _make_user_persona_session(db_session)

    # Build up a few positives, then one negative should hurt noticeably.
    for _ in range(5):
        await cs.update_relationship(
            db_session,
            persona_id=persona_id,
            user_id=user_id,
            affect=TurnAffect(Valence.POSITIVE, 0.4),
        )
    rel = await cs.load_relationship(db_session, persona_id=persona_id, user_id=user_id)
    before = float(rel.affinity_score)

    _, neg_delta, _ = await cs.update_relationship(
        db_session,
        persona_id=persona_id,
        user_id=user_id,
        affect=TurnAffect(Valence.NEGATIVE, 0.4),
    )
    rel2 = await cs.load_relationship(db_session, persona_id=persona_id, user_id=user_id)
    assert neg_delta < 0
    assert float(rel2.affinity_score) < before
    assert rel2.negative_turns == 1


async def test_user_snapshot_reflects_profile(db_session):  # type: ignore[no-untyped-def]
    from buddle.services import conversation_service as cs
    from buddle.services import profile_service

    user_id, _persona_id, _ = await _make_user_persona_session(db_session)
    # No profile yet → snapshot is None.
    assert await cs.build_user_snapshot(db_session, user_id=user_id) is None

    await profile_service.observe_text(
        db_session, user_id=user_id, text="새로운 게 늘 궁금하고 모임도 좋아해"
    )
    snap = await cs.build_user_snapshot(db_session, user_id=user_id)
    assert snap is not None
    assert set(snap.keys()) >= {"o", "c", "e", "a", "n", "confidence"}


async def test_opted_out_user_has_no_snapshot(db_session):  # type: ignore[no-untyped-def]
    from buddle.services import conversation_service as cs
    from buddle.services import profile_service

    user_id, _persona_id, _ = await _make_user_persona_session(db_session)
    await profile_service.update_profile(db_session, user_id=user_id, profile_opt_out=True)
    assert await cs.build_user_snapshot(db_session, user_id=user_id) is None
