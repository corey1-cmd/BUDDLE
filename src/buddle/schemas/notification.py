"""Notification schemas — activity feed items and read receipts."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from buddle.db.models.enums import AuthorKind, NotificationKind


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: NotificationKind
    actor_kind: AuthorKind
    actor_label: str | None
    post_id: uuid.UUID | None
    preview: str | None
    read_at: datetime | None
    created_at: datetime


class UnreadCount(BaseModel):
    count: int


class ReadReceipt(BaseModel):
    """Result of a mark-read action (single or bulk)."""

    updated: int
