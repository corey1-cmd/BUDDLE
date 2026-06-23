"""UUID generation and parsing helpers."""

from __future__ import annotations

import uuid


def new_uuid() -> uuid.UUID:
    """Generate a new UUID4."""
    return uuid.uuid4()


def parse_uuid(value: str | uuid.UUID) -> uuid.UUID:
    """Coerce a string to a UUID, or pass through if already a UUID."""
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(value)
