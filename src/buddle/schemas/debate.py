"""Debate dashboard schemas — the topic debate's structured view.

Shapes the /v1/topics/{tag}/debate response: per-topic totals plus a list of
conversation axes, each with its representative claim, pro/con/neutral split,
ground/rebuttal counts, and recent-activity trend (where the axis is heading).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from buddle.services.argument_service import DashboardView


class AxisRead(BaseModel):
    """One conversation axis (대화 축) in the dashboard."""

    representative_claim: str = Field(description="이 축을 대표하는 주장")
    representative_post_id: uuid.UUID | None = Field(
        default=None, description="대표 주장이 나온 글 (대화 진입점, 직접 기여는 없음)"
    )
    claim_count: int = Field(description="이 축에 속한 주장 수")
    pro: int = Field(description="찬성 입장 주장 수")
    con: int = Field(description="반대 입장 주장 수")
    neutral: int = Field(description="중립 주장 수")
    ground_count: int = Field(description="이 축을 뒷받침하는 근거 수")
    rebuttal_count: int = Field(description="이 축에 대한 반박 수")
    recent_claims: int = Field(description="최근 7일 내 새 주장 수 (흐름)")


class DebateDashboardRead(BaseModel):
    """The full topic debate dashboard."""

    topic_tag_id: uuid.UUID
    topic_name: str = Field(description="화제(태그) 이름")
    total_claims: int
    total_grounds: int
    total_rebuttals: int
    total_questions: int
    axes: list[AxisRead] = Field(default_factory=list, description="대화 축 (최대 5개)")

    @classmethod
    def from_view(cls, view: DashboardView, *, topic_name: str) -> DebateDashboardRead:
        axes = [
            AxisRead(
                representative_claim=a.representative_claim,
                representative_post_id=a.representative_post_id,
                claim_count=a.claim_count,
                pro=a.pro,
                con=a.con,
                neutral=a.neutral,
                ground_count=a.ground_count,
                rebuttal_count=a.rebuttal_count,
                recent_claims=a.recent_claims,
            )
            for a in view.axes
        ]
        return cls(
            topic_tag_id=view.topic_tag_id,
            topic_name=topic_name,
            total_claims=view.total_claims,
            total_grounds=view.total_grounds,
            total_rebuttals=view.total_rebuttals,
            total_questions=view.total_questions,
            axes=axes,
        )


class DebateTopicRequest(BaseModel):
    """Promote a post into a debate topic seed.

    topic_name is optional: when omitted, the post's first existing tag is used;
    if the post has no tags either, the request is rejected (400) asking for one.
    """

    topic_name: str | None = Field(
        default=None, max_length=64, description="토론 화제 이름 (비우면 글의 첫 태그 사용)"
    )


class DebateTopicCreated(BaseModel):
    """Result of seeding a debate from a post."""

    tag_id: uuid.UUID
    topic_name: str
    seeded_units: int = Field(description="이 글에서 토론에 추가된 논증 유닛 수")


# ── Opposition geometry (대립구조 시각화) ────────────────────────────────────


class GeoNodeRead(BaseModel):
    """One positioned element in the opposition geometry (0..1 coords)."""

    kind: str
    x: float
    y: float
    radius: float
    stance: str
    label: str = ""
    weight: int = 0


class GeoEdgeRead(BaseModel):
    """A connection between geometry nodes."""

    x1: float
    y1: float
    x2: float
    y2: float
    kind: str


class OppositionRead(BaseModel):
    """The geometric opposition view for a topic."""

    topic_tag_id: uuid.UUID
    topic_name: str
    opposition_type: str = Field(description="binary | spectrum | multipolar | tension")
    nodes: list[GeoNodeRead] = Field(default_factory=list)
    edges: list[GeoEdgeRead] = Field(default_factory=list)
    pro_total: int = 0
    con_total: int = 0
    neutral_total: int = 0
    summary: str = ""

    @classmethod
    def from_view(
        cls, view: object, *, topic_tag_id: uuid.UUID, topic_name: str
    ) -> OppositionRead:
        return cls(
            topic_tag_id=topic_tag_id,
            topic_name=topic_name,
            opposition_type=getattr(getattr(view, "opposition_type", None), "value", "spectrum"),
            nodes=[
                GeoNodeRead(
                    kind=n.kind,
                    x=n.x,
                    y=n.y,
                    radius=n.radius,
                    stance=n.stance,
                    label=n.label,
                    weight=n.weight,
                )
                for n in getattr(view, "nodes", [])
            ],
            edges=[
                GeoEdgeRead(x1=e.x1, y1=e.y1, x2=e.x2, y2=e.y2, kind=e.kind)
                for e in getattr(view, "edges", [])
            ],
            pro_total=getattr(view, "pro_total", 0),
            con_total=getattr(view, "con_total", 0),
            neutral_total=getattr(view, "neutral_total", 0),
            summary=getattr(view, "summary", ""),
        )


class GraphNodeRead(BaseModel):
    """One node in the Kialo-style argument graph (hierarchical via parent_id)."""

    id: str
    kind: str = Field(description="claim | dimension | ground | evidence | rebuttal | question")
    text: str
    stance: str = "neutral"
    parent_id: str | None = None
    dimension: str = Field(default="claim", description="problem | cause | solution | claim")
    depth: int = 0
    weight: int = 1


class ArgumentGraphRead(BaseModel):
    """The argument graph for a topic — claim-rooted hierarchy."""

    topic_tag_id: uuid.UUID
    topic_name: str
    nodes: list[GraphNodeRead] = Field(default_factory=list)
    claim_count: int = 0
    ground_count: int = 0
    rebuttal_count: int = 0
    evidence_count: int = 0
    summary: str = ""

    @classmethod
    def from_view(
        cls, view: object, *, topic_tag_id: uuid.UUID, topic_name: str
    ) -> ArgumentGraphRead:
        return cls(
            topic_tag_id=topic_tag_id,
            topic_name=topic_name,
            nodes=[
                GraphNodeRead(
                    id=n.id,
                    kind=getattr(n.kind, "value", str(n.kind)),
                    text=n.text,
                    stance=n.stance,
                    parent_id=n.parent_id,
                    dimension=getattr(n.dimension, "value", str(n.dimension)),
                    depth=n.depth,
                    weight=n.weight,
                )
                for n in getattr(view, "nodes", [])
            ],
            claim_count=getattr(view, "claim_count", 0),
            ground_count=getattr(view, "ground_count", 0),
            rebuttal_count=getattr(view, "rebuttal_count", 0),
            evidence_count=getattr(view, "evidence_count", 0),
            summary=getattr(view, "summary", ""),
        )


class StanceContribution(BaseModel):
    """Add a claim (and optional grounds) on a chosen side of a topic."""

    stance: Literal["pro", "con", "neutral"] = Field(description="택한 편")
    claim: str = Field(min_length=2, max_length=500, description="주장")
    grounds: list[str] = Field(default_factory=list, max_length=5, description="근거 (최대 5개)")

class StanceContributionByName(BaseModel):
    """Same as StanceContribution, but for callers that only have a topic
    *name* (e.g. a chat's current topic chip), not a tag_id. The tag is
    get-or-created from the name."""

    topic_name: str = Field(min_length=1, max_length=64, description="화제 이름")
    stance: Literal["pro", "con", "neutral"] = Field(description="택한 편")
    claim: str = Field(min_length=2, max_length=500, description="주장")
    grounds: list[str] = Field(default_factory=list, max_length=5, description="근거 (최대 5개)")


class StanceAccepted(BaseModel):
    """Result of contributing a stance to a topic's debate."""

    tag_id: uuid.UUID
    units_added: int
