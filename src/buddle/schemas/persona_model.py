"""Persona model registry schemas — public + admin views."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from buddle.db.models.enums import PersonaBackendKind, PersonaModelStatus

_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}[a-z0-9]$")


# ── Public (for end-users picking a persona model) ────────────────────────


class PersonaModelPublic(BaseModel):
    """What end users see when listing available persona models."""

    model_config = ConfigDict(from_attributes=True)

    template_key: str
    display_name: str
    description: str | None
    version: str
    backend_kind: PersonaBackendKind
    is_default: bool


# ── Admin views ───────────────────────────────────────────────────────────


class PersonaModelAdmin(PersonaModelPublic):
    """Full view, admin-only fields included."""

    id: uuid.UUID
    backend_config: dict[str, Any] | None
    system_prompt: str | None
    status: PersonaModelStatus
    created_at: datetime
    updated_at: datetime


class PersonaModelCreate(BaseModel):
    template_key: str = Field(min_length=2, max_length=64)
    display_name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    version: str = Field(default="0.1.0", max_length=32)
    backend_kind: PersonaBackendKind = PersonaBackendKind.STUB
    backend_config: dict[str, Any] | None = None
    system_prompt: str | None = None
    status: PersonaModelStatus = PersonaModelStatus.DRAFT
    is_default: bool = False

    @field_validator("template_key")
    @classmethod
    def _validate_key(cls, v: str) -> str:
        v = v.lower()
        if not _KEY_RE.match(v):
            raise ValueError(
                "template_key must be lowercase alphanumeric, '-' or '_', "
                "2-64 chars, starting and ending with alphanumeric."
            )
        return v


class PersonaModelUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    version: str | None = Field(default=None, max_length=32)
    backend_kind: PersonaBackendKind | None = None
    backend_config: dict[str, Any] | None = None
    system_prompt: str | None = None
    status: PersonaModelStatus | None = None
    is_default: bool | None = None
