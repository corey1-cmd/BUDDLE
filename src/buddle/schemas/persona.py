"""Persona schemas.

`strategy_template` was Stage 1 part-1; replaced by `model_key` referencing
the persona_models registry. Allowed values are determined dynamically (any
ACTIVE PersonaModel) rather than a hardcoded enum.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PersonaCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    model_key: str = Field(min_length=2, max_length=64)
    interest_tag_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    # Location-based chat (opt-in). Set at creation so the proximity feature is
    # configured in one place. lat/lon required if location_sharing is true.
    location_sharing: bool = False
    location_lat: float | None = Field(default=None, ge=-90.0, le=90.0)
    location_lon: float | None = Field(default=None, ge=-180.0, le=180.0)


class PersonaUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    model_key: str | None = Field(default=None, min_length=2, max_length=64)
    interest_tag_ids: list[uuid.UUID] | None = Field(default=None, max_length=20)
    is_active: bool | None = None
    # Location-based chat (opt-in). All three optional; when location_sharing is
    # set true, lat/lon must be provided (validated in the service).
    location_sharing: bool | None = None
    location_lat: float | None = Field(default=None, ge=-90.0, le=90.0)
    location_lon: float | None = Field(default=None, ge=-180.0, le=180.0)


class PersonaRead(BaseModel):
    """Brief persona representation for list views."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    model_key: str
    is_active: bool
    created_at: datetime


class TagBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class TagTrend(BaseModel):
    """A tag with its recent public-post count (트렌딩 화제)."""

    id: uuid.UUID
    name: str
    post_count: int


class PersonaInterestTagRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tag: TagBrief
    weight: float


class PersonaDetail(PersonaRead):
    """Full persona detail with interest tags."""

    interest_tags: list[PersonaInterestTagRead]
    # Exposed so the client can render the location-sharing state (e.g. the
    # nearby screen's on/off view) without guessing.
    location_sharing: bool = False


class PersonaQuotaInfo(BaseModel):
    current: int
    limit: int
    remaining: int
