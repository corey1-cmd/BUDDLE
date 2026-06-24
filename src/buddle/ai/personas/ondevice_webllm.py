"""On-device (WebLLM/WebGPU) persona backend marker.

When a persona's backend_kind is 'ondevice_webllm', the actual inference
happens inside the user's browser via WebLLM (AIMO's WebGPU integration
re-used here). The server contributes only:

  - the system_prompt (sent to the client),
  - the backend_config (e.g., which on-device model to load).

For server-side flows that absolutely need a server-generated string (post
creation by an offline client, for example), this backend raises a sentinel
that the calling pipeline interprets as 'defer to client / fallback to stub'.

In Stage 2 the post pipeline doesn't yet support deferral, so for
ondevice_webllm we fall back to a stub-style transformation on the server
side. The WebSocket dialogue route should never invoke this backend
server-side; the client handles dialogue locally and only persists turns.
"""

from __future__ import annotations

from typing import Any

from buddle.ai.interfaces import (
    DialogueTurn,
    PersonaInterpretation,
    PersonaReply,
)


class OndeviceWebllmPersona:
    """Server-side stub-style behaviour for ondevice_webllm personas.

    The real inference is in the client; this server-side object exists so
    that uniform server flows (e.g. post creation from a non-browser caller)
    still produce a sensible output.
    """

    def __init__(self, *, model_key: str, system_prompt: str | None, config: dict[str, Any] | None):
        self._model_key = model_key
        self._system_prompt = system_prompt
        self._config = config or {}

    async def interpret(
        self,
        *,
        persona_name: str,
        model_key: str,
        content_raw: str,
    ) -> PersonaInterpretation:
        transformed = f"[{persona_name}] {content_raw}".strip()
        return PersonaInterpretation(
            content_transformed=transformed,
            metadata={
                "backend": "ondevice_webllm",
                "model_key": model_key,
                "deferred_to_client": "true",
                "client_model": str(self._config.get("client_model", "")),
            },
        )

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
        # Defensive: the WebSocket route shouldn't reach here for an
        # on-device persona because the client handles dialogue. If it does,
        # produce a minimal acknowledgement so the conversation doesn't break.
        return PersonaReply(
            content=f"[{persona_name}] {user_message}",
            metadata={
                "backend": "ondevice_webllm",
                "deferred_to_client": "true",
                "model_key": model_key,
            },
        )
