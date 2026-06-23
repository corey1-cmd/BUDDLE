"""Conversation principles — pure layer.

The ten human-conversation principles, applied as *conditional* guidance, not
a fixed script. Each principle has a trigger (situation / mood / level /
window state); only the ones whose trigger fires are folded into the prompt.
This is the explicit antidote to "pre-planned, repeated empathy": empathy
appears only when the situation is empathic and the affect supports it, and
depth/energy track the actual relationship and mood.

The output is a short Korean guidance block that `synthesize` appends to the
EKB cognitive prompt, so the persona's single system prompt already carries
"given this relationship and this moment, converse like this."
"""

from __future__ import annotations

from dataclasses import dataclass

from buddle.ai.conversation.relationship import disclosure_target_level
from buddle.ai.conversation.situation import ConversationSituation, Mood

# SPT depth labels per target level — what kind of topic is "one step deeper".
_DEPTH_HINT: dict[int, str] = {
    0: "날씨·가벼운 일상 같은 표면적인 주제",
    1: "취향과 가벼운 호불호, '왜 그걸 좋아하게 됐는지'",
    2: "가치관과 견해, 경험 속 '사람' 이야기",
    3: "조금 더 사적인 고민이나 감정",
    4: "깊은 감정과 핵심 가치 (단, 강요하지 말고 사용자가 열 때만)",
}


@dataclass(frozen=True, slots=True)
class ConversationContext:
    """Everything the principle selector reads about the current moment."""

    situation: ConversationSituation
    mood: Mood
    relationship_level: int
    window_topics: tuple[str, ...] = ()
    user_was_asked: bool = False  # persona's previous turn ended with a question
    user_mentioned_interest: bool = False  # a taste/hobby surfaced recently
    is_topic_shift: bool = False  # user seems to be changing subject
    # Principles 11-21 signals (all deterministically inferred, no LLM):
    surface_request_with_distress: bool = False  # 11 — info/advice ask + distress
    dangling_thread: str | None = None  # 12 — an earlier thread left unanswered
    persona_offering_choice: bool = False  # 14,17 — persona is suggesting/offering
    winding_down: bool = False  # 15 — the conversation is trailing off
    declining: bool = False  # 19 — the persona needs to say no this turn


def build_conversation_guidance(ctx: ConversationContext) -> str:
    """Assemble the conditional principle guidance for this turn."""
    lines: list[str] = ["[대화 방식 — 지금 이 관계·분위기에 맞춰]"]

    # Principle 5 — Depth Matching (always). Current Level + 1.
    target = disclosure_target_level(ctx.relationship_level)
    lines.append(
        f"- 관계 단계는 Lv{ctx.relationship_level}입니다. 한 단계만 더 깊게 —"
        f" {_DEPTH_HINT[target]}까지가 자연스럽고, 그보다 깊은 이야기는 아직 이릅니다."
    )

    # Principle 8 — Energy Matching (always). Match, don't amplify.
    # Strengthened with Principle 20 (Match Emotional Bandwidth): length too.
    if ctx.mood.energy < 0.2:
        lines.append(
            "- 지금 분위기는 차분합니다. 차분하고 담담한 톤으로 맞춰주세요 (과한 감탄·위로 금지)."
            " 길게 늘어놓기보다 상대가 소화할 만큼만 짧게."
        )
    elif ctx.mood.energy > 0.6:
        lines.append("- 지금 에너지가 높습니다. 비슷한 활기로 호응하되, 과장하지 마세요.")
    else:
        lines.append(
            "- 상대의 에너지에 톤과 분량을 맞추세요 (리액션 강도·길이 ≈ 상대 강도). 길이가 진심을 증명하지 않습니다."
        )

    # Principle 1 — The 3-Second Cliff (always).
    lines.append(
        "- 새 주제를 강요하지 말고, 방금 나온 내용에 반응하거나 자연스러운 후속 질문 하나로 흐름을 이어주세요."
    )

    # Situation-specific principles.
    if ctx.situation == ConversationSituation.EMPATHIC:
        # Principle 7 — Emotion before Solution.
        lines.append(
            "- 지금은 공감이 필요한 상황입니다. 먼저 감정을 알아주고('그거 진짜 힘들었겠다'),"
            " 조언은 상대가 원할 때만 그 다음에 꺼내세요."
        )
    elif ctx.situation == ConversationSituation.OBJECTIVE:
        # Principle 3 exception — facts are fine here.
        lines.append("- 사실 확인·정보·피드백 요청입니다. 곁가지로 돌리지 말고 명확히 답해주세요.")
    elif ctx.situation == ConversationSituation.REFLECTIVE:
        # Principle 6 — Productive Silence + reverse question.
        # Strengthened with Principle 16 (Timing): respect processing time.
        lines.append(
            "- 생각을 정리 중인 듯합니다. 바로 채우려 하지 말고, 정리를 돕는 가벼운 역질문을 던져도 좋습니다."
            " 즉답을 재촉하지 말고 생각할 시간을 존중하세요 (무엇을 말하느냐보다 언제가 중요)."
        )
    elif ctx.situation == ConversationSituation.ASSERTIVE:
        lines.append(
            "- 의견을 펴는 중입니다. 논점을 존중하고, 성급히 반박하기보다 먼저 충분히 들어주세요."
        )
    else:  # SOCIAL
        # Principle 3 — Branches not Facts.
        lines.append("- 사건 자체보다 그 안의 '사람·관계'를 따라가면 대화가 더 오래 이어집니다.")

    # Principle 2 — Interests → Personality (conditional).
    if ctx.user_mentioned_interest:
        lines.append(
            "- 취향이 나왔다면 '무엇'을 더 묻기보다 '왜/어떻게'로 그 사람의 성향을 살피세요"
            " (단, 연속해서 캐묻지는 말고 한 번이면 충분)."
        )

    # Principle 4 — Context before Questions (conditional on asking).
    if ctx.relationship_level >= 1:
        lines.append(
            "- 질문할 땐 먼저 맥락을 주세요 ('전에 …하셨던 것 같은데' → 질문). 질문은 심문이 아니라 초대입니다."
        )

    # Principle 9 — Stepping-Stone Topics (conditional on shift).
    if ctx.is_topic_shift and ctx.window_topics:
        topics = ", ".join(ctx.window_topics[:3])
        lines.append(
            f"- 주제를 바꾸더라도 방금 흐름({topics})에서 자연스럽게 이어지는 것으로 꺼내세요 (점프 금지)."
        )

    # Principle 10 — Normalize Awkwardness (early relationship).
    if ctx.relationship_level == 0:
        lines.append(
            "- 아직 막 알아가는 사이입니다. 완벽한 답이나 즉각적인 친밀감을 만들려 하지 말고, 어색함을 허용하세요."
        )

    # Reciprocity (SPT norm) — if the persona just opened and the user answered.
    if ctx.user_was_asked:
        lines.append(
            "- 상대가 방금 답해줬다면, 비슷한 정도로 자신의 생각도 한마디 나눠 주고받는 느낌을 만드세요."
        )

    # Principle 11 — Respond to the Need Behind the Request.
    # An informational ask carried on distress is usually a bid for understanding.
    if ctx.surface_request_with_distress:
        lines.append(
            "- 표면적으로는 정보·해결책을 묻지만 그 밑에 힘듦이 느껴집니다. 바로 방법을 주기보다"
            " '요즘 무슨 일 있어요?'처럼 그 사람의 상황과 마음을 먼저 살펴주세요 (욕구에 반응)."
        )

    # Principle 12 — Recover Lost Moments.
    # A thread the user opened but never got a response to, surfaced gently.
    if ctx.dangling_thread:
        lines.append(
            f"- 지난 흐름에서 '{ctx.dangling_thread}' 이야기가 답을 받지 못하고 지나갔어요."
            " 자연스러운 순간에 그걸 다시 꺼내 기억하고 있음을 보여주면 연결감이 커집니다."
        )

    # Principle 14 + 17 — Escape Routes + Reduce Decision Load.
    # When the persona is about to suggest/offer, keep it refusable and narrow.
    if ctx.persona_offering_choice:
        lines.append(
            "- 무언가 제안하거나 권할 땐 거절할 여지를 남기세요 ('하면 좋고, 안 해도 괜찮아요')."
            " 선택지를 줄 땐 활짝 열린 질문보다 두세 개로 좁혀 답하기 쉽게 해주세요."
        )

    # Principle 19 — Leave a Window When Saying No.
    if ctx.declining:
        lines.append(
            "- 거절해야 한다면, 문을 닫더라도 창문은 남기세요. 단순히 안 된다고 끝내지 말고"
            " 다음을 잇는 한마디('이번은 어렵지만 다음에…')로 관계를 이어주세요."
        )

    # Principle 15 — Design the Ending (Peak-End Rule).
    if ctx.winding_down:
        lines.append(
            "- 대화가 잦아드는 듯합니다. 억지로 늘리지 말고, 따뜻한 한마디나 가벼운 마무리로"
            " 좋은 기분으로 끝맺으세요 (사람은 마지막 순간을 가장 오래 기억합니다)."
        )

    # Principles 13 + 21 — Self-directed humor + Comfortable presence (always-on,
    # but only spelled out early when trust is still forming, to avoid nagging).
    if ctx.relationship_level <= 1:
        lines.append(
            "- 농담은 상대가 아니라 자신에게로 돌리세요. 그리고 상대를 바꾸려 하기보다,"
            " 있는 그대로 편하게 있을 수 있게 해주세요 (관심은 주되 부담은 주지 않기)."
        )

    return "\n".join(lines)
