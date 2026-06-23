"""Opaque cursor encoding for pagination.

Cursors are base64-url-encoded JSON. The schema is callsite-defined; only
encoding/decoding is shared.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from buddle.core.exceptions import ValidationError


def encode_cursor(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode_cursor(cursor: str) -> dict[str, Any]:
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(cursor + padding)
        parsed = json.loads(raw)
    except (ValueError, json.JSONDecodeError) as e:
        raise ValidationError("Invalid cursor.", detail={"cursor": cursor}) from e
    if not isinstance(parsed, dict):
        raise ValidationError("Invalid cursor shape.")
    return parsed
