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
) -> str:
    """Build the compact cognitive-guidance block for the system prompt.

    safety_guidance (leukocyte) and debias_guidance (mediator), when present,
    are surfaced prominently — safety first — so the persona's reply respects
    them. They are produced by the pure conscience/debias gates.

    conversation_guidance (the relationship/mood/principles block) carries the
    human-conversation-psychology guidance: how to converse given the current
    Social-Penetration level, the recent mood, and which of the ten principles
    apply this turn.
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
        f"- 참고 소스: {search_notes}",
    ]
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
    # Safety (leukocyte) comes first when present — it outranks everything.
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
