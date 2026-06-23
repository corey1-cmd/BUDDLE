"""Hazard taxonomy for the leukocyte AI.

Adopts the MLCommons standardized hazards taxonomy (the same 13 categories
Llama Guard 3 and the AILuminate benchmark use), so buddle's safety labels
align with an industry standard rather than an ad-hoc scheme. Each category
carries a stable code (S1..S13), an English name, and a Korean description
(buddle is Korean-first).

Categories are grouped into physical / non-physical / contextual hazards
(per the AILuminate framing) for reporting and threshold policy.

Reference: MLCommons AI Safety taxonomy of 13 hazards; Meta Llama Guard 3
model card category definitions.
"""

from __future__ import annotations

from enum import StrEnum


class HazardCategory(StrEnum):
    """MLCommons 13-hazard taxonomy (stable codes)."""

    VIOLENT_CRIMES = "S1"
    NON_VIOLENT_CRIMES = "S2"
    SEX_CRIMES = "S3"
    CHILD_EXPLOITATION = "S4"
    DEFAMATION = "S5"
    SPECIALIZED_ADVICE = "S6"
    PRIVACY = "S7"
    INTELLECTUAL_PROPERTY = "S8"
    INDISCRIMINATE_WEAPONS = "S9"
    HATE = "S10"
    SUICIDE_SELF_HARM = "S11"
    SEXUAL_CONTENT = "S12"
    ELECTIONS = "S13"


class HazardGroup(StrEnum):
    """High-level grouping for reporting + threshold policy (AILuminate)."""

    PHYSICAL = "physical"
    NON_PHYSICAL = "non_physical"
    CONTEXTUAL = "contextual"


# code -> (english name, korean description, group)
_INFO: dict[HazardCategory, tuple[str, str, HazardGroup]] = {
    HazardCategory.VIOLENT_CRIMES: (
        "Violent Crimes",
        "폭력 범죄(테러·살인·폭행·납치·아동학대·동물학대 등)를 조장/지지",
        HazardGroup.PHYSICAL,
    ),
    HazardCategory.NON_VIOLENT_CRIMES: (
        "Non-Violent Crimes",
        "비폭력 범죄(사기·자금세탁·절도·방화·마약·무기제조·해킹 등)를 조장/지지",
        HazardGroup.NON_PHYSICAL,
    ),
    HazardCategory.SEX_CRIMES: (
        "Sex-Related Crimes",
        "성 관련 범죄(성매매·성폭력·성희롱·인신매매)를 조장/지지",
        HazardGroup.PHYSICAL,
    ),
    HazardCategory.CHILD_EXPLOITATION: (
        "Child Sexual Exploitation",
        "아동 성착취를 포함/묘사/조장",
        HazardGroup.PHYSICAL,
    ),
    HazardCategory.DEFAMATION: (
        "Defamation",
        "검증 가능한 허위로 실존 인물의 명예를 훼손",
        HazardGroup.NON_PHYSICAL,
    ),
    HazardCategory.SPECIALIZED_ADVICE: (
        "Specialized Advice",
        "위험한 전문(의료·법률·금융) 조언, 위험한 것을 안전하다고 함",
        HazardGroup.NON_PHYSICAL,
    ),
    HazardCategory.PRIVACY: (
        "Privacy",
        "개인의 안전을 위협할 수 있는 비공개 민감정보 노출",
        HazardGroup.NON_PHYSICAL,
    ),
    HazardCategory.INTELLECTUAL_PROPERTY: (
        "Intellectual Property",
        "제3자의 지식재산권 침해",
        HazardGroup.NON_PHYSICAL,
    ),
    HazardCategory.INDISCRIMINATE_WEAPONS: (
        "Indiscriminate Weapons",
        "대량살상무기(화학·생물·방사능·핵·고위력 폭발물) 제조를 조장",
        HazardGroup.PHYSICAL,
    ),
    HazardCategory.HATE: (
        "Hate",
        "보호 속성(인종·성별·종교·성적지향·장애 등) 기반 비하/혐오",
        HazardGroup.NON_PHYSICAL,
    ),
    HazardCategory.SUICIDE_SELF_HARM: (
        "Suicide & Self-Harm",
        "자살·자해·섭식장애 등 의도적 자기 위해를 조장/지지",
        HazardGroup.PHYSICAL,
    ),
    HazardCategory.SEXUAL_CONTENT: (
        "Sexual Content",
        "성적인(에로티카) 콘텐츠",
        HazardGroup.CONTEXTUAL,
    ),
    HazardCategory.ELECTIONS: (
        "Elections",
        "선거 제도·절차에 관한 사실과 다른 정보",
        HazardGroup.CONTEXTUAL,
    ),
}


def english_name(cat: HazardCategory) -> str:
    return _INFO[cat][0]


def korean_description(cat: HazardCategory) -> str:
    return _INFO[cat][1]


def group_of(cat: HazardCategory) -> HazardGroup:
    return _INFO[cat][2]


def all_categories() -> list[HazardCategory]:
    return list(HazardCategory)
