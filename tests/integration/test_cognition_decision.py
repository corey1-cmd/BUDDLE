"""EKB Stage B (Decision Process) tests — pure, no DB.

Validates problem recognition, search source selection, alternative evaluation
with persona-disposition weighting, choice, the safety override, and the
synthesized prompt block.
"""

from __future__ import annotations

from buddle.ai.cognition import (
    PersonaDispositions,
    ResponseStrategy,
    decide,
    process_information,
    run_cognition,
    synthesize_prompt_block,
)
from buddle.ai.cognition.signals import Intent


def _info(text: str):  # type: ignore[no-untyped-def]
    return process_information(text)


# ── Choice per intent ────────────────────────────────────────────────────


def test_share_news_chooses_celebrate():
    d = decide(_info("나 시험 합격했어!"))
    assert d.chosen == ResponseStrategy.CELEBRATE


def test_seek_support_chooses_comfort():
    d = decide(_info("너무 외롭고 우울해"))
    assert d.chosen == ResponseStrategy.COMFORT


def test_ask_info_chooses_inform():
    d = decide(_info("이거 어떻게 동작해?"))
    assert d.chosen == ResponseStrategy.INFORM


def test_request_action_chooses_assist():
    d = decide(_info("이 버그 고쳐줘"))
    assert d.chosen == ResponseStrategy.ASSIST


def test_vague_message_raises_clarify():
    d = decide(_info("어"))
    # CLARIFY should be present and highly ranked for a vague message
    strategies = {c.strategy for c in d.candidates}
    assert ResponseStrategy.CLARIFY in strategies


# ── Problem recognition ──────────────────────────────────────────────────


def test_problem_recognition_text():
    d = decide(_info("나 합격했어!"))
    assert "좋은 소식" in d.problem


def test_problem_recognition_flags_ambiguity():
    d = decide(_info("어"))
    assert "모호" in d.problem


# ── Search source selection ──────────────────────────────────────────────


def test_search_uses_history_for_info_intent():
    d = decide(_info("아까 그거 어떻게 한다고?"), has_history=True)
    assert d.search.internal_memory_used


def test_search_uses_external_for_info_intent():
    d = decide(_info("이거 어떻게 해?"), has_external=True)
    assert d.search.external_context_used


def test_search_none_when_self_contained():
    d = decide(_info("나 합격했어!"), has_history=False, has_external=False)
    assert not d.search.internal_memory_used
    assert not d.search.external_context_used


# ── Disposition weighting ────────────────────────────────────────────────


def test_warm_persona_scores_emotional_higher_than_cold():
    warm = PersonaDispositions(warmth=0.95)
    cold = PersonaDispositions(warmth=0.05)
    info = _info("나 합격했어!")
    d_warm = decide(info, dispositions=warm)
    d_cold = decide(info, dispositions=cold)

    def celebrate_score(d):  # type: ignore[no-untyped-def]
        return next(c.score for c in d.candidates if c.strategy == ResponseStrategy.CELEBRATE)

    assert celebrate_score(d_warm) > celebrate_score(d_cold)


def test_informative_persona_scores_inform_higher():
    talky = PersonaDispositions(informativeness=0.95)
    quiet = PersonaDispositions(informativeness=0.05)
    info = _info("이거 어떻게 해?")

    def inform_score(d):  # type: ignore[no-untyped-def]
        return next(c.score for c in d.candidates if c.strategy == ResponseStrategy.INFORM)

    assert inform_score(decide(info, dispositions=talky)) > inform_score(
        decide(info, dispositions=quiet)
    )


# ── Safety override ──────────────────────────────────────────────────────


def test_distress_never_celebrated():
    # Even if somehow scored, a support-seeking distressed message must not be
    # answered with CELEBRATE.
    d = decide(_info("시험 떨어져서 너무 우울하고 힘들어"))
    assert d.chosen != ResponseStrategy.CELEBRATE


# ── Candidates ordering ──────────────────────────────────────────────────


def test_candidates_sorted_descending():
    d = decide(_info("이거 어떻게 해?"))
    scores = [c.score for c in d.candidates]
    assert scores == sorted(scores, reverse=True)


# ── Synthesis ────────────────────────────────────────────────────────────


def test_synthesize_block_contains_sections():
    info = _info("나 합격했어!")
    d = decide(info)
    block = synthesize_prompt_block(info, d)
    assert "인지 분석" in block
    assert "응답 전략" in block
    assert "toxic positivity" in block


def test_run_cognition_end_to_end():
    info, decision, block = run_cognition("너무 외롭고 힘들어", has_history=True)
    assert info.intent == Intent.SEEK_SUPPORT
    assert decision.chosen == ResponseStrategy.COMFORT
    assert "검증" in block or "위로" in block or "인정" in block


# ── bias-safety ──────────────────────────────────────────────────────────


def test_decision_deterministic_for_same_inputs():
    info = _info("나 합격했어!")
    disp = PersonaDispositions(warmth=0.7)
    d1 = decide(info, dispositions=disp)
    d2 = decide(info, dispositions=disp)
    assert d1.chosen == d2.chosen
    assert [c.score for c in d1.candidates] == [c.score for c in d2.candidates]
