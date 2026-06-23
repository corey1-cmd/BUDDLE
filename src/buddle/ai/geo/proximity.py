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
    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(h)))


def ring_points(distance_km: float, rings: tuple[float, ...] = RADIUS_RINGS_KM) -> int:
    """How many concentric rings this distance falls within (equal weight each).

    A distance exactly on a ring boundary counts as inside that ring (<=).
    """
    if distance_km < 0:
        return 0
    return sum(1 for r in rings if distance_km <= r)


def proximity_score(
    a: GeoPoint, b: GeoPoint, rings: tuple[float, ...] = RADIUS_RINGS_KM
) -> int:
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


def within_match_range(a: GeoPoint, b: GeoPoint, rings: tuple[float, ...] = RADIUS_RINGS_KM) -> bool:
    """Whether two points are close enough to match at all (within largest ring)."""
    if not rings:
        return False
    return haversine_km(a, b) <= max(rings)


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
