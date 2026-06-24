"""Synthesize the cognitive pipeline output into a compact prompt block.

Cost discipline: the staged analysis is rich, but we compress it into a short,
structured Korean block before injecting it into the single response-generation
call. This avoids both extra LLM calls (cost) and prompt bloat /
"lost-in-the-middle" (quality). The block tells the persona what was
understood and which response strategy to take — not a transcript of every
internal field.

Strategy -> concrete guidance reuses the evidence-based techniques already
encoded for affect (ACR, validation, active listening), so behavior is
consistent across the affect and cognition layers.
"""

from __future__ import annotations

from buddle.ai.cognition.signals import (
    DecisionResult,
    InformationProcessingResult,
    ResponseStrategy,
)
from buddle.ai.cognition.user_context import UserContextFact, render_context_block

_STRATEGY_GUIDANCE: dict[ResponseStrategy, str] = {
    ResponseStrategy.CELEBRATE: (
        "좋은 소식에 적극적·구체적으로 함께 기뻐하세요(ACR). 진심으로 축하하고 "
        "더 음미할 수 있는 질문 하나를 덧붙이되 과장은 피하세요."
    ),
    ResponseStrategy.COMFORT: (
        "감정을 먼저 인정하고 그대로 비춰주세요(검증+반영). 성급한 해결이나 가벼운 "
        "위로로 넘기지 말고 곁에 있다는 따뜻함을 전하세요. 진단·의학적 조언은 금지."
    ),
    ResponseStrategy.INFORM: (
        "질문의 핵심에 명확하고 정확하게 답하세요. 모르면 솔직히 말하고, 따뜻한 어조를 유지하세요."
    ),
    ResponseStrategy.ASSIST: (
        "요청한 작업을 돕거나 수행하세요. 필요한 정보가 빠졌다면 짧게 되묻고, 협조적으로 진행하세요."
    ),
    ResponseStrategy.CLARIFY: (
        "메시지가 모호합니다. 비판단적으로, 무엇을 원하는지 부드럽게 한 가지만 되물어 명확히 하세요."
    ),
    ResponseStrategy.CONVERSE: (
        "따뜻하고 열린 태도로 대화를 이어가세요. 들은 내용을 짧게 비추고 자연스러운 질문 하나를 더하세요."
    ),
}

_COMMON_TONE = (
    "전반적으로 사람의 기분이 밝아지도록 진솔하고 따뜻하게 대화하세요. "
    "가짜 감정이나 영혼 없는 긍정(toxic positivity)은 금지하고, 상대의 말투·정체성을 "
    "흉내 내지 말고 당신의 페르소나를 일관되게 유지하세요."
)


def synthesize_prompt_block(
    info: InformationProcessingResult,
    decision: DecisionResult,
    *,
    safety_guidance: str = "",
    debias_guidance: str = "",
    conversation_guidance: str = "",
    user_context: UserContextFact | None = None,
    caution_guidance: str = "",
) -> str:
    """Build the compact cognitive-guidance block for the system prompt.

    우선순위 (높은 것이 먼저):
      1. caution_guidance  — 백혈구 AI 7단계 추론 (유의 단어 감지 시)
      2. safety_guidance   — conscience gate (자해·타해 신호)
      3. debias_guidance   — mediator 편향 완화
      4. user_context      — 사용자 공개 사실 (EKB Search 내부 탐색 결과)
      5. conversation_guidance — 관계/분위기 대화 원칙
      6. response strategy — 최종 응답 전략

    caution_guidance가 존재하면 7단계 추론을 마친 뒤 응답하도록 페르소나에
    명시적으로 지시한다 (즉시 답변 금지).
    """
    guidance = _STRATEGY_GUIDANCE.get(
        decision.chosen, _STRATEGY_GUIDANCE[ResponseStrategy.CONVERSE]
    )
    topics = ", ".join(info.topics[:5]) if info.topics else "(불명확)"
    search_notes = "; ".join(decision.search.notes)

    lines = [
        "[인지 분석 — 이 메시지를 이렇게 이해했습니다]",
        f"- 의도: {info.intent.value} / 감정: {info.affect.valence.value}"
        f" (강도 {info.affect.intensity:.2f})",
        f"- 핵심 주제: {topics}",
        f"- 다룰 점: {decision.problem}",
        f"- 탐색(내부·외부): {search_notes}",
    ]
    # EKB Search — 사용자 공개 정보 (내부 탐색 결과).
    # UserContextFact는 Search 단계에서 "이 사람에 대해 이미 아는 것"으로 조회됨.
    # 사실(이름·위치 등)만 포함; 의견·말투는 포함되지 않음.
    if user_context:
        context_block = render_context_block(user_context)
        if context_block:
            lines.append(context_block)
    # Long-term memory (EKB internal search results). Reference material, not
    # instructions: surface naturally, never enumerate or show off recall.
    if decision.search.recalled:
        lines.append("[장기 기억 — 예전 대화에서 이 사용자에 대해 기억하는 것]")
        for mem in decision.search.recalled[:5]:
            lines.append(f"- {mem[:120]}")
        lines.append(
            "- 위 기억은 자연스럽게만 활용하세요. 기억을 나열하거나 '기억하고 있다'고 "
            "과시하지 말고, 대화에 도움이 될 때만 부드럽게 반영하세요."
        )
    # 백혈구 AI 7단계 추론 (최우선 — 즉시 답변 금지 지시 포함).
    if caution_guidance:
        lines.insert(0, caution_guidance)
    # Safety (leukocyte conscience) — 자해·타해 신호 처리.
    if safety_guidance:
        lines.append(safety_guidance)
    if debias_guidance:
        lines.append(debias_guidance)
    # Conversation psychology: how to converse given the relationship + mood.
    if conversation_guidance:
        lines.append(conversation_guidance)
    lines.extend(
        [
            "[응답 전략]",
            f"- {guidance}",
            f"- {_COMMON_TONE}",
        ]
    )
    return "\n".join(lines)
