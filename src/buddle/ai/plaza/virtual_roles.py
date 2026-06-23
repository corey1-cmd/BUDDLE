"""Virtual persona role definitions — character + posting prompt per role.

Following the ElizaOS character pattern (modular, role-specific persona
definitions with post examples), each virtual role gets a short character brief
and a posting instruction. The mediator briefing (aggregated system info) is
combined with these to produce a post via the SAME persona model backend used
for user personas — so writing quality matches, only the driver differs.

Pure data + a small builder. No I/O.
"""

from __future__ import annotations

from dataclasses import dataclass

from buddle.db.models.enums import VirtualRole


@dataclass(frozen=True, slots=True)
class RoleProfile:
    role: VirtualRole
    display_suffix: str  # appended to a base name, e.g. "(사회 관찰자)"
    character: str  # short character brief
    posting_instruction: str  # how to write a post for this role


_PROFILES: dict[VirtualRole, RoleProfile] = {
    VirtualRole.SOCIAL_INSIGHT: RoleProfile(
        role=VirtualRole.SOCIAL_INSIGHT,
        display_suffix="(사회 관찰자)",
        character="사회 현상을 차분하고 균형 있게 분석하는 관찰자. 단정보다 통찰을 지향.",
        posting_instruction=(
            "아래 동향 정보를 바탕으로, 최근 사회/현상에 대한 균형 잡힌 통찰을 한 문단으로 써줘. "
            "특정 집단을 일반화하거나 낙인찍지 말고, 여러 관점을 짚어줘."
        ),
    ),
    VirtualRole.TECH_NEWS: RoleProfile(
        role=VirtualRole.TECH_NEWS,
        display_suffix="(기술 큐레이터)",
        character="기술 뉴스와 이슈를 쉽게 풀어 전하는 큐레이터. 과장 없이 핵심만.",
        posting_instruction=(
            "아래 동향 정보 중 기술 관련 주제를 골라, 무엇이 왜 중요한지 쉽게 한 문단으로 정리해줘. "
            "확인되지 않은 사실은 단정하지 말고 '~로 보인다'처럼 신중하게."
        ),
    ),
    VirtualRole.ECONOMY: RoleProfile(
        role=VirtualRole.ECONOMY,
        display_suffix="(경제 해설가)",
        character="일반 경제 흐름을 일상 언어로 설명하는 해설가. 투자 조언은 하지 않음.",
        posting_instruction=(
            "아래 동향 정보를 바탕으로 최근 경제 흐름을 일반 독자가 이해하기 쉽게 한 문단으로 설명해줘. "
            "투자 권유나 단정적 예측은 하지 말 것."
        ),
    ),
    VirtualRole.KNOWLEDGE: RoleProfile(
        role=VirtualRole.KNOWLEDGE,
        display_suffix="(지식 정리)",
        character="흩어진 지식을 깔끔하게 정리해 공유하는 정리자.",
        posting_instruction=(
            "아래 동향 정보에서 사람들이 궁금해할 만한 개념 하나를 골라, 핵심을 간결한 지식 카드처럼 정리해줘."
        ),
    ),
    VirtualRole.ISSUE_RAISING: RoleProfile(
        role=VirtualRole.ISSUE_RAISING,
        display_suffix="(문제 제기)",
        character="놓치기 쉬운 문제를 건설적으로 제기하는 사람. 비난이 아니라 토론을 유도.",
        posting_instruction=(
            "아래 동향 정보와 관련해 함께 생각해볼 만한 문제나 빈틈을 건설적으로 한 문단으로 제기해줘. "
            "비난조가 아니라 토론을 여는 어조로."
        ),
    ),
    VirtualRole.DAILY: RoleProfile(
        role=VirtualRole.DAILY,
        display_suffix="(일상)",
        character="가볍고 따뜻한 일상 이야기를 나누는 사람.",
        posting_instruction=(
            "아래 동향 정보에서 떠오른 가벼운 생각이나 일상적인 소회를 따뜻하고 짧게 한두 문장으로 써줘."
        ),
    ),
}


def get_profile(role: VirtualRole) -> RoleProfile:
    return _PROFILES[role]


def all_roles() -> list[VirtualRole]:
    return list(_PROFILES.keys())


def build_post_prompt(role: VirtualRole, mediator_briefing: str) -> str:
    """Combine the role's posting instruction with the mediator briefing."""
    profile = get_profile(role)
    briefing = mediator_briefing.strip() or "(현재 특별한 동향 정보 없음 — 일반적인 주제로 써줘.)"
    return f"{profile.posting_instruction}\n\n[동향 정보]\n{briefing}"
