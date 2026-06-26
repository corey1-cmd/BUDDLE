"""Layer B stage 2-7 tests — service contracts, prompt injection, models.

DB-backed flows (consider_post, fetch_context, knowledge_tick) run in CI; here
we verify signatures, the model shapes, the prompt reference-injection, and the
internal signing helper — all without a database.
"""

from __future__ import annotations

import inspect

# ── service signatures ──────────────────────────────────────────────────────


def test_knowledge_service_entrypoints_exist():
    from buddle.services import knowledge_service as ks

    for fn in (
        "consider_post",
        "update_topic_edges",
        "fetch_context",
        "build_pool",
        "knowledge_tick",
    ):
        assert hasattr(ks, fn), fn


def test_consider_post_signature():
    from buddle.services import knowledge_service as ks

    p = inspect.signature(ks.consider_post).parameters
    assert "post_id" in p and "weights" in p and "commit" in p


def test_fetch_context_privacy_param():
    from buddle.services import knowledge_service as ks

    p = inspect.signature(ks.fetch_context).parameters
    # requesting persona drives the private-visibility check
    assert "requesting_persona_id" in p and "topic" in p


# ── models ──────────────────────────────────────────────────────────────────


def test_knowledge_unit_inherits_visibility_and_embedding():
    from buddle.db.models.knowledge_unit import KnowledgeUnit

    cols = set(KnowledgeUnit.__table__.columns.keys())
    assert {
        "source_post_id",
        "persona_id",
        "gist",
        "embedding",
        "visibility",
        "retention_score",
    } <= cols


def test_topic_edge_unique_pair():
    from buddle.db.models.topic_edge import TopicEdge

    uniques = [
        c for c in TopicEdge.__table__.constraints if c.__class__.__name__ == "UniqueConstraint"
    ]
    assert any({col.name for col in u.columns} == {"topic_a", "topic_b"} for u in uniques)


def test_knowledge_space_models_registered():
    from buddle.db.models import (
        ConversationPool,
        KnowledgeAudit,
        KnowledgeUnit,
        PersonaContextRef,
        PoolUnit,
        TopicEdge,
    )

    assert all(
        m is not None
        for m in (
            ConversationPool,
            KnowledgeAudit,
            KnowledgeUnit,
            PersonaContextRef,
            PoolUnit,
            TopicEdge,
        )
    )


# ── prompt reference injection (Layer B read path) ─────────────────────────


def test_build_dialogue_messages_accepts_knowledge_context():
    from buddle.ai.personas.prompts import build_dialogue_messages

    p = inspect.signature(build_dialogue_messages).parameters
    assert "knowledge_context" in p


def test_knowledge_context_injected_as_reference_not_instruction():
    from buddle.ai.personas.prompts import build_dialogue_messages

    msgs = build_dialogue_messages(
        persona_name="초록",
        model_system_prompt="너는 다정한 친구야",
        history=[],
        user_message="동네 산책 얘기하자",
        knowledge_context=["강가 코스가 좋더라", "아침이 한적해"],
    )
    # a system block carrying the reference material is present (the knowledge
    # space is labelled '당신의 지식 공간' — the internal-reference channel)
    ref = [m for m in msgs if m["role"] == "system" and "지식 공간" in m["content"]]
    assert len(ref) == 1
    assert "강가 코스" in ref[0]["content"]
    # framed as optional reference, not a directive
    assert "자연스럽게만 참고" in ref[0]["content"]
    # user message still last
    assert msgs[-1]["role"] == "user"


def test_no_knowledge_context_no_reference_block():
    from buddle.ai.personas.prompts import build_dialogue_messages

    msgs = build_dialogue_messages(
        persona_name="초록",
        model_system_prompt="너는 다정한 친구야",
        history=[],
        user_message="안녕",
    )
    assert not any("지식 공간" in m["content"] for m in msgs)


# ── technician signing helper (pure) ───────────────────────────────────────


def test_sign_unit_deterministic_and_bounded():
    from buddle.services.knowledge_service import _sign_unit

    a = _sign_unit("같은 생각")
    b = _sign_unit("같은 생각")
    c = _sign_unit("다른 생각")
    assert a == b  # deterministic
    assert a != c  # content-sensitive
    assert len(a) <= 128
