"""Inbox schemas — items delivered privately to one of the user's personas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from buddle.schemas.post import PersonaBrief, TagName


class InboxItem(BaseModel):
    """A distribution event delivered to one of the user's personas."""

    distribution_id: uuid.UUID
    target_persona: PersonaBrief
    source_persona: PersonaBrief | None
    content_transformed: str
    tags: list[TagName]
    relevance_score: float
    delivered_at: datetime
    seen_at: datetime | None


class InboxPage(BaseModel):
    items: list[InboxItem]
    next_cursor: str | None
