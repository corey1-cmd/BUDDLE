"""10-tier graded proximity weights — pure math contract.

The weight curve is a falling logistic over tiers 1–6 (near-flat head so the
closest tier doesn't win by a landslide) joined at tier 6 to an exponential
tail for tiers 7–10 with C¹ continuity (value AND slope match by construction:
λ = a·(1 − f(6)) from f' = −a·f·(1−f)).
"""

from __future__ import annotations

import math
from itertools import pairwise

from buddle.ai.geo.proximity import (
    RADIUS_RINGS_KM,
    GeoPoint,
    graded_affinity,
    tier_of,
    tier_weight,
)

_SPLIT = 6


def test_tier_of_maps_distance_to_innermost_ring():
    ordered = sorted(RADIUS_RINGS_KM)  # 1,5,10,30,50,100,200,300,500,1000
    assert tier_of(0.3) == 1
    assert tier_of(1.0) == 1  # boundary counts as inside
    assert tier_of(4.0) == 2
    assert tier_of(120.0) == 7
    assert tier_of(999.0) == 10
    assert tier_of(ordered[-1]) == 10
    assert tier_of(ordered[-1] + 0.01) == 0  # out of range
    assert tier_of(-5.0) == 0


def test_weights_strictly_decrease_over_tiers():
    ws = [tier_weight(k) for k in range(1, 11)]
    for earlier, later in pairwise(ws):
        assert earlier > later > 0.0


def test_head_is_near_flat_no_winner_takes_all():
    """Tiers 1–3 stay within ~25% of each other — 근거리 독식 방지."""
    assert tier_weight(1) / tier_weight(3) < 1.25


def test_c0_continuity_at_split():
    eps = 1e-9
    left = tier_weight(_SPLIT - eps)
    right = tier_weight(_SPLIT + eps)
    assert math.isclose(left, right, rel_tol=1e-6)


def test_c1_continuity_at_split():
    """Numeric slope from both sides matches at the joint (the λ choice)."""
    h = 1e-6
    slope_left = (tier_weight(_SPLIT) - tier_weight(_SPLIT - h)) / h
    slope_right = (tier_weight(_SPLIT + h) - tier_weight(_SPLIT)) / h
    assert math.isclose(slope_left, slope_right, rel_tol=1e-3)


def test_tail_never_reaches_zero():
    """나라 간(tier 10)도 매칭 가능 — 강하게 할인되지만 0이 아니다."""
    assert 0.0 < tier_weight(10) < tier_weight(_SPLIT) * 0.2


def test_out_of_range_is_zero():
    assert tier_weight(0) == 0.0
    assert tier_weight(-3) == 0.0


def test_graded_affinity_normalized_and_ordered():
    seoul = GeoPoint(37.5665, 126.9780)
    neighbor = GeoPoint(37.5700, 126.9800)  # < 1 km
    incheon = GeoPoint(37.4563, 126.7052)  # ~27 km
    busan = GeoPoint(35.1796, 129.0756)  # ~325 km
    tokyo = GeoPoint(35.6762, 139.6503)  # ~1150 km (범위 밖)

    a1 = graded_affinity(seoul, neighbor)
    a2 = graded_affinity(seoul, incheon)
    a3 = graded_affinity(seoul, busan)
    a4 = graded_affinity(seoul, tokyo)

    assert a1 == 1.0  # tier 1 anchors the scale
    assert 1.0 > a2 > a3 > 0.0
    assert a4 == 0.0  # outside the largest ring
