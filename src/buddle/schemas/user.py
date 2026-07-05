"""User schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from buddle.db.models.enums import UserTier


class UserRead(BaseModel):
    """Public user representation."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    tier: UserTier
    persona_quota: int
    is_admin: bool
    is_active: bool
    created_at: datetime


class UserUpdate(BaseModel):
    """Self-update payload — only fields the user can change directly."""

    email: EmailStr | None = None
    current_password: str | None = Field(default=None, min_length=1, max_length=128)
    new_password: str | None = Field(default=None, min_length=8, max_length=128)


class AccountDeleteRequest(BaseModel):
    """Confirm account deletion with the current password (deliberate action)."""

    password: str = Field(min_length=1, max_length=128)
