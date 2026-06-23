"""Reaction schemas — like / report on a public post."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class ReportRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class ImportanceView(BaseModel):
    """Returned after a reaction so the client can reflect the new state."""

    post_id: uuid.UUID
    normalized_importance: float


class ReportAck(BaseModel):
    post_id: uuid.UUID
    alert_id: uuid.UUID
    normalized_importance: float
