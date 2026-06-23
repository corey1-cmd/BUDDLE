"""Relationship schema — the user-facing shape of a persona<->user bond.

Surfaces the Social-Penetration level with its human-readable stage and a
coarse closeness percentage. The raw affinity score and turn tallies are
included for transparency (the user can see why the bond is where it is), but
the UI shows mainly the level + label, kept quiet and non-gamified.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# Social-Penetration stage labels, indexed by level (0..4). Mirrors
# buddle.ai.conversation.RelationshipLevel and the chat UI's REL_LABELS.
STAGE_LABELS: tuple[str, ...] = (
    "막 알아가는 사이",  # 0 orientation
    "조금씩 친해지는 중",  # 1 exploratory
    "마음을 나누는 사이",  # 2 affective
    "편안하고 가까운 사이",  # 3 stable
    "깊이 신뢰하는 사이",  # 4 intimate
)


class RelationshipRead(BaseModel):
    """Current state of the persona<->user bond."""

    level: int = Field(ge=0, le=4, description="Social Penetration 단계 (0~4)")
    stage_label: str = Field(description="단계의 한국어 표현")
    affinity_score: float = Field(description="정서은행계좌 점수 (0~100)")
    closeness_pct: int = Field(ge=0, le=100, description="점수를 백분율로 표현")
    positive_turns: int
    negative_turns: int
    turn_count: int
    mood_valence: float = Field(description="최근 대화 분위기 (-1~1)")
    mood_energy: float = Field(description="최근 대화 에너지 (0~1)")

    @classmethod
    def from_relationship(cls, rel: object) -> RelationshipRead:
        level = int(getattr(rel, "level", 0))
        score = float(getattr(rel, "affinity_score", 0.0))
        return cls(
            level=level,
            stage_label=STAGE_LABELS[max(0, min(4, level))],
            affinity_score=round(score, 2),
            closeness_pct=round(max(0.0, min(100.0, score))),
            positive_turns=int(getattr(rel, "positive_turns", 0)),
            negative_turns=int(getattr(rel, "negative_turns", 0)),
            turn_count=int(getattr(rel, "turn_count", 0)),
            mood_valence=round(float(getattr(rel, "mood_valence", 0.0)), 3),
            mood_energy=round(float(getattr(rel, "mood_energy", 0.0)), 3),
        )

    @classmethod
    def neutral(cls) -> RelationshipRead:
        """The default bond (no turns yet) — orientation stage at zero."""
        return cls(
            level=0,
            stage_label=STAGE_LABELS[0],
            affinity_score=0.0,
            closeness_pct=0,
            positive_turns=0,
            negative_turns=0,
            turn_count=0,
            mood_valence=0.0,
            mood_energy=0.0,
        )
