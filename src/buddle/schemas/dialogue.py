"""WebSocket dialogue frame schemas.

Wire format: each WebSocket text frame is a JSON object with a 'type' field.

Client -> server:
  - { "type": "user_message", "content": "..." }

Server -> client:
  - { "type": "persona_message", "content": "...", "metadata": {...} }
  - { "type": "error", "code": "...", "message": "..." }
  - { "type": "typing", "state": "start" | "stop" }     (optional, Stage 2)

History is loaded from the `messages` table on connect and not re-sent
over the wire — clients should fetch it via REST if they need it.
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field


class ClientUserMessage(BaseModel):
    type: Literal["user_message"]
    content: str = Field(min_length=1, max_length=4000)
    # Topic session this message belongs to. When omitted, falls back to the
    # persona-wide stream (backward compatible).
    session_id: uuid.UUID | None = None


class ServerPersonaMessage(BaseModel):
    type: Literal["persona_message"] = "persona_message"
    content: str
    metadata: dict[str, str] = Field(default_factory=dict)


class ServerError(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str


class ServerTyping(BaseModel):
    type: Literal["typing"] = "typing"
    state: Literal["start", "stop"]
