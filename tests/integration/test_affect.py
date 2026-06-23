"""Affect perception + guidance tests (pure).

Validates the evidence-based posture mapping AND the anti-bias contract:
perception depends only on the message content, never on who sent it or any
history — so identical text always yields identical analysis.
"""

from __future__ import annotations

from buddle.ai.affect import (
    ResponsePosture,
    Valence,
    build_affect_guidance,
    perceive,
)

# ── posture mapping (evidence-aligned) ───────────────────────────────────


def test_good_news_triggers_celebrate_acr():
    a = perceive("나 오늘 대학 합격했어!")
    assert a.valence == Valence.POSITIVE
    assert a.posture == ResponsePosture.CELEBRATE


def test_distress_triggers_support():
    a = perceive("요즘 너무 외롭고 우울해서 힘들어")
    assert a.valence == Valence.NEGATIVE
    assert a.posture == ResponsePosture.SUPPORT


def test_mild_negative_triggers_encourage():
    a = perceive("오늘 좀 지치고 짜증났어")
    assert a.valence == Valence.NEGATIVE
    # tired/annoyed are negative but not in the distress set
    assert a.posture == ResponsePosture.ENCOURAGE


def test_question_triggers_engage():
    a = perceive("이거 어떻게 하는지 알아?")
    assert a.is_question
    assert a.posture == ResponsePosture.ENGAGE


def test_neutral_triggers_reflect():
    a = perceive("오늘 점심은 김밥을 먹었다")
    assert a.valence == Valence.NEUTRAL
    assert a.posture == ResponsePosture.REFLECT


def test_english_signals_work_too():
    a = perceive("I am so happy, I finally passed!")
    assert a.valence == Valence.POSITIVE
    assert a.posture == ResponsePosture.CELEBRATE


# ── anti-bias contract ───────────────────────────────────────────────────


def test_identical_text_yields_identical_analysis():
    """No profiling/history: same message -> same result, every time."""
    msg = "시험에 떨어져서 속상하고 불안해"
    a1 = perceive(msg)
    a2 = perceive(msg)
    assert a1 == a2


def test_perceive_signature_takes_only_text():
    """The perceive() API accepts a single message and nothing identifying —
    structurally preventing user/group adaptation (bias amplification)."""
    import inspect

    sig = inspect.signature(perceive)
    params = list(sig.parameters)
    assert params == ["text"]


def test_intensity_scales_with_affect_words():
    low = perceive("좀 슬퍼")
    high = perceive("너무 슬프고 외롭고 불안하고 괴로워")
    assert high.intensity > low.intensity


# ── guidance text ────────────────────────────────────────────────────────


def test_guidance_includes_anti_toxic_positivity():
    g = build_affect_guidance(perceive("나 합격했어!"))
    # common tone block forbids fake positivity
    assert "toxic positivity" in g


def test_guidance_support_avoids_quick_fixes_language():
    g = build_affect_guidance(perceive("외롭고 우울해"))
    assert "검증" in g or "인정" in g  # validation-first guidance


def test_guidance_is_nonempty_for_all_postures():
    for msg in ["합격했어", "우울해", "지쳤어", "어떻게 해?", "밥 먹었다"]:
        g = build_affect_guidance(perceive(msg))
        assert g and "대화 태도 가이드" in g
