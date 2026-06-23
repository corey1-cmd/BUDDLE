"""Request body size cap middleware.

Rejects oversized request bodies with 413 before the JSON parser allocates
them, bounding memory-amplification DoS. Two layers:

1. **Content-Length fast path** — a declared length over the cap is rejected
   immediately, without reading the body.
2. **Streaming guard** — chunked or length-omitted requests can't be trusted
   on their header, so we tally bytes inside a wrapped ``receive`` and, the
   moment the running total crosses the cap, stop feeding the app and return
   413. We intercept the response so the handler can't also write one (no
   double-start).

WebSocket scopes pass through untouched — their framing is bounded by the
message schema and the dialogue route's own per-connection limits.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_PAYLOAD_TOO_LARGE = 413
_BODY = b'{"code":"PAYLOAD_TOO_LARGE","message":"Request too large."}'


async def _send_413(send: Send) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": _PAYLOAD_TOO_LARGE,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(_BODY)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": _BODY, "more_body": False})


class BodySizeLimitMiddleware:
    """ASGI middleware enforcing a hard cap on request body bytes."""

    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Layer 1: declared Content-Length fast-reject (no body read).
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    if int(value) > self.max_body_bytes:
                        await _send_413(send)
                        return
                except ValueError:
                    pass  # malformed header → rely on the streaming guard
                break

        # Layer 2: tally streamed bytes; on overflow, send 413 and swallow the
        # app's own response so we never emit two response-start messages.
        state = {"received": 0, "tripped": False, "started": False}

        async def guarded_receive() -> Message:
            message = await receive()
            if message["type"] == "http.request":
                state["received"] += len(message.get("body", b""))
                if state["received"] > self.max_body_bytes:
                    state["tripped"] = True
                    # Truncate this chunk and signal end-of-stream so the app's
                    # parser unblocks; we'll override its response below.
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        async def guarded_send(message: Message) -> None:
            if state["tripped"]:
                # Emit our 413 exactly once, drop everything the app produces.
                if not state["started"]:
                    state["started"] = True
                    await _send_413(send)
                return
            await send(message)

        await self.app(scope, guarded_receive, guarded_send)

        # Edge case: body overflowed but the app produced no output at all.
        if state["tripped"] and not state["started"]:
            state["started"] = True
            await _send_413(send)
