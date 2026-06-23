"""Proximity matching tests — pure geo math, no DB.

Verifies Haversine accuracy, nested-ring scoring + boundaries, normalized
affinity, the "closer = stronger" monotonicity that motivates the feature,
and the privacy coarsening contract. DB-backed find_nearby runs in CI.
"""

from __future__ import annotations

from buddle.ai.geo import (
    RADIUS_RINGS_KM,
    GeoPoint,
    coarsen,
    haversine_km,
    proximity_affinity,
    proximity_score,
    ring_points,
    within_match_range,
)

# Reference points around Seoul.
CITY_HALL = GeoPoint(37.5663, 126.9779)
MYEONGDONG = GeoPoint(37.5636, 126.9869)  # ~0.8 km
YEOUIDO = GeoPoint(37.5219, 126.9245)  # ~6.8 km
SUWON = GeoPoint(37.2636, 127.0286)  # ~34 km
CHEONAN = GeoPoint(36.8151, 127.1139)  # ~84 km
FAR_OVERSEAS = GeoPoint(1.3521, 103.8198)  # Singapore, >4000 km (out of range)


# ── Haversine ──────────────────────────────────────────────────────────────


def test_distance_zero_for_same_point():
    assert haversine_km(CITY_HALL, CITY_HALL) == 0.0


def test_distance_known_values_approx():
    assert haversine_km(CITY_HALL, MYEONGDONG) < 2
    assert 5 < haversine_km(CITY_HALL, YEOUIDO) < 9
    assert 30 < haversine_km(CITY_HALL, SUWON) < 38
    assert haversine_km(CITY_HALL, CHEONAN) > 75


def test_distance_symmetric():
    assert haversine_km(CITY_HALL, SUWON) == haversine_km(SUWON, CITY_HALL)


# ── nested-ring scoring ────────────────────────────────────────────────────


def test_ring_points_closest_hits_all():
    assert proximity_score(CITY_HALL, MYEONGDONG) == len(RADIUS_RINGS_KM)  # 5


def test_ring_points_mid_distance():
    # ~6.8 km -> within all rings >= 10 km (1000..10) = 8 of 10
    assert proximity_score(CITY_HALL, YEOUIDO) == 8


def test_ring_points_far_edge():
    # ~34 km -> within rings >= 50 km (1000,500,300,200,100,50) = 6 of 10
    assert proximity_score(CITY_HALL, SUWON) == 6


def test_ring_points_out_of_range():
    # CHEONAN ~84 km is now WITHIN range (>= 100 km ring) -> 5 points
    assert proximity_score(CITY_HALL, CHEONAN) == 5
    # a point >1000 km away (e.g. far overseas) scores 0
    assert proximity_score(CITY_HALL, FAR_OVERSEAS) == 0


def test_ring_boundary_is_inclusive():
    # a distance exactly on a ring counts as inside (<=)
    # 10 km -> rings >= 10 (1000,500,300,200,100,50,30,10) = 8
    assert ring_points(10.0) == 8
    assert ring_points(10.0001) == 7  # just outside the 10 km ring


def test_negative_distance_zero():
    assert ring_points(-5.0) == 0


# ── normalized affinity + monotonicity (the feature's premise) ─────────────


def test_affinity_range():
    assert proximity_affinity(CITY_HALL, MYEONGDONG) == 1.0
    assert proximity_affinity(CITY_HALL, FAR_OVERSEAS) == 0.0
    a = proximity_affinity(CITY_HALL, YEOUIDO)
    assert 0.0 < a < 1.0


def test_closer_is_strictly_stronger():
    # the core idea: closer pairs get a higher (or equal) score
    s_near = proximity_affinity(CITY_HALL, MYEONGDONG)
    s_mid = proximity_affinity(CITY_HALL, YEOUIDO)
    s_far = proximity_affinity(CITY_HALL, SUWON)
    s_out = proximity_affinity(CITY_HALL, FAR_OVERSEAS)
    assert s_near > s_mid > s_far > s_out


def test_within_match_range():
    assert within_match_range(CITY_HALL, SUWON)  # 34 km <= 1000
    assert within_match_range(CITY_HALL, CHEONAN)  # 84 km <= 1000
    assert not within_match_range(CITY_HALL, FAR_OVERSEAS)  # > 1000 km


# ── privacy coarsening contract ────────────────────────────────────────────


def test_coarsen_reduces_precision():
    c = coarsen(GeoPoint(37.566312, 126.977942), 1)
    assert c.lat == 37.6
    assert c.lon == 127.0


def test_coarsen_two_decimals():
    c = coarsen(GeoPoint(37.566312, 126.977942), 2)
    assert c.lat == 37.57
    assert c.lon == 126.98


def test_equal_weight_rings():
    # each ring contributes exactly one point (equal weight, per spec):
    # difference between consecutive ring counts is at most 1
    # 10 rings; counts step down by 1 as we cross each ring boundary
    counts = [ring_points(d) for d in [0.5, 3, 7, 20, 40, 80, 150, 250, 450, 900, 1500]]
    assert counts == [10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0]
