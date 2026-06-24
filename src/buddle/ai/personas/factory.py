"""PersonaAI factory and orchestration.

Single entry point for the rest of the codebase. Looks up the persona's
model in the registry, picks the right backend by `backend_kind`, and:

  - caches `interpret()` responses in Redis (cheap repeat-savings),
  - falls back to PersonaStub if the configured backend errors out
    (graceful degradation — pipeline keeps moving),
  - records the active backend in returned metadata.

Stage 3 may extend this with: per-user rate limiting, streaming, and
async-queued inference for long-running responses.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from buddle.ai.interfaces import (
    DialogueTurn,
    PersonaInterpretation,
    PersonaReply,
)
from buddle.ai.personas.local_hf import LocalHfPersona
from buddle.ai.personas.ondevice_webllm import OndeviceWebllmPersona
from buddle.ai.personas.vllm_endpoint import PersonaBackendError, VllmEndpointPersona
from buddle.ai.stubs.persona_stub import PersonaStub
from buddle.core.exceptions import NotFound
from buddle.core.logging import get_logger
from buddle.core.types import RedisClient
from buddle.db.models.enums import PersonaBackendKind
from buddle.db.models.persona_model import PersonaModel

log = get_logger(__name__)


class _PersonaBackend(Protocol):
    async def interpret(
        self, *, persona_name: str, model_key: str, content_raw: str
    ) -> PersonaInterpretation: ...

    async def respond_in_dialogue(
        self,
        *,
        persona_name: str,
        model_key: str,
        history: list[DialogueTurn],
        user_message: str,
        user_context: object = None,
    ) -> PersonaReply: ...


_INTERPRET_CACHE_TTL_S = 60 * 10  # 10 minutes
_INTERPRET_CACHE_PREFIX = "buddle:persona:interpret:"


def _build_backend(
    *,
    model_key: str,
    backend_kind: PersonaBackendKind,
    system_prompt: str | None,
    backend_config: dict[str, Any] | None,
    db: AsyncSession,
) -> _PersonaBackend:
    if backend_kind == PersonaBackendKind.STUB:
        return PersonaStub(db)
    if backend_kind == PersonaBackendKind.VLLM_ENDPOINT:
        return VllmEndpointPersona(
            model_key=model_key,
            system_prompt=system_prompt,
            config=backend_config,
        )
    if backend_kind == PersonaBackendKind.LOCAL_HF:
        return LocalHfPersona(
            model_key=model_key,
            system_prompt=system_prompt,
            config=backend_config,
        )
    if backend_kind == PersonaBackendKind.ONDEVICE_WEBLLM:
        return OndeviceWebllmPersona(
            model_key=model_key,
            system_prompt=system_prompt,
            config=backend_config,
        )
    # Defensive — new enum values should explicitly extend this match
    raise PersonaBackendError(f"Unsupported backend_kind: {backend_kind!r}")


async def _load_model(db: AsyncSession, model_key: str) -> PersonaModel:
    result = await db.execute(select(PersonaModel).where(PersonaModel.template_key == model_key))
    model = result.scalar_one_or_none()
    if not model:
        raise NotFound(
            f"Persona model '{model_key}' is not registered.",
            detail={"template_key": model_key},
        )
    return model


def _interpret_cache_key(*, model_key: str, persona_name: str, content_raw: str) -> str:
    h = hashlib.sha256()
    h.update(model_key.encode())
    h.update(b"\0")
    h.update(persona_name.encode())
    h.update(b"\0")
    h.update(content_raw.encode())
    return _INTERPRET_CACHE_PREFIX + h.hexdigest()


class PersonaService:
    """Stateless orchestrator. Construct per-request with the current
    DB session and Redis client; methods do their own backend dispatch."""

    def __init__(self, db: AsyncSession, redis_client: RedisClient | None = None):
        self._db = db
        self._redis = redis_client

    # ── interpret (used by post creation) ─────────────────────────────────

    async def interpret(
        self,
        *,
        persona_name: str,
        model_key: str,
        content_raw: str,
    ) -> PersonaInterpretation:
        # Cache lookup
        cache_key = _interpret_cache_key(
            model_key=model_key, persona_name=persona_name, content_raw=content_raw
        )
        if self._redis is not None:
            cached = await self._redis.get(cache_key)
            if cached:
                try:
                    payload = json.loads(cached)
                    return PersonaInterpretation(
                        content_transformed=payload["content_transformed"],
                        metadata={**payload.get("metadata", {}), "cache_hit": "true"},
                    )
                except (json.JSONDecodeError, KeyError):
                    pass  # bad cache entry; ignore and regenerate

        model = await _load_model(self._db, model_key)
        backend = _build_backend(
            model_key=model_key,
            backend_kind=model.backend_kind,
            system_prompt=model.system_prompt,
            backend_config=model.backend_config,
            db=self._db,
        )

        try:
            result = await backend.interpret(
                persona_name=persona_name,
                model_key=model_key,
                content_raw=content_raw,
            )
        except PersonaBackendError as e:
            log.warning(
                "persona.interpret.fallback_to_stub",
                model_key=model_key,
                backend=model.backend_kind.value,
                error=str(e),
            )
            stub = PersonaStub(self._db)
            result = await stub.interpret(
                persona_name=persona_name,
                model_key=model_key,
                content_raw=content_raw,
            )

        # Cache write
        if self._redis is not None:
            try:
                await self._redis.set(
                    cache_key,
                    json.dumps(
                        {
                            "content_transformed": result.content_transformed,
                            "metadata": dict(result.metadata),
                        }
                    ),
                    ex=_INTERPRET_CACHE_TTL_S,
                )
            except Exception as e:  # cache errors must not affect the user
                log.warning("persona.cache.write_failed", error=str(e))

        return result

    # ── dialogue (used by WebSocket route) ────────────────────────────────

    async def respond_in_dialogue(
        self,
        *,
        persona_name: str,
        model_key: str,
        history: list[DialogueTurn],
        user_message: str,
        recalled_memories: list[str] | None = None,
        conversation_guidance: str = "",
        user_context: object = None,
    ) -> PersonaReply:
        model = await _load_model(self._db, model_key)
        backend = _build_backend(
            model_key=model_key,
            backend_kind=model.backend_kind,
            system_prompt=model.system_prompt,
            backend_config=model.backend_config,
            db=self._db,
        )

        try:
            return await backend.respond_in_dialogue(
                persona_name=persona_name,
                model_key=model_key,
                history=history,
                user_message=user_message,
                recalled_memories=recalled_memories,
                conversation_guidance=conversation_guidance,
                user_context=user_context,
            )
        except PersonaBackendError as e:
            log.warning(
                "persona.dialogue.fallback_to_stub",
                model_key=model_key,
                backend=model.backend_kind.value,
                error=str(e),
            )
            stub = PersonaStub(self._db)
            return await stub.respond_in_dialogue(
                persona_name=persona_name,
                model_key=model_key,
                history=history,
                user_message=user_message,
                recalled_memories=recalled_memories,
                conversation_guidance=conversation_guidance,
                user_context=user_context,
            )
