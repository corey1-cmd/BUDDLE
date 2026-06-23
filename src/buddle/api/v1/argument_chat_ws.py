"""Argument/persona-AI chat WebSocket — /v1/ws/argument/{post_id}.

RAG-grounded conversation with either a post's claim (mode=claim) or its
author's public thinking (mode=author). Reuses the shared WS infrastructure
(auth, origin check, rate limiting) and the persona generation backend.

Safety is layered: the system prompt carries the mandatory "this is an AI
reconstruction, not the person" label and a no-fabrication instruction
(ai/argument/retrieval), and the persona's reply is still screened by the
leukocyte output gate before it is sent. Author opt-out → the socket closes
with a policy violation before any turn.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections import deque

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from pydantic import ValidationError

from buddle.ai.argument import ChatMode, build_chat_prompt, has_grounding
from buddle.ai.personas import PersonaService
from buddle.api.v1.ws_common import (
    WS_AUTH_TIMEOUT_S,
    WS_RATE_MAX_TURNS,
    WS_RATE_WINDOW_S,
    authenticate_ws,
    rate_limited,
    send_json,
    ws_origin_allowed,
)
from buddle.config import get_settings
from buddle.core.exceptions import NotFound, Unauthorized
from buddle.core.logging import get_logger
from buddle.db.models.enums import ContextNoteKind
from buddle.db.session import AsyncSessionLocal
from buddle.schemas.argument_chat import (
    ArgClientMessage,
    ArgClientSaveNote,
    ArgServerError,
    ArgServerMessage,
    ArgServerNoteSaved,
    ArgServerTyping,
)
from buddle.services import argument_chat_service, leukocyte_service

log = get_logger(__name__)
router = APIRouter(prefix="/ws", tags=["argument-chat"])

_LABELS = {
    ChatMode.CLAIM: "이 대화는 게시글의 주장을 공개 내용으로 구성한 AI입니다 (본인 아님).",
    ChatMode.AUTHOR: "이 대화는 글쓴이의 공개 글로 구성한 AI 재현입니다 (본인 아님).",
}


def _resolve_mode(raw: str | None) -> ChatMode:
    if raw == ChatMode.AUTHOR.value:
        return ChatMode.AUTHOR
    return ChatMode.CLAIM


@router.websocket("/argument/{post_id}")
async def argument_ws(websocket: WebSocket, post_id: uuid.UUID) -> None:
    if not get_settings().argument_enabled:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="disabled")
        return
    if not ws_origin_allowed(websocket):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="origin not allowed")
        return

    mode = _resolve_mode(websocket.query_params.get("mode"))
    await websocket.accept()

    # First frame must be the access token.
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=WS_AUTH_TIMEOUT_S)
    except (TimeoutError, WebSocketDisconnect):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="auth timeout")
        return

    token = _extract_token(raw)
    async with AsyncSessionLocal() as db:
        try:
            await authenticate_ws(db, token)
        except Unauthorized:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="unauthorized")
            return

        # Access gate: public post; author not opted out (AUTHOR mode).
        access = await argument_chat_service.check_access(db, post_id=post_id, mode=mode)
        if not access.allowed or access.post is None:
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION, reason=access.reason or "forbidden"
            )
            return
        post = access.post

    with contextlib.suppress(Exception):
        await send_json(websocket, ArgServerTyping(state="stop"))

    timestamps: deque[float] = deque()
    try:
        while True:
            raw = await websocket.receive_text()
            parsed = _parse_client(raw)
            if parsed is None:
                await send_json(
                    websocket,
                    ArgServerError(code="BAD_MESSAGE", message="형식이 올바르지 않습니다."),
                )
                continue

            if isinstance(parsed, ArgClientSaveNote):
                await _handle_save_note(websocket, post_id, parsed)
                continue

            # user_message → rate limit, retrieve, generate, screen, send.
            if rate_limited(timestamps):
                await send_json(
                    websocket,
                    ArgServerError(
                        code="RATE_LIMITED",
                        message=f"너무 빠릅니다. 최대 {WS_RATE_MAX_TURNS}/{int(WS_RATE_WINDOW_S)}초.",
                    ),
                )
                continue

            await _handle_user_message(websocket, post, mode, parsed)
    except WebSocketDisconnect:
        return
    except Exception as e:  # never crash the socket on an unexpected error
        log.warning("argument_ws.error", error=str(e))
        with contextlib.suppress(Exception):
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)


async def _handle_user_message(
    websocket: WebSocket, post: object, mode: ChatMode, msg: ArgClientMessage
) -> None:
    async with AsyncSessionLocal() as db:
        # Re-load post in this session for relationship-free retrieval.
        from buddle.db.models.post import Post

        post_row = await db.get(Post, post.id)  # type: ignore[attr-defined]
        if post_row is None:
            await send_json(
                websocket, ArgServerError(code="GONE", message="글을 찾을 수 없습니다.")
            )
            return

        ctx = await argument_chat_service.build_context(
            db, post=post_row, mode=mode, query_text=msg.content
        )
        if not has_grounding(ctx):
            await send_json(
                websocket,
                ArgServerMessage(
                    content="공개된 글에서 이 주제로 깊이 이야기할 만한 근거를 아직 찾지 못했어요.",
                    label=_LABELS[mode],
                ),
            )
            return

        prompt = build_chat_prompt(ctx)

        with contextlib.suppress(Exception):
            await send_json(websocket, ArgServerTyping(state="start"))

        # Generate via the persona backend; the RAG prompt rides in as guidance.
        # Uses the general "buddle-default" model (seeded by seed_persona_models).
        # If that model isn't registered yet (fresh DB), fall back to the stub
        # so the conversation still works instead of erroring the socket.
        svc = PersonaService(db, None)
        try:
            reply = await svc.respond_in_dialogue(
                persona_name="버들 AI",
                model_key="buddle-default",
                history=[],
                user_message=msg.content,
                conversation_guidance=prompt,
            )
            content = reply.content
        except NotFound:
            from buddle.ai.stubs.persona_stub import PersonaStub

            stub_reply = await PersonaStub(db).respond_in_dialogue(
                persona_name="버들 AI",
                model_key="buddle-default",
                history=[],
                user_message=msg.content,
                conversation_guidance=prompt,
            )
            content = stub_reply.content
        # Output-side safety gate (same as dialogue).
        screened = await leukocyte_service.screen_response(content)

        with contextlib.suppress(Exception):
            await send_json(websocket, ArgServerTyping(state="stop"))
        await send_json(websocket, ArgServerMessage(content=screened.content, label=_LABELS[mode]))


async def _handle_save_note(
    websocket: WebSocket, post_id: uuid.UUID, msg: ArgClientSaveNote
) -> None:
    async with AsyncSessionLocal() as db:
        note = await argument_chat_service.add_context_note(
            db,
            post_id=post_id,
            content=msg.content,
            kind=ContextNoteKind(msg.note_kind),
        )
        await send_json(websocket, ArgServerNoteSaved(note_id=note.id))


def _extract_token(raw: str) -> str:
    import json

    try:
        data = json.loads(raw)
        if isinstance(data, dict) and "token" in data:
            return str(data["token"])
    except (json.JSONDecodeError, ValueError):
        pass
    return raw.strip()


def _parse_client(raw: str) -> ArgClientMessage | ArgClientSaveNote | None:
    import json

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        if data.get("type") == "save_note":
            return ArgClientSaveNote.model_validate(data)
        return ArgClientMessage.model_validate(data)
    except ValidationError:
        return None
