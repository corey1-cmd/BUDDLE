"""Argument-AI chat WebSocket message schemas.

Mirrors the dialogue WS contract but adds a "save note" client action so a
useful answer can be persisted onto the post as context.

Protocol:
  client → { "type": "user_message", "content": "..." }
  client → { "type": "save_note", "content": "...", "note_kind": "context" }
  server → { "type": "ai_message", "content": "...", "label": "..." }
  server → { "type": "note_saved", "note_id": "..." }
  server → { "type": "typing", "state": "start" }
  server → { "type": "error", "code": "...", "message": "..." }
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field


class ArgClientMessage(BaseModel):
    type: Literal["user_message"] = "user_message"
    content: str = Field(min_length=1, max_length=2000)


class ArgClientSaveNote(BaseModel):
    type: Literal["save_note"] = "save_note"
    content: str = Field(min_length=1, max_length=2000)
    note_kind: Literal["context", "evidence", "clarification"] = "context"


class ArgServerMessage(BaseModel):
    type: Literal["ai_message"] = "ai_message"
    content: str
    label: str = Field(description="이 AI가 누구/무엇의 재현인지 알리는 고정 라벨")


class ArgServerNoteSaved(BaseModel):
    type: Literal["note_saved"] = "note_saved"
    note_id: uuid.UUID


class ArgServerTyping(BaseModel):
    type: Literal["typing"] = "typing"
    state: Literal["start", "stop"] = "start"


class ArgServerError(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str
