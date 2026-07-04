"""Geo helpers — pure proximity matching for the location-based variant."""

from buddle.ai.geo.proximity import (
    RADIUS_RINGS_KM,
    GeoPoint,
    coarsen,
    graded_affinity,
    haversine_km,
    proximity_affinity,
    proximity_score,
    ring_points,
    tier_of,
    tier_weight,
    within_match_range,
)

__all__ = [
    "RADIUS_RINGS_KM",
    "GeoPoint",
    "coarsen",
    "graded_affinity",
    "haversine_km",
    "proximity_affinity",
    "proximity_score",
    "ring_points",
    "tier_of",
    "tier_weight",
    "within_match_range",
]
