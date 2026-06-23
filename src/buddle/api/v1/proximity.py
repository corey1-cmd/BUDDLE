"""Proximity routes — /v1/proximity: opt-in location + nearby persona matching.

A separate location-based matching stage (LBS variant). Users set their
persona's location (opt-in) and fetch nearby personas ranked by nested-ring
proximity. Only coarsened coordinates are returned for matches.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from buddle.api.deps import DB, CurrentUser
from buddle.core.exceptions import Forbidden, NotFound
from buddle.db.models.persona import Persona
from buddle.services import proximity_service

router = APIRouter(prefix="/proximity", tags=["proximity"])


class LocationUpdate(BaseModel):
    lat: float | None = Field(default=None, ge=-90.0, le=90.0)
    lon: float | None = Field(default=None, ge=-180.0, le=180.0)
    sharing: bool = False


class NearbyPersona(BaseModel):
    persona_id: uuid.UUID
    name: str
    distance_km: float
    ring_points: int
    affinity: float
    approx_lat: float
    approx_lon: float


async def _owned_persona(db: DB, user_id: uuid.UUID, persona_id: uuid.UUID) -> Persona:
    p = await db.get(Persona, persona_id)
    if p is None or p.user_id != user_id:
        raise NotFound("Persona not found.")
    return p


@router.put("/personas/{persona_id}/location", summary="Set persona location (opt-in)")
async def set_location(
    persona_id: uuid.UUID,
    payload: LocationUpdate,
    user: CurrentUser,
    db: DB,
) -> dict[str, object]:
    await _owned_persona(db, user.id, persona_id)
    # If sharing is on, both coordinates must be present.
    if payload.sharing and (payload.lat is None or payload.lon is None):
        raise Forbidden("lat and lon are required when sharing is enabled.")
    p = await proximity_service.set_location(
        db, persona_id, lat=payload.lat, lon=payload.lon, sharing=payload.sharing
    )
    return {"persona_id": str(p.id), "sharing": p.location_sharing}


@router.get(
    "/personas/{persona_id}/nearby",
    response_model=list[NearbyPersona],
    summary="Find nearby personas ranked by proximity (closest first)",
)
async def nearby(
    persona_id: uuid.UUID,
    user: CurrentUser,
    db: DB,
    limit: int = Query(default=20, ge=1, le=100),
) -> Sequence[object]:
    await _owned_persona(db, user.id, persona_id)
    return await proximity_service.find_nearby(db, persona_id, limit=limit)
