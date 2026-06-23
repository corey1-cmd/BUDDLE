"""Proximity matching service — a SEPARATE matching stage for the LBS variant.

Finds personas geographically near a given persona, ranked by the nested-ring
proximity affinity (ai/geo). Kept independent of the mediator's relevance
formula (per the design decision): proximity recommendations are their own
endpoint/stage, so the existing distribution logic is untouched.

Two-step efficiency (standard for geo search):
  1. Coarse bounding-box prefilter in SQL (cheap, uses the lat/lon index) to
     shrink the candidate set to roughly the largest ring.
  2. Exact Haversine + ring scoring in Python for accuracy (bbox is a square,
     rings are circles).

Privacy: only personas with location_sharing = true participate, and any
coordinate that leaves the server is coarsened (see ai/geo.coarsen). The exact
stored coordinate of another user is never returned.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from buddle.ai.geo import (
    RADIUS_RINGS_KM,
    GeoPoint,
    coarsen,
    haversine_km,
    proximity_affinity,
    ring_points,
)
from buddle.core.exceptions import NotFound
from buddle.db.models.persona import Persona


@dataclass(frozen=True, slots=True)
class ProximityMatch:
    persona_id: uuid.UUID
    name: str
    distance_km: float
    ring_points: int
    affinity: float
    # Coarsened location for safe display (never the exact stored coordinate).
    approx_lat: float
    approx_lon: float


def _bbox_deg(center: GeoPoint, radius_km: float) -> tuple[float, float, float, float]:
    """Lat/lon bounding box (degrees) covering `radius_km` around center.

    1 deg latitude ≈ 111 km; longitude scaled by cos(latitude). A small margin
    is added so the square fully encloses the circle.
    """
    margin = 1.1
    dlat = (radius_km / 111.0) * margin
    coslat = max(0.01, math.cos(math.radians(center.lat)))
    dlon = (radius_km / (111.0 * coslat)) * margin
    return (center.lat - dlat, center.lat + dlat, center.lon - dlon, center.lon + dlon)


async def find_nearby(
    db: AsyncSession,
    persona_id: uuid.UUID,
    *,
    limit: int = 20,
) -> list[ProximityMatch]:
    """Rank other location-sharing personas by proximity to `persona_id`.

    Returns only personas within the largest ring, sorted by affinity (closest
    first). Empty if the source persona isn't sharing a location.
    """
    src = await db.get(Persona, persona_id)
    if src is None:
        raise NotFound("Persona not found.")
    if not (src.location_sharing and src.location_lat is not None and src.location_lon is not None):
        return []  # source not sharing -> no matching

    center = GeoPoint(lat=src.location_lat, lon=src.location_lon)
    max_radius = max(RADIUS_RINGS_KM)
    min_lat, max_lat, min_lon, max_lon = _bbox_deg(center, max_radius)

    # Step 1: coarse bbox prefilter (indexed), excluding self + non-sharers.
    rows = (
        await db.execute(
            select(Persona).where(
                and_(
                    Persona.id != persona_id,
                    Persona.location_sharing.is_(True),
                    Persona.location_lat.is_not(None),
                    Persona.location_lon.is_not(None),
                    Persona.location_lat >= min_lat,
                    Persona.location_lat <= max_lat,
                    Persona.location_lon >= min_lon,
                    Persona.location_lon <= max_lon,
                )
            )
        )
    ).scalars()

    # Step 2: exact Haversine + ring scoring; keep only within the largest ring.
    matches: list[ProximityMatch] = []
    for p in rows:
        if p.location_lat is None or p.location_lon is None:
            continue
        other = GeoPoint(lat=p.location_lat, lon=p.location_lon)
        d = haversine_km(center, other)
        pts = ring_points(d)
        if pts == 0:
            continue  # inside bbox square but outside the circle
        approx = coarsen(other, 2)
        matches.append(
            ProximityMatch(
                persona_id=p.id,
                name=p.name,
                distance_km=round(d, 2),
                ring_points=pts,
                affinity=proximity_affinity(center, other),
                approx_lat=approx.lat,
                approx_lon=approx.lon,
            )
        )

    matches.sort(key=lambda m: (-m.affinity, m.distance_km))
    return matches[: max(1, min(limit, 100))]


async def set_location(
    db: AsyncSession,
    persona_id: uuid.UUID,
    *,
    lat: float | None,
    lon: float | None,
    sharing: bool,
) -> Persona:
    """Set a persona's location + opt-in sharing flag (owner-checked by route)."""
    p = await db.get(Persona, persona_id)
    if p is None:
        raise NotFound("Persona not found.")
    p.location_lat = lat
    p.location_lon = lon
    p.location_sharing = sharing
    await db.commit()
    await db.refresh(p)
    return p
