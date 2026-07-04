"""Geo proximity matching — pure functions for the location-based variant.

Rationale (Tobler's First Law of Geography: "near things are more related than
distant things"): people who are geographically closer tend to share culture,
context, and interests, so their conversations overlap more — good signal for
recommendation. We turn distance into a match score using NESTED radius rings.

Concentric rings {1000, 500, 300, 200, 100, 50, 30, 10, 5, 1} km. Each ring a
pair of personas both fall within contributes ONE equal-weight point (per the
spec: "weights of the overlaps in each radius are equal"). Closer pairs satisfy
more rings, so the score accumulates the closer they are — a strong gradient
that spreads outward from very local to national/cross-border scale:

    d = 0.8 km -> within all 10 rings -> 10 points (strongest)
    d = 7   km -> within {1000..10}   -> 8 points
    d = 250 km -> within {1000,500,300} -> 3 points
    d = 1500 km -> none               -> 0 (out of match range)

Normalizing by the ring count gives a proximity affinity in [0, 1]. This is a
SEPARATE matching stage (not folded into the mediator's relevance formula).

Pure + dependency-free (math only); no I/O, no extra LLM/embedding calls.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Concentric radius rings in kilometers, largest first. Each contributes one
# equal-weight point when both parties fall inside it. Rings span from very
# local (1 km) to national/cross-border scale (1000 km), so matching can reach
# beyond a single metro/country while still scoring closer pairs much higher
# (a nearby pair satisfies far more rings -> a strong "spreads out from close"
# gradient).
RADIUS_RINGS_KM: tuple[float, ...] = (
    1000.0,
    500.0,
    300.0,
    200.0,
    100.0,
    50.0,
    30.0,
    10.0,
    5.0,
    1.0,
)

_EARTH_RADIUS_KM = 6371.0088  # mean Earth radius (km)


@dataclass(frozen=True, slots=True)
class GeoPoint:
    """A latitude/longitude in decimal degrees."""

    lat: float
    lon: float


def haversine_km(a: GeoPoint, b: GeoPoint) -> float:
    """Great-circle distance between two points in kilometers (Haversine).

    Accurate for the city/regional scale we care about and cheap to compute.
    """
    lat1 = math.radians(a.lat)
    lat2 = math.radians(b.lat)
    dlat = lat2 - lat1
    dlon = math.radians(b.lon - a.lon)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(h)))


def ring_points(distance_km: float, rings: tuple[float, ...] = RADIUS_RINGS_KM) -> int:
    """How many concentric rings this distance falls within (equal weight each).

    A distance exactly on a ring boundary counts as inside that ring (<=).
    """
    if distance_km < 0:
        return 0
    return sum(1 for r in rings if distance_km <= r)


def proximity_score(a: GeoPoint, b: GeoPoint, rings: tuple[float, ...] = RADIUS_RINGS_KM) -> int:
    """Raw nested-ring proximity points between two points (0..len(rings))."""
    return ring_points(haversine_km(a, b), rings)


def proximity_affinity(
    a: GeoPoint, b: GeoPoint, rings: tuple[float, ...] = RADIUS_RINGS_KM
) -> float:
    """Normalized proximity in [0, 1] (raw points / number of rings).

    0 = outside the largest ring; 1 = within the innermost (closest) ring.
    """
    n = len(rings)
    if n == 0:
        return 0.0
    return proximity_score(a, b, rings) / n


def within_match_range(
    a: GeoPoint, b: GeoPoint, rings: tuple[float, ...] = RADIUS_RINGS_KM
) -> bool:
    """Whether two points are close enough to match at all (within largest ring)."""
    if not rings:
        return False
    return haversine_km(a, b) <= max(rings)


# ── Graded tier weights: logistic head (1–6) + C¹ exponential tail (7–10) ──
#
# "지역 → 도시 → 나라 → 세계"의 10단계에서, 매칭 가중은 두 요구를 동시에
# 만족해야 한다: ① 아주 가까운 사람만 독식하지 않을 것(1~3단계는 거의 동급),
# ② 멀수록 대화 방식·주제가 갈리므로 완만히, 그러나 0이 되지는 않게 감쇠할 것
# (나라 간 매칭도 '가능하되 희귀'해야 세계 확장 서사가 산다).
#
#   1–6단계  f(k) = σ(a·(k0 − k))        하강 로지스틱 — 근거리 평탄부 + 중간 변곡
#   7–10단계 g(k) = f(6)·e^(−λ(k−6))     지수 꼬리 — 0에 닿지 않는 장거리 감쇠
#
# 두 조각은 k=6에서 값과 기울기가 모두 일치한다(C¹). 로지스틱의 도함수가
# f' = −a·f·(1−f) 이므로 λ = a·(1 − f(6)) 로 잡으면 닫힌형으로 정확히 이어진다
# — 수치 맞춤 없이 파라미터(a, k0)만으로 연속성이 보장된다.

_TIER_SPLIT = 6  # 1..6 = 로지스틱(지역~광역), 7..10 = 지수 꼬리(도시간~나라간)
_TIER_STEEPNESS = 0.9  # a — 클수록 변곡이 가파름
_TIER_MIDPOINT = 4.5  # k0 — 변곡 위치(4~5단계 사이)


def tier_of(distance_km: float, rings: tuple[float, ...] = RADIUS_RINGS_KM) -> int:
    """Distance -> tier 1(가장 근접)..len(rings)(가장 원거리); 범위 밖 = 0.

    Tier k = the k-th smallest ring that still contains the distance, so the
    innermost containing ring decides the tier (boundary counts as inside).
    """
    if distance_km < 0:
        return 0
    for idx, r in enumerate(sorted(rings)):
        if distance_km <= r:
            return idx + 1
    return 0  # outside the largest ring — not matchable


def tier_weight(
    k: float,
    *,
    steepness: float = _TIER_STEEPNESS,
    midpoint: float = _TIER_MIDPOINT,
    split: int = _TIER_SPLIT,
) -> float:
    """Match weight for tier k (real-valued OK) in (0, 1).

    k <= split: falling logistic. k > split: exponential tail joined with C¹
    continuity at the split (value AND slope match — see module comment).
    k < 1 clamps to tier 1; k <= 0 -> 0 (out of range).
    """
    if k <= 0:
        return 0.0
    k = max(1.0, k)
    if k <= split:
        return 1.0 / (1.0 + math.exp(steepness * (k - midpoint)))
    f_split = 1.0 / (1.0 + math.exp(steepness * (split - midpoint)))
    lam = steepness * (1.0 - f_split)  # C¹: g'(split) = f'(split)
    return f_split * math.exp(-lam * (k - split))


def graded_affinity(a: GeoPoint, b: GeoPoint, rings: tuple[float, ...] = RADIUS_RINGS_KM) -> float:
    """Tier-weighted proximity in [0, 1] — 1.0 at tier 1, 0.0 out of range.

    Normalized by the tier-1 weight so the closest tier anchors the scale;
    ordering across tiers follows tier_weight's logistic+tail shape.
    """
    k = tier_of(haversine_km(a, b), rings)
    if k == 0:
        return 0.0
    return tier_weight(float(k)) / tier_weight(1.0)


# Privacy helper: even though exact coordinates are STORED (precision choice),
# what we EXPOSE to other users/clients is generalized — a coarse grid cell —
# so a peer can never read someone's exact location. Storing precise + exposing
# coarse keeps distance math accurate while protecting users (LBS requirement).
def coarsen(point: GeoPoint, decimals: int = 1) -> GeoPoint:
    """Round coordinates to `decimals` places for safe exposure.

    ~decimals=1 -> ≈11 km grid; decimals=2 -> ≈1.1 km. Used for any location
    value leaving the server; never expose raw stored coordinates.
    """
    return GeoPoint(lat=round(point.lat, decimals), lon=round(point.lon, decimals))
