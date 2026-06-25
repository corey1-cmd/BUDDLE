"""WebSocket dialogue route — /v1/ws/dialogue/{persona_id}.

Auth: pass the access token as `?token=...` query string (browsers can't
set Authorization headers on WebSocket upgrades).

Lifecycle:
  1. Validate token + persona ownership.
  2. Loop: receive user_message frame -> persist -> call PersonaService
     -> persist persona reply -> send persona_message frame.

Hardening:
  - Per-connection sliding-window rate limit (max N turns / window).
  - Frame size is bounded by ClientUserMessage (max_length=4000).
  - Failures send an error frame; connection closes only on auth/protocol
    failures or internal errors.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
import time
import uuid
from collections import deque

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from buddle.ai.affect.perception import perceive
from buddle.ai.cognition import process_information
from buddle.ai.conversation import (
    ConversationContext,
    ConversationSituation,
    Mood,
    TurnAffect,
    build_conversation_guidance,
    detect_decline_needed,
    detect_distress,
    detect_winding_down,
    is_request,
    situation_for,
)
from buddle.ai.interfaces import DialogueTurn
from buddle.ai.memory import extract_candidates
from buddle.ai.personas import PersonaService
from buddle.config import get_settings
from buddle.core.exceptions import Unauthorized
from buddle.core.logging import get_logger
from buddle.db.models.enums import MessageRole
from buddle.db.models.persona import Persona
from buddle.db.models.user import User
from buddle.db.session import AsyncSessionLocal
from buddle.schemas.dialogue import (
    ClientUserMessage,
    ServerError,
    ServerPersonaMessage,
    ServerTyping,
)
from buddle.security.jwt import decode_token
from buddle.ai.cognition.user_context import UserContextFact, merge_facts
from buddle.services.user_context_service import extract_facts_llm
from buddle.services import (
    conversation_service,
    dialogue_service,
    leukocyte_service,
    memory_service,
    profile_service,
)

log = get_logger(__name__)

router = APIRouter(prefix="/ws", tags=["dialogue"])

# Deadline for the client to send its auth frame after connecting.
_AUTH_TIMEOUT_S = 10.0

# Per-connection rate limit: at most MAX_TURNS within WINDOW_S seconds.
_RATE_MAX_TURNS = 20
_RATE_WINDOW_S = 60.0
_HISTORY_WINDOW = 40


async def _authenticate(db: AsyncSession, token: str) -> User:
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


async def _load_owned_persona(
    db: AsyncSession, user: User, persona_id: uuid.UUID
) -> Persona | None:
    result = await db.execute(
        select(Persona).where(
            Persona.id == persona_id,
            Persona.user_id == user.id,
            Persona.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def _send_json(ws: WebSocket, model) -> None:  # type: ignore[no-untyped-def]
    await ws.send_text(model.model_dump_json())


def _rate_limited(timestamps: deque[float]) -> bool:
    """Sliding-window check. Mutates `timestamps`, returns True if over budget."""
    now = time.monotonic()
    while timestamps and now - timestamps[0] > _RATE_WINDOW_S:
        timestamps.popleft()
    if len(timestamps) >= _RATE_MAX_TURNS:
        return True
    timestamps.append(now)
    return False


def _ws_origin_allowed(websocket: WebSocket) -> bool:
    """CSWSH guard: validate the upgrade's Origin against the allowlist.

    Browsers don't apply CORS to WebSocket upgrades, so a malicious page could
    otherwise open a socket on the user's behalf. In-band token auth already
    blocks the classic cookie-riding attack, but checking Origin closes the
    gap for any future cookie/session use and rejects cross-site sockets early.

    Non-browser clients send no Origin header; those are allowed only when
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


@dataclasses.dataclass(frozen=True, slots=True)
class _TurnAnalysis:
    """Per-turn conversation analysis, computed once before generation and
    reused when persisting the structured turn + updating the relationship."""

    situation: ConversationSituation
    affect: TurnAffect
    opened_disclosure: bool
    was_followup: bool
    is_reciprocity: bool
    salient_topics: tuple[str, ...]
    mood: Mood


def _find_dangling_thread(window, current_topics: set[str]) -> str | None:  # type: ignore[no-untyped-def]
    """Find an earlier topic the user raised that then dropped out of the
    conversation (Principle 12 — Recover Lost Moments).

    Heuristic: a topic that appeared in an EARLIER user turn but is absent from
    both the latest turns and the current message. Deterministic; returns the
    most recent such topic (closest to recoverable), or None.
    """
    turns = getattr(window, "turns", [])
    if len(turns) < 3:
        return None
    # Topics in the latest two turns (considered "still live").
    live: set[str] = set(current_topics)
    for t in turns[-2:]:
        # WindowTurn has no per-turn topics; approximate liveness via substring.
        for topic in getattr(window, "salient_topics", ())[:8]:
            if topic in (t.content or ""):
                live.add(topic)
    # An earlier-mentioned salient topic no longer live → dangling.
    for topic in getattr(window, "salient_topics", ())[:8]:
        if topic in live:
            continue
        # Confirm it was actually raised earlier in the window.
        for t in turns[:-2]:
            if t.role == "user" and topic in (t.content or ""):
                return topic
    return None


async def _build_conversation_guidance(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    persona_id: uuid.UUID,
    user_id: uuid.UUID,
    user_message: str,
) -> tuple[str, _TurnAnalysis]:
    """Compute the conversation-psychology guidance for this user turn.

    Reads the recent window (working set), the persona<->user relationship
    level, and runs the pure affect/situation analysis, then assembles the
    conditional principle guidance. Returns (guidance_text, analysis) so the
    caller can both inject the guidance and persist the analysis afterward.
    """
    window = await conversation_service.recent_window(db, session_id=session_id, n=10)
    rel = await conversation_service.load_relationship(db, persona_id=persona_id, user_id=user_id)

    # Pure affect + intent → situation (reuse EKB info processing).
    affect = perceive(user_message)
    info = process_information(user_message)
    situation = situation_for(info.intent, valence=affect.valence)
    turn_affect = TurnAffect(valence=affect.valence, intensity=affect.intensity)

    # Run disclosure extraction ONCE and reuse (it's the same deterministic call
    # for both the self-disclosure signal and the interest-mention trigger).
    candidates = extract_candidates(user_message)
    # Self-disclosure: did this turn produce a durable memory candidate?
    opened_disclosure = bool(candidates)
    # Follow-up / reciprocity: the persona's previous turn ended with a question.
    is_reciprocity = window.persona_last_was_question
    was_followup = window.persona_last_was_question

    # An interest/taste mention this turn (Principle 2 trigger).
    mentioned_interest = any(c.kind.value == "preference" for c in candidates)
    # Topic shift heuristic: user's salient tokens don't overlap window topics.
    user_topics = set(info.topics)
    is_topic_shift = bool(user_topics) and not (user_topics & set(window.salient_topics))

    # Principles 11-21 signals — deterministic heuristics (no LLM), inferred from
    # the message text + window. These only RAISE guidance, never block, so a
    # false positive costs at most one extra gentle nudge.
    distress = detect_distress(user_message)
    surface_request_with_distress = distress and is_request(user_message)
    winding_down = detect_winding_down(user_message)
    declining = detect_decline_needed(user_message)
    # Persona is "offering a choice" when the user is seeking a suggestion
    # (advice/recommendation request) — that's when escape-routes + load-reduction
    # matter most.
    persona_offering_choice = is_request(user_message) and situation in (
        ConversationSituation.SOCIAL,
        ConversationSituation.OBJECTIVE,
    )
    # Dangling thread (Principle 12): an earlier topic the user raised that the
    # persona asked about but never got followed up — i.e. a window topic absent
    # from the most recent turns. Surface the oldest such topic.
    dangling_thread = _find_dangling_thread(window, current_topics=user_topics)

    ctx = ConversationContext(
        situation=situation,
        mood=window.mood,
        relationship_level=int(rel.level),
        window_topics=window.salient_topics,
        user_was_asked=is_reciprocity,
        user_mentioned_interest=mentioned_interest,
        is_topic_shift=is_topic_shift,
        surface_request_with_distress=surface_request_with_distress,
        dangling_thread=dangling_thread,
        persona_offering_choice=persona_offering_choice,
        winding_down=winding_down,
        declining=declining,
    )
    guidance = build_conversation_guidance(ctx)

    analysis = _TurnAnalysis(
        situation=situation,
        affect=turn_affect,
        opened_disclosure=opened_disclosure,
        was_followup=was_followup,
        is_reciprocity=is_reciprocity,
        salient_topics=tuple(info.topics[:8]),
        mood=window.mood,
    )
    return guidance, analysis


async def _record_conversation_turns(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    persona_id: uuid.UUID,
    user_id: uuid.UUID,
    user_message: str,
    persona_reply: str,
    analysis: _TurnAnalysis,
) -> None:
    """Persist the structured user + persona turns and update the relationship.

    The relationship update applies the Gottman emotional-bank-account delta;
    the user turn stores that delta so the bond's history is auditable.
    """
    _rel, delta, _leveled = await conversation_service.update_relationship(
        db,
        persona_id=persona_id,
        user_id=user_id,
        affect=analysis.affect,
        opened_disclosure=analysis.opened_disclosure,
        is_reciprocity=analysis.is_reciprocity,
        mood=analysis.mood,
        commit=False,
    )
    await conversation_service.record_turn(
        db,
        session_id=session_id,
        persona_id=persona_id,
        role=MessageRole.USER,
        content=user_message,
        situation=analysis.situation,
        valence=analysis.affect.valence,
        intensity=analysis.affect.intensity,
        was_followup=analysis.was_followup,
        opened_disclosure=analysis.opened_disclosure,
        salient_topics=list(analysis.salient_topics),
        affinity_delta_value=delta,
        commit=False,
    )
    await conversation_service.record_turn(
        db,
        session_id=session_id,
        persona_id=persona_id,
        role=MessageRole.PERSONA,
        content=persona_reply,
        commit=False,
    )
    await db.commit()


@router.websocket("/dialogue/{persona_id}")
async def dialogue_ws(
    websocket: WebSocket,
    persona_id: uuid.UUID,
) -> None:
    """Authenticate via the FIRST message frame, not a query string.

    Handshake:
      1. Server checks Origin (CSWSH guard), then accepts the connection.
      2. Client sends {"type": "auth", "token": "<access_token>"} as the first
         text frame (a short auth deadline applies).
      3. Server validates token + persona ownership; on failure closes 1008.

    Passing the token in-band (not as ?token=) keeps it out of server/proxy
    access logs and browser history — closing a common token-leak vector.
    """
    # CSWSH guard runs before accept(): reject cross-origin upgrades outright.
    if not _ws_origin_allowed(websocket):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="origin not allowed")
        return

    await websocket.accept()

    # 1. Receive the auth frame (bounded wait to avoid idle unauth sockets).
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=_AUTH_TIMEOUT_S)
    except (TimeoutError, WebSocketDisconnect):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="auth timeout")
        return

    token: str | None = None
    try:
        frame = json.loads(raw)
        if frame.get("type") == "auth":
            tok = frame.get("token")
            token = tok if isinstance(tok, str) else None
    except (json.JSONDecodeError, AttributeError):
        token = None

    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="expected auth frame")
        return

    async with AsyncSessionLocal() as auth_db:
        try:
            user = await _authenticate(auth_db, token)
        except Unauthorized as e:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=str(e.message))
            return
        except (ValueError, KeyError):
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="invalid token")
            return

        persona = await _load_owned_persona(auth_db, user, persona_id)
        if persona is None:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="persona not found")
            return

    # Signal successful authentication so the client may start sending messages.
    with contextlib.suppress(Exception):
        await websocket.send_text(json.dumps({"type": "auth_ok"}))

    redis_client = getattr(websocket.app.state, "redis", None)
    turn_timestamps: deque[float] = deque()
    # Per-connection user context: facts the user explicitly states accumulate
    # here across turns. Keyed by session_id so multi-session connections stay
    # isolated. EKB Search reads this as "prior knowledge about this user".
    session_user_contexts: dict[str, UserContextFact] = {}

    log.info(
        "ws.dialogue.connected",
        user_id=str(user.id),
        persona_id=str(persona_id),
        model_key=persona.model_key,
    )

    try:
        while True:
            raw = await websocket.receive_text()

            try:
                data = json.loads(raw)
                client_msg = ClientUserMessage.model_validate(data)
            except (json.JSONDecodeError, ValidationError) as e:
                await _send_json(
                    websocket, ServerError(code="BAD_FRAME", message=f"Invalid frame: {e}")
                )
                continue

            if _rate_limited(turn_timestamps):
                await _send_json(
                    websocket,
                    ServerError(
                        code="RATE_LIMITED",
                        message=f"Too many messages. Max {_RATE_MAX_TURNS}/{int(_RATE_WINDOW_S)}s.",
                    ),
                )
                continue

            async with AsyncSessionLocal() as turn_db:
                await dialogue_service.record_user_message(
                    turn_db, persona_id, client_msg.content, session_id=client_msg.session_id
                )

                history = await dialogue_service.load_recent_history(
                    turn_db, persona_id, session_id=client_msg.session_id, limit=_HISTORY_WINDOW
                )
                if history and history[-1].role == "user":
                    history = history[:-1]

                # LTM recall (EKB Search): cross-session memories for this
                # persona, ranked by recency·importance·relevance. Memory must
                # never break the dialogue — failures degrade to no recall.
                recalled: list[str] = []
                if get_settings().memory_enabled:
                    try:
                        recalled = [
                            m.content
                            for m in await memory_service.recall(
                                turn_db, persona_id=persona_id, query_text=client_msg.content
                            )
                        ]
                    except Exception as e:
                        log.warning("memory.recall_failed", error=str(e))

                # Conversation psychology: build the relationship/mood/principle
                # guidance from the recent window + the persona<->user bond.
                # Never breaks the dialogue — on failure, generation proceeds
                # without the guidance block.
                convo_guidance = ""
                convo_analysis: _TurnAnalysis | None = None
                if get_settings().conversation_enabled and client_msg.session_id is not None:
                    try:
                        convo_guidance, convo_analysis = await _build_conversation_guidance(
                            turn_db,
                            session_id=client_msg.session_id,
                            persona_id=persona_id,
                            user_id=user.id,
                            user_message=client_msg.content,
                        )
                    except Exception as e:
                        log.warning("conversation.guidance_failed", error=str(e))

                # EKB Search — user-disclosed facts (internal knowledge source).
                # Extract facts from the current message and merge into the
                # session's accumulated context. Opinions are never captured here.
                # The LLM extractor judges precisely (e.g. "나는 행복해" yields no
                # name); it is gated by a cheap regex so most turns skip the call,
                # and degrades to no facts on failure. Never breaks the dialogue.
                session_key = str(client_msg.session_id) if client_msg.session_id else "_nosession"
                try:
                    new_facts = await extract_facts_llm(
                        client_msg.content, settings=get_settings()
                    )
                except Exception as e:
                    log.warning("user_context.extract_failed", error=str(e))
                    new_facts = UserContextFact()
                accumulated_ctx = merge_facts(
                    session_user_contexts.get(session_key, UserContextFact()),
                    new_facts,
                )
                session_user_contexts[session_key] = accumulated_ctx

                # Current-message topics — pure, computed once and reused by the
                # news (external) and knowledge-space (internal) injectors below.
                msg_topics = process_information(client_msg.content).topics

                # EKB Stage B — external news context (mediator-delivered).
                # The hourly news pipeline stores AI-mediated briefings in Redis;
                # here we surface them to the persona ONLY when the current
                # message's topics overlap a briefing's tags, so casual turns are
                # never derailed by unrelated tech news. Injected through the
                # existing mediator_bundle channel (renders as a background note
                # and sets has_external in the cognition pipeline). Never breaks
                # the dialogue — any failure degrades to no news context.
                if redis_client is not None and get_settings().news_tick_interval_s > 0:
                    try:
                        from buddle.services.news_service import (
                            build_news_context_block,
                            get_news_briefings,
                            get_news_digest,
                        )

                        if msg_topics:
                            briefings = await get_news_briefings(
                                redis_client,
                                topics=msg_topics,
                                limit=3,
                                require_topic_match=True,
                            )
                            # Only when the conversation actually touches the news
                            # do we add the mediator-combined digest as the lead.
                            if briefings:
                                digest = str((await get_news_digest(redis_client)).get("text", ""))
                                news_block = build_news_context_block(briefings, digest=digest)
                                if news_block:
                                    history = [
                                        *history,
                                        DialogueTurn(role="mediator_bundle", content=news_block),
                                    ]
                    except Exception as e:
                        log.warning("news.context_inject_failed", error=str(e))

                # EKB Search — the user's own knowledge space (Layer B). The
                # persona draws on units distilled from the user's posts
                # (leukocyte-screened, mediator-tagged, filed into the topic's
                # conversation pool) that match the current topic. This closes the
                # loop: 글 → 백혈구·매개자 → 지식공간 → 대화. Read-only on an
                # isolated session (fetch_context records a context-ref + commits),
                # topic-gated, fail-safe. Same mediator_bundle delivery as news.
                if msg_topics:
                    try:
                        from buddle.services import knowledge_service

                        gists: list[str] = []
                        seen_g: set[str] = set()
                        async with AsyncSessionLocal() as kn_db:
                            for t in msg_topics[:2]:
                                bundle = await knowledge_service.fetch_context(
                                    kn_db,
                                    persona_id,
                                    topic=t,
                                    requesting_persona_id=persona_id,
                                    limit=4,
                                )
                                for it in bundle.items:
                                    if it.gist and it.gist not in seen_g:
                                        seen_g.add(it.gist)
                                        gists.append(it.gist)
                        if gists:
                            kn_block = (
                                "[당신의 지식 공간 — 사용자가 쓴 글에서 정리된 내용입니다. "
                                "자연스럽게만 활용하고 나열하지 마세요]\n"
                                + "\n".join(f"- {g[:160]}" for g in gists[:5])
                            )
                            history = [
                                *history,
                                DialogueTurn(role="mediator_bundle", content=kn_block),
                            ]
                    except Exception as e:
                        log.warning("knowledge.context_inject_failed", error=str(e))

                with contextlib.suppress(Exception):
                    await _send_json(websocket, ServerTyping(state="start"))

                persona_svc = PersonaService(turn_db, redis_client)
                reply = await persona_svc.respond_in_dialogue(
                    persona_name=persona.name,
                    model_key=persona.model_key,
                    history=history,
                    user_message=client_msg.content,
                    recalled_memories=recalled or None,
                    conversation_guidance=convo_guidance,
                    user_context=accumulated_ctx,
                )

                # Output-side ethics gate: screen the persona's OWN reply before
                # it is stored/sent. Response-side screening catches unsafe
                # generations that slipped past the input gate (more robust to
                # adversarial prompts). On block, a safe fallback replaces it.
                screened = await leukocyte_service.screen_response(reply.content)
                safe_content = screened.content

                await dialogue_service.record_persona_message(
                    turn_db, persona_id, safe_content, session_id=client_msg.session_id
                )

                with contextlib.suppress(Exception):
                    await _send_json(websocket, ServerTyping(state="stop"))

                await _send_json(
                    websocket,
                    ServerPersonaMessage(content=safe_content, metadata=dict(reply.metadata)),
                )

                # LTM observation (EKB Retention persisted): runs after the
                # reply is already on the wire, so it never adds user-visible
                # latency; failures are logged and swallowed.
                if get_settings().memory_enabled:
                    try:
                        await memory_service.observe_turn(
                            turn_db,
                            persona_id=persona_id,
                            user_text=client_msg.content,
                            session_id=client_msg.session_id,
                        )
                    except Exception as e:
                        log.warning("memory.observe_failed", error=str(e))

                # Trait observation (profile layer): same post-reply timing,
                # same never-break-the-dialogue posture. Sovereignty guards
                # (opt-out / user-edit freeze) live inside the service.
                if get_settings().profile_enabled:
                    try:
                        await profile_service.observe_text(
                            turn_db, user_id=user.id, text=client_msg.content
                        )
                    except Exception as e:
                        log.warning("profile.observe_failed", error=str(e))

                # Conversation psychology persistence: record both structured
                # turns (the re-readable log) and update the relationship score
                # (Gottman emotional bank account). Post-reply; never blocks.
                if (
                    get_settings().conversation_enabled
                    and convo_analysis is not None
                    and client_msg.session_id is not None
                ):
                    try:
                        await _record_conversation_turns(
                            turn_db,
                            session_id=client_msg.session_id,
                            persona_id=persona_id,
                            user_id=user.id,
                            user_message=client_msg.content,
                            persona_reply=safe_content,
                            analysis=convo_analysis,
                        )
                    except Exception as e:
                        log.warning("conversation.persist_failed", error=str(e))

    except WebSocketDisconnect:
        log.info(
            "ws.dialogue.disconnected",
            user_id=str(user.id),
            persona_id=str(persona_id),
        )
    except Exception as e:
        log.exception(
            "ws.dialogue.unhandled",
            user_id=str(user.id),
            persona_id=str(persona_id),
            error=str(e),
        )
        with contextlib.suppress(Exception):
            await _send_json(
                websocket,
                ServerError(code="INTERNAL", message="Unexpected server error."),
            )
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
