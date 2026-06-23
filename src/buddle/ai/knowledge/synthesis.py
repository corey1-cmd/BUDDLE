"""Insight synthesis — pure planning for recombining knowledge units (Layer B).

This decides WHAT to combine and HOW (grouping by similarity, bridging topics,
tracing contributions) WITHOUT any LLM call. The actual prose summary is then
produced either by the LLM synthesizer or, when none is configured, by the
deterministic fallback here.

Synthesis is selective: should_synthesize() gates it so we only integrate pools
that are large + fresh enough to be worth it (otherwise the raw pool suffices).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

BUNDLE_MIN_UNITS = 3
SIM_GROUP_THRESHOLD = 0.80   # cosine >= this => same recombination group
FRESHNESS_FLOOR = 0.3


@dataclass(frozen=True, slots=True)
class UnitView:
    """DB-independent view of a knowledge unit for planning."""

    unit_id: str
    gist: str
    tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SynthesisPlan:
    groups: list[list[str]]        # recombination: grouped unit_ids
    bridge_topics: list[str]       # topics spanning the units
    contributing_ids: list[str]    # all units that fed the bundle


def should_synthesize(
    unit_count: int,
    freshness: float,
    *,
    min_units: int = BUNDLE_MIN_UNITS,
    freshness_floor: float = FRESHNESS_FLOOR,
) -> bool:
    """Gate: only integrate a pool worth integrating (not every pool)."""
    return unit_count >= min_units and freshness >= freshness_floor


def plan_synthesis(
    units: list[UnitView],
    similarity: Callable[[str, str], float],
    *,
    threshold: float = SIM_GROUP_THRESHOLD,
) -> SynthesisPlan:
    """Group units by pairwise similarity (recombination) and collect bridge
    topics + contributing ids. Pure: `similarity(id_a, id_b)` is injected
    (embedding cosine in the service).

    Greedy single-linkage grouping keeps it deterministic and cheap.
    """
    ids = [u.unit_id for u in units]
    groups: list[list[str]] = []
    assigned: set[str] = set()

    for i, a in enumerate(ids):
        if a in assigned:
            continue
        group = [a]
        assigned.add(a)
        for b in ids[i + 1 :]:
            if b in assigned:
                continue
            if similarity(a, b) >= threshold:
                group.append(b)
                assigned.add(b)
        groups.append(group)

    bridge: list[str] = []
    for u in units:
        for t in u.tags:
            if t and t not in bridge:
                bridge.append(t)

    return SynthesisPlan(groups=groups, bridge_topics=bridge, contributing_ids=ids)


def fallback_summary(plan: SynthesisPlan, units: list[UnitView]) -> tuple[str, str]:
    """Deterministic (no-LLM) summary + reasoning_trace from a plan.

    Used when no synthesizer backend is configured. Presents perspectives
    rather than asserting a single conclusion (matches the LLM prompt's stance).
    """
    by_id = {u.unit_id: u for u in units}
    n = len(units)
    g = len(plan.groups)

    lines: list[str] = []
    for idx, group in enumerate(plan.groups, start=1):
        gists = [by_id[i].gist for i in group if i in by_id]
        if not gists:
            continue
        head = gists[0]
        extra = f" (외 {len(gists) - 1}개 유사 생각)" if len(gists) > 1 else ""
        lines.append(f"관점 {idx}: {head}{extra}")

    summary = (
        f"'{', '.join(plan.bridge_topics[:3]) or '여러 주제'}'에 관해 모인 "
        f"{n}개의 생각이 {g}개의 관점으로 묶입니다. " + " / ".join(lines[:4])
    )
    reasoning = (
        f"단위 {n}개를 유사도 기준으로 {g}개 그룹으로 재조합했습니다. "
        f"가로지르는 주제: {', '.join(plan.bridge_topics[:5]) or '없음'}. "
        "각 그룹의 대표 생각을 관점으로 제시하며, 단일 결론을 단정하지 않습니다."
    )
    return summary, reasoning
