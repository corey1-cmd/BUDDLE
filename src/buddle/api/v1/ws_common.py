"""Shared WebSocket helpers — reused by the dialogue and argument-chat sockets.

These were originally private to the dialogue handler; extracting them lets the
argument-AI socket reuse the exact same auth, rate-limiting, origin-check, and
JSON-send logic instead of duplicating (and drifting from) it.
"""

from __future__ import annotations

import time
import uuid
from collections import deque

from fastapi import WebSocket
from sqlalchemy.ext.asyncio import AsyncSession

from buddle.config import get_settings
from buddle.core.exceptions import Unauthorized
from buddle.db.models.user import User
from buddle.security.jwt import decode_token

# Shared WS limits.
WS_AUTH_TIMEOUT_S = 10.0
WS_RATE_MAX_TURNS = 20
WS_RATE_WINDOW_S = 60.0


async def authenticate_ws(db: AsyncSession, token: str) -> User:
    """Validate an access token from the first WS frame and load the user."""
    claims = decode_token(token)
    if claims.get("type") != "access":
        raise Unauthorized("Wrong token type.")
    sub = claims.get("sub")
    if not sub:
        raise Unauthorized("Token missing subject.")
    user = await db.get(User, uuid.UUID(sub))
    if not user or not user.is_active:
        raise Unauthorized("User is inactive or not found.")
    return user


async def send_json(ws: WebSocket, model: object) -> None:
    """Send a pydantic model as a JSON text frame."""
    await ws.send_text(model.model_dump_json())  # type: ignore[attr-defined]


def rate_limited(timestamps: deque[float]) -> bool:
    """Sliding-window check. Mutates `timestamps`, True if over budget."""
    now = time.monotonic()
    while timestamps and now - timestamps[0] > WS_RATE_WINDOW_S:
        timestamps.popleft()
    if len(timestamps) >= WS_RATE_MAX_TURNS:
        return True
    timestamps.append(now)
    return False


def ws_origin_allowed(websocket: WebSocket) -> bool:
    """CSWSH guard: validate the upgrade's Origin against the allowlist.

    Browsers don't apply CORS to WebSocket upgrades, so a malicious page could
    otherwise open a socket on the user's behalf. In-band token auth already
    blocks cookie-riding, but checking Origin rejects cross-site sockets early.
    Non-browser clients send no Origin; allowed only when
    ws_allow_missing_origin is true (native apps, server-to-server, tests).
    """
    settings = get_settings()
    origin = None
    for name, value in websocket.scope.get("headers", []):
        if name == b"origin":
            origin = value.decode("latin-1")
            break
    if origin is None:
        return settings.ws_allow_missing_origin
    allowed = settings.ws_allowed_origins or settings.cors_origins
    return origin in allowed
