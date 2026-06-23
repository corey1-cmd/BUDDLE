"""Post schemas — create, read, feed items."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from buddle.db.models.enums import PostVisibility


class PostCreate(BaseModel):
    persona_id: uuid.UUID
    content_raw: str = Field(min_length=1, max_length=8000)
    visibility: PostVisibility


class PersonaBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    model_key: str


class TagName(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class PostRead(BaseModel):
    """A post returned to its owner (includes raw content)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_persona: PersonaBrief | None
    content_raw: str
    content_transformed: str
    visibility: PostVisibility
    is_suppressed: bool
    tags: list[TagName]
    created_at: datetime


class PostFeedItem(BaseModel):
    """A post in the public feed (no raw content exposure)."""

    id: uuid.UUID
    source_persona: PersonaBrief | None
    content_transformed: str
    tags: list[TagName]
    importance: float  # normalized [-1, 1]
    created_at: datetime


class FeedPage(BaseModel):
    items: list[PostFeedItem]
    next_cursor: str | None
