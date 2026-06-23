"""Persona long-term memory — pure-layer unit tests (no DB, no network).

Covers the three theory commitments and the EKB wiring:
  * scoring  — Park et al. 2023 composition, Ebbinghaus decay, ACT-R strength
  * extraction — EKB Retention: disclosures in, questions/noise out, idempotent
  * morphology — kiwipiepy path AND josa-strip fallback ("산에" regression)
  * cognition — recall reaches the Search stage and the synthesized block
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from buddle.ai.lang import morph
from buddle.ai.memory import (
    W_IMPORTANCE,
    W_RECENCY,
    W_RELEVANCE,
    cosine_from_pgvector_distance,
    extract_candidates,
    memory_score,
    recency_weight,
)
from buddle.db.models.enums import MemoryKind

_NOW = datetime(2026, 6, 12, 12, 0, tzinfo=UTC)


# ── scoring: Ebbinghaus decay ──────────────────────────────────────────────


def test_recency_decays_over_time():
    fresh = recency_weight(_NOW, now=_NOW, strength=1.0)
    old = recency_weight(_NOW - timedelta(hours=200), now=_NOW, strength=1.0)
    assert fresh == 1.0
    assert old < fresh


def test_strength_slows_forgetting():
    """ACT-R approximation: a much-retrieved memory decays more slowly."""
    when = _NOW - timedelta(hours=200)
    weak = recency_weight(when, now=_NOW, strength=1.0)
    strong = recency_weight(when, now=_NOW, strength=10.0)
    assert strong > weak


def test_relevance_carries_dominant_weight():
    assert W_RELEVANCE > W_RECENCY and W_RELEVANCE > W_IMPORTANCE
    base = dict(importance=0.5, strength=1.0, last_accessed_at=_NOW, now=_NOW)
    assert memory_score(cosine_sim=0.9, **base) > memory_score(cosine_sim=0.1, **base)


def test_score_clamped_to_unit_interval():
    s = memory_score(
        cosine_sim=5.0, importance=9.0, strength=100.0, last_accessed_at=_NOW, now=_NOW
    )
    assert 0.0 <= s <= 1.0


def test_pgvector_distance_to_similarity_mapping():
    assert cosine_from_pgvector_distance(0.0) == 1.0
    assert cosine_from_pgvector_distance(2.0) == 0.0
    assert cosine_from_pgvector_distance(1.0) == 0.5


# ── extraction: EKB Retention ──────────────────────────────────────────────


def test_extracts_event_and_preference_from_e2e_sentence():
    """The canonical E2E input must yield a lived event + a stated desire."""
    cands = extract_candidates("오늘 강가를 걸었는데 참 좋더라. 비슷한 사람과 닿고 싶다.")
    kinds = [c.kind for c in cands]
    assert MemoryKind.EVENT in kinds
    assert MemoryKind.PREFERENCE in kinds
    assert all(0.0 <= c.importance <= 1.0 for c in cands)


def test_questions_are_not_disclosures():
    assert extract_candidates("내일 날씨 어때?") == []
    assert extract_candidates("강남 맛집 추천해 줄 수 있나요?") == []


def test_trivial_input_yields_nothing():
    assert extract_candidates("ㅇㅇ") == []
    assert extract_candidates("   ") == []
    assert extract_candidates("") == []


def test_preference_disclosure():
    cands = extract_candidates("나는 잔잔한 산책을 정말 좋아해")
    assert len(cands) == 1
    assert cands[0].kind is MemoryKind.PREFERENCE


def test_relation_disclosure():
    cands = extract_candidates("내 동생은 부산에 살아서 자주 못 본다")
    assert any(c.kind is MemoryKind.RELATION for c in cands)


def test_fact_disclosure():
    cands = extract_candidates("나는 생체의공학 전공이야")
    assert any(c.kind is MemoryKind.FACT for c in cands)


def test_extraction_is_deterministic():
    text = "오늘 강가를 걸었는데 참 좋더라. 비슷한 사람과 닿고 싶다."
    assert extract_candidates(text) == extract_candidates(text)


def test_extraction_caps_candidates():
    text = " ".join(f"나는 취미{i}를 정말 좋아해." for i in range(8))
    assert len(extract_candidates(text)) <= 3


# ── morphology: the "산에" regression ──────────────────────────────────────


def test_fallback_strips_locative_josa_from_two_char_noun(monkeypatch):
    """Without the analyzer, the bounded josa-strip must still solve 산에→산."""
    monkeypatch.setattr(morph, "_kiwi", lambda: None)
    tokens = morph.extract_content_tokens("산에 갔다")
    assert "산" in tokens


def test_content_tokens_find_nouns_on_any_path():
    """Holds with kiwipiepy installed (CI/[korean]) or absent (fallback)."""
    assert "강가" in morph.extract_content_tokens("오늘 강가를 걸었는데 참 좋더라")


# ── cognition threading: recall reaches Search + prompt block ──────────────


def test_decide_with_recall_marks_internal_memory_used():
    from buddle.ai.cognition import decide, process_information

    info = process_information("요즘 잘 지내?")
    decision = decide(info, recalled_memories=("사용자는 강가 산책을 좋아한다",))
    assert decision.search.internal_memory_used is True
    assert decision.search.recalled == ("사용자는 강가 산책을 좋아한다",)
    assert any("장기 기억" in n for n in decision.search.notes)


def test_recalled_memories_capped_at_five():
    from buddle.ai.cognition import decide, process_information

    info = process_information("안녕!")
    decision = decide(info, recalled_memories=tuple(f"기억 {i}" for i in range(9)))
    assert len(decision.search.recalled) == 5


def test_synthesized_block_carries_memories_with_usage_guidance():
    from buddle.ai.cognition import run_cognition

    _, _, block = run_cognition(
        "오늘 뭐 할까?", recalled_memories=("사용자는 강가 산책을 좋아한다",)
    )
    assert "장기 기억" in block
    assert "강가 산책" in block
    assert "나열" in block  # the do-not-show-off guidance line


def test_build_dialogue_messages_threads_memories_into_prompt():
    from buddle.ai.personas.prompts import build_dialogue_messages

    messages = build_dialogue_messages(
        persona_name="버들",
        model_system_prompt=None,
        history=[],
        user_message="오늘 산책 갈까 고민이야",
        recalled_memories=["사용자는 강가 산책을 좋아한다"],
    )
    joined = "\n".join(m["content"] for m in messages if m["role"] == "system")
    assert "강가 산책" in joined


def test_all_persona_backends_accept_recalled_memories():
    """Protocol conformance: every backend's respond_in_dialogue takes the
    recalled_memories keyword (so the factory can thread it blindly)."""
    import inspect

    from buddle.ai.personas.local_hf import LocalHfPersona
    from buddle.ai.personas.ondevice_webllm import OndeviceWebllmPersona
    from buddle.ai.personas.vllm_endpoint import VllmEndpointPersona
    from buddle.ai.stubs.persona_stub import PersonaStub

    for backend in (VllmEndpointPersona, LocalHfPersona, OndeviceWebllmPersona, PersonaStub):
        sig = inspect.signature(backend.respond_in_dialogue)
        assert "recalled_memories" in sig.parameters, backend.__name__
