"""Opposition geometry — pure layer (no I/O, no LLM).

Turns a topic's stance distribution into a geometric opposition view. Grounded
in the research on argument/opposition visualization:

  * Binary opposition (Saussure) — mutually exclusive poles.
  * Spectrum (Butler) — gradations along a continuum, not a rigid dichotomy.
  * Multipolar (Dung's argumentation frameworks) — 3+ coexisting positions.
  * Dialectical tension (Baxter & Montgomery) — opposites that coexist
    unresolved.

And, crucially, by Holder & Bearfield (2023) — simple red-vs-blue opposition
visuals *amplify* polarization. buddle is a connection-first 공론장, so the
geometry shows "many angles on one question" rather than two camps colliding:
a central thesis with positions around it, a continuous spectrum by default,
and the willow palette instead of political red/blue.

This module is deterministic: same distribution → same coordinates. It only
computes the abstract shape (normalized 0..1 coordinates + roles); the SVG is
drawn on the frontend from these primitives.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum


class OppositionType(StrEnum):
    """Which geometric form best fits the topic's opposition structure."""

    BINARY = "binary"  # facing arcs — two dominant poles, thin middle
    SPECTRUM = "spectrum"  # stance band — continuous distribution (default)
    MULTIPOLAR = "multipolar"  # radial constellation — 3+ axes
    TENSION = "tension"  # yin-yang — balanced poles that rebut each other


class StanceBucket(StrEnum):
    """Five-level stance, refining the 3-way pro/con/neutral into a spectrum."""

    STRONG_CON = "strong_con"
    CON = "con"
    NEUTRAL = "neutral"
    PRO = "pro"
    STRONG_PRO = "strong_pro"


# Spectrum position for each bucket, left (con) → right (pro), in 0..1.
_BUCKET_X: dict[StanceBucket, float] = {
    StanceBucket.STRONG_CON: 0.04,
    StanceBucket.CON: 0.27,
    StanceBucket.NEUTRAL: 0.50,
    StanceBucket.PRO: 0.73,
    StanceBucket.STRONG_PRO: 0.96,
}


@dataclass(frozen=True, slots=True)
class StanceDistribution:
    """Counts per bucket + supporting stats used to pick a geometry."""

    strong_con: int = 0
    con: int = 0
    neutral: int = 0
    pro: int = 0
    strong_pro: int = 0
    axis_count: int = 1  # conversation axes for this topic
    rebuttal_count: int = 0

    @property
    def total(self) -> int:
        return self.strong_con + self.con + self.neutral + self.pro + self.strong_pro

    @property
    def pro_side(self) -> int:
        return self.pro + self.strong_pro

    @property
    def con_side(self) -> int:
        return self.con + self.strong_con

    def count(self, bucket: StanceBucket) -> int:
        return {
            StanceBucket.STRONG_CON: self.strong_con,
            StanceBucket.CON: self.con,
            StanceBucket.NEUTRAL: self.neutral,
            StanceBucket.PRO: self.pro,
            StanceBucket.STRONG_PRO: self.strong_pro,
        }[bucket]


@dataclass(frozen=True, slots=True)
class GeoNode:
    """One positioned element in the opposition geometry (normalized 0..1)."""

    kind: str  # "thesis" | "claim-cluster" | "pole" | "axis"
    x: float
    y: float
    radius: float  # 0..1, scaled to claim weight
    stance: str  # bucket value or "thesis"
    label: str = ""
    weight: int = 0  # claims represented


@dataclass(frozen=True, slots=True)
class GeoEdge:
    """A connection between two nodes (support solid / rebuttal dashed)."""

    x1: float
    y1: float
    x2: float
    y2: float
    kind: str  # "support" | "rebuttal" | "hinge"


@dataclass(frozen=True, slots=True)
class OppositionView:
    """The full geometric opposition view for a topic."""

    opposition_type: OppositionType
    nodes: list[GeoNode] = field(default_factory=list)
    edges: list[GeoEdge] = field(default_factory=list)
    pro_total: int = 0
    con_total: int = 0
    neutral_total: int = 0
    summary: str = ""


def classify_opposition(dist: StanceDistribution) -> OppositionType:
    """Pick the geometry that best represents this opposition structure.

    Order of checks matters:
      1. 3+ axes → MULTIPOLAR (a debate that genuinely branched).
      2. Balanced poles + heavy mutual rebuttal → TENSION (locked, coexisting).
      3. Poles dominant + thin middle → BINARY (two camps).
      4. otherwise → SPECTRUM (the connection-first default).
    """
    total = dist.total
    if total == 0:
        return OppositionType.SPECTRUM
    if dist.axis_count >= 3 and total >= 6:
        return OppositionType.MULTIPOLAR

    pro, con = dist.pro_side, dist.con_side
    poles = pro + con
    middle = dist.neutral
    balanced = poles > 0 and min(pro, con) / max(pro, con) >= 0.6 if max(pro, con) else False

    # Tension: poles balanced AND lots of rebuttal relative to size.
    if balanced and poles >= 4 and dist.rebuttal_count >= max(2, poles // 2):
        return OppositionType.TENSION

    # Binary: the two poles dominate and the middle is thin.
    if poles >= 3 and middle <= max(1, total // 5) and min(pro, con) >= 1:
        return OppositionType.BINARY

    return OppositionType.SPECTRUM


def _radius_for(weight: int, max_weight: int) -> float:
    """Map a claim weight to a node radius in [0.03, 0.13] (sqrt for area-fair)."""
    if max_weight <= 0:
        return 0.05
    frac = math.sqrt(weight) / math.sqrt(max_weight)
    return 0.03 + 0.10 * frac


def _spectrum_view(dist: StanceDistribution) -> OppositionView:
    """Stance band: positions along a continuous con→pro axis (the default)."""
    buckets = list(StanceBucket)
    max_w = max((dist.count(b) for b in buckets), default=0)
    nodes: list[GeoNode] = []
    for b in buckets:
        w = dist.count(b)
        if w == 0:
            continue
        nodes.append(
            GeoNode(
                kind="claim-cluster",
                x=_BUCKET_X[b],
                y=0.5,
                radius=_radius_for(w, max_w),
                stance=b.value,
                weight=w,
            )
        )
    return OppositionView(
        opposition_type=OppositionType.SPECTRUM,
        nodes=nodes,
        edges=[],
        pro_total=dist.pro_side,
        con_total=dist.con_side,
        neutral_total=dist.neutral,
        summary="입장이 찬성-중립-반대 사이에 연속적으로 분포해 있어요.",
    )


def _binary_view(dist: StanceDistribution) -> OppositionView:
    """Facing arcs: two poles around a central thesis (a hinge, not a clash)."""
    max_w = max(dist.pro_side, dist.con_side, 1)
    nodes = [
        GeoNode(kind="thesis", x=0.5, y=0.5, radius=0.08, stance="thesis", label="화제"),
        GeoNode(
            kind="pole",
            x=0.18,
            y=0.5,
            radius=_radius_for(dist.con_side, max_w),
            stance=StanceBucket.CON.value,
            weight=dist.con_side,
            label="반대",
        ),
        GeoNode(
            kind="pole",
            x=0.82,
            y=0.5,
            radius=_radius_for(dist.pro_side, max_w),
            stance=StanceBucket.PRO.value,
            weight=dist.pro_side,
            label="찬성",
        ),
    ]
    edges = [
        GeoEdge(x1=0.18, y1=0.5, x2=0.5, y2=0.5, kind="hinge"),
        GeoEdge(x1=0.5, y1=0.5, x2=0.82, y2=0.5, kind="hinge"),
    ]
    return OppositionView(
        opposition_type=OppositionType.BINARY,
        nodes=nodes,
        edges=edges,
        pro_total=dist.pro_side,
        con_total=dist.con_side,
        neutral_total=dist.neutral,
        summary="찬성과 반대, 두 입장이 하나의 화제를 사이에 두고 마주보고 있어요.",
    )


def _multipolar_view(dist: StanceDistribution) -> OppositionView:
    """Radial constellation: positions spread around a shared central thesis."""
    # One spoke per non-empty bucket, spread evenly around the circle.
    present = [b for b in StanceBucket if dist.count(b) > 0]
    max_w = max((dist.count(b) for b in present), default=1)
    nodes = [GeoNode(kind="thesis", x=0.5, y=0.5, radius=0.07, stance="thesis", label="화제")]
    edges: list[GeoEdge] = []
    n = max(1, len(present))
    for i, b in enumerate(present):
        angle = -math.pi / 2 + (2 * math.pi * i / n)  # start at top, clockwise
        cx = 0.5 + 0.36 * math.cos(angle)
        cy = 0.5 + 0.36 * math.sin(angle)
        w = dist.count(b)
        nodes.append(
            GeoNode(
                kind="axis",
                x=cx,
                y=cy,
                radius=_radius_for(w, max_w),
                stance=b.value,
                weight=w,
            )
        )
        edges.append(GeoEdge(x1=0.5, y1=0.5, x2=cx, y2=cy, kind="support"))
    return OppositionView(
        opposition_type=OppositionType.MULTIPOLAR,
        nodes=nodes,
        edges=edges,
        pro_total=dist.pro_side,
        con_total=dist.con_side,
        neutral_total=dist.neutral,
        summary="여러 갈래의 입장이 하나의 화제를 중심으로 펼쳐져 있어요.",
    )


def _tension_view(dist: StanceDistribution) -> OppositionView:
    """Yin-yang: two interlocked poles that coexist (unresolved tension)."""
    max_w = max(dist.pro_side, dist.con_side, 1)
    # Two interlocked lobes; each carries a small dot of the other (서로 안에 서로).
    nodes = [
        GeoNode(
            kind="pole",
            x=0.38,
            y=0.42,
            radius=_radius_for(dist.con_side, max_w),
            stance=StanceBucket.CON.value,
            weight=dist.con_side,
            label="반대",
        ),
        GeoNode(
            kind="pole",
            x=0.62,
            y=0.58,
            radius=_radius_for(dist.pro_side, max_w),
            stance=StanceBucket.PRO.value,
            weight=dist.pro_side,
            label="찬성",
        ),
        # Small inset dots: the seed of the other side within each.
        GeoNode(kind="seed", x=0.38, y=0.42, radius=0.02, stance=StanceBucket.PRO.value),
        GeoNode(kind="seed", x=0.62, y=0.58, radius=0.02, stance=StanceBucket.CON.value),
    ]
    edges = [GeoEdge(x1=0.5, y1=0.18, x2=0.5, y2=0.82, kind="rebuttal")]
    return OppositionView(
        opposition_type=OppositionType.TENSION,
        nodes=nodes,
        edges=edges,
        pro_total=dist.pro_side,
        con_total=dist.con_side,
        neutral_total=dist.neutral,
        summary="두 입장이 팽팽히 맞물려, 어느 쪽도 쉽게 기울지 않는 긴장 상태예요.",
    )


def build_opposition_view(dist: StanceDistribution) -> OppositionView:
    """Classify the opposition and compute its geometry (deterministic)."""
    kind = classify_opposition(dist)
    if kind == OppositionType.BINARY:
        return _binary_view(dist)
    if kind == OppositionType.MULTIPOLAR:
        return _multipolar_view(dist)
    if kind == OppositionType.TENSION:
        return _tension_view(dist)
    return _spectrum_view(dist)
