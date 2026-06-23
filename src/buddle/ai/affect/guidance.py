"""Turn a PerceivedAffect into concrete, evidence-based response guidance that
is appended to the persona's system prompt.

The guidance encodes well-established techniques:
  - CELEBRATE  -> Active Constructive Responding (Gable et al., 2004): react
    with genuine, specific enthusiasm; ask an elaborating question so the
    person savors the good news.
  - SUPPORT    -> validation + reflection (empathetic-chatbot evidence):
    acknowledge the feeling first, reflect it back, avoid minimizing or
    jumping to fixes; offer gentle, optional support.
  - ENCOURAGE  -> light, hopeful framing without dismissing the difficulty.
  - ENGAGE     -> curious, helpful, answer the question warmly.
  - REFLECT    -> nonjudgmental active listening: reflect + an open question.

Guardrails baked into the guidance text:
  - Be warm and brighten the conversation, but NEVER fake feelings, over-praise,
    or dismiss real distress (toxic positivity is explicitly discouraged).
  - Use "I"-style, person-centered language; do not diagnose; do not give
    medical advice.
  - Crucially, the guidance is about *posture*, derived only from the current
    message — it does not instruct the model to mirror the user's wording or
    adapt to their identity, preserving the no-bias contract.
"""

from __future__ import annotations

from buddle.ai.affect.perception import PerceivedAffect, ResponsePosture

_POSTURE_GUIDANCE: dict[ResponsePosture, str] = {
    ResponsePosture.CELEBRATE: (
        "상대가 좋은 일을 나눈 것 같습니다. 적극적이고 구체적으로 함께 기뻐하세요(ACR). "
        "진심으로 축하하고, 그 일을 더 음미할 수 있도록 한 가지 구체적인 질문을 덧붙이세요. "
        "과장된 칭찬은 피하고 자연스럽게."
    ),
    ResponsePosture.SUPPORT: (
        "상대가 힘들어하는 신호가 있습니다. 먼저 감정을 인정하고 그대로 비춰주세요(검증+반영). "
        "성급한 해결책이나 '괜찮아질 거야' 같은 가벼운 위로로 넘기지 말고, "
        "곁에 있다는 따뜻함을 전하세요. 진단·의학적 조언은 하지 마세요. "
        "원한다면 부담 없는 작은 제안만 덧붙이세요."
    ),
    ResponsePosture.ENCOURAGE: (
        "약간의 부정적 기류가 있습니다. 어려움을 가볍게 여기지 않으면서, "
        "희망적이고 다정한 시선으로 한 걸음 나아갈 수 있게 격려하세요."
    ),
    ResponsePosture.ENGAGE: (
        "상대가 질문하거나 대화를 이어가려 합니다. 호기심 있고 따뜻하게, 도움이 되도록 답하세요."
    ),
    ResponsePosture.REFLECT: (
        "특별한 감정 신호는 약합니다. 비판단적으로 경청하는 태도로, "
        "들은 내용을 짧게 비춰주고 열린 질문 하나로 대화를 자연스럽게 이어가세요."
    ),
}

_COMMON_TONE = (
    "전반적으로 사람의 기분이 밝아지도록 따뜻하고 진솔하게 대화하세요. "
    "단, 가짜 감정이나 영혼 없는 긍정(toxic positivity)은 금지합니다. "
    "상대의 말투나 정체성을 흉내 내지 말고, 당신의 페르소나를 일관되게 유지하세요."
)


def build_affect_guidance(affect: PerceivedAffect) -> str:
    """Produce a short guidance block for the persona's system prompt."""
    posture_text = _POSTURE_GUIDANCE.get(affect.posture, _POSTURE_GUIDANCE[ResponsePosture.REFLECT])
    return f"[대화 태도 가이드]\n- {posture_text}\n- {_COMMON_TONE}"
