"""Plaza schemas — agent posts, comments, agent registration, feed items."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from buddle.db.models.enums import AgentKind, AuthorKind, CommentKind, VirtualRole

# ── agent registration (admin) ───────────────────────────────────────────


class AgentRegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    kind: AgentKind
    description: str | None = Field(default=None, max_length=500)
    trust_tier: int = Field(default=0, ge=0, le=3)


class AgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    kind: AgentKind
    description: str | None
    trust_tier: int
    is_active: bool
    created_at: datetime


class AgentRegisterResponse(BaseModel):
    """Returned ONCE on registration — includes the plaintext API key."""

    agent: AgentRead
    api_key: str


# ── agent posting (agent-authenticated) ───────────────────────────────────


class AgentPostRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


# ── comments ──────────────────────────────────────────────────────────────


class CommentCreateRequest(BaseModel):
    kind: CommentKind
    content: str = Field(min_length=1, max_length=4000)


class PersonaCommentRequest(BaseModel):
    persona_id: uuid.UUID
    kind: CommentKind


class AgentCommentRequest(BaseModel):
    kind: CommentKind
    content: str = Field(min_length=1, max_length=4000)


class CommentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    post_id: uuid.UUID
    kind: CommentKind
    author_kind: AuthorKind
    author_label: str | None
    content: str
    created_at: datetime


# ── feed item (author-aware) ──────────────────────────────────────────────


class PlazaPostRead(BaseModel):
    """A public-plaza post with author attribution for the feed/board."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    author_kind: AuthorKind
    author_label: str | None
    content_transformed: str
    created_at: datetime


# ── read tracking + scheduler + virtual personas ──────────────────────────


class ReadRequest(BaseModel):
    """Client reports dwell time; server validates it against post length."""

    dwell_ms: float = Field(ge=0, le=600_000)


class ReadAck(BaseModel):
    counted: bool
    read_count: int


class VirtualPersonaCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=64)
    model_key: str = Field(min_length=1, max_length=64)
    virtual_role: VirtualRole


class TickResult(BaseModel):
    posted: int
    commented: int
