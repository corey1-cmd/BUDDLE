"""Geo helpers — pure proximity matching for the location-based variant."""

from buddle.ai.geo.proximity import (
    RADIUS_RINGS_KM,
    GeoPoint,
    coarsen,
    haversine_km,
    proximity_affinity,
    proximity_score,
    ring_points,
    within_match_range,
)

__all__ = [
    "RADIUS_RINGS_KM",
    "GeoPoint",
    "coarsen",
    "haversine_km",
    "proximity_affinity",
    "proximity_score",
    "ring_points",
    "within_match_range",
]
