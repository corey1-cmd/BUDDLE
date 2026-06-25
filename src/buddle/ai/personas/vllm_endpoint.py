"""vLLM / TGI HTTP backend for persona inference.

Targets the OpenAI-compatible chat-completions endpoint that vLLM and
text-generation-inference both expose. backend_config contract:

    {
      "endpoint_url":  "https://internal.vllm/v1",   # required
      "model":         "qwen3-7b-instruct",          # required
      "lora_adapter":  "buddle/poet-v2",             # optional; vLLM LoRA name
      "api_key":       "...",                        # optional
      "temperature":   0.7,                          # optional
      "max_tokens":    512,                          # optional
      "timeout_s":     30                            # optional
    }

The adapter retries once on transient 5xx / network errors. On hard failure
it raises PersonaBackendError, which the calling pipeline must translate
into a graceful fallback (Stage 1 stub) rather than 500ing the user.
"""

from __future__ import annotations

from typing import Any

import httpx

from buddle.ai.interfaces import (
    DialogueTurn,
    PersonaInterpretation,
    PersonaReply,
)
from buddle.ai.personas.prompts import (
    build_dialogue_messages,
    build_interpret_messages,
)
from buddle.core.logging import get_logger

log = get_logger(__name__)


class PersonaBackendError(RuntimeError):
    """Raised when a backend call fails after retries. Caller decides fallback."""


def _config_get(config: dict[str, Any] | None, key: str, default: Any = None) -> Any:
    return (config or {}).get(key, default)


class VllmEndpointPersona:
    """OpenAI-compat HTTP persona backend."""

    def __init__(self, *, model_key: str, system_prompt: str | None, config: dict[str, Any] | None):
        self._model_key = model_key
        self._system_prompt = system_prompt
        self._config = config or {}

        if not self._config.get("endpoint_url"):
            raise PersonaBackendError(
                f"backend_config.endpoint_url is required for model '{model_key}'"
            )
        if not self._config.get("model"):
            raise PersonaBackendError(f"backend_config.model is required for model '{model_key}'")

    # ── public API ────────────────────────────────────────────────────────

    async def interpret(
        self,
        *,
        persona_name: str,
        model_key: str,
        content_raw: str,
    ) -> PersonaInterpretation:
        messages = build_interpret_messages(
            persona_name=persona_name,
            model_system_prompt=self._system_prompt,
            content_raw=content_raw,
        )
        text = await self._chat(messages)
        return PersonaInterpretation(
            content_transformed=text.strip(),
            metadata={
                "backend": "vllm_endpoint",
                "model_key": model_key,
                "served_model": str(self._config.get("model")),
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
        knowledge_context: list[str] | None = None,
    ) -> PersonaReply:
        messages = build_dialogue_messages(
            persona_name=persona_name,
            model_system_prompt=self._system_prompt,
            history=history,
            user_message=user_message,
            recalled_memories=recalled_memories,
            conversation_guidance=conversation_guidance,
            user_context=user_context,  # type: ignore[arg-type]
            knowledge_context=knowledge_context,
        )
        text = await self._chat(messages)
        return PersonaReply(
            content=text.strip(),
            metadata={
                "backend": "vllm_endpoint",
                "model_key": model_key,
                "served_model": str(self._config.get("model")),
            },
        )

    # ── internals ─────────────────────────────────────────────────────────

    async def _chat(self, messages: list[dict[str, str]]) -> str:
        endpoint = str(self._config["endpoint_url"]).rstrip("/")
        url = f"{endpoint}/chat/completions"

        payload: dict[str, Any] = {
            "model": self._config["model"],
            "messages": messages,
            "temperature": float(_config_get(self._config, "temperature", 0.7)),
            "max_tokens": int(_config_get(self._config, "max_tokens", 512)),
            "stream": False,
        }
        # vLLM LoRA selection: served as the 'model' name with the LoRA loaded
        # at server start, or via the 'lora_request' extension. Most deployments
        # use the former (simpler), so we pass it through if supplied.
        lora = _config_get(self._config, "lora_adapter")
        if lora:
            payload["lora_request"] = {"lora_name": lora}

        headers: dict[str, str] = {"Content-Type": "application/json"}
        api_key = _config_get(self._config, "api_key")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        timeout_s = float(_config_get(self._config, "timeout_s", 30))

        last_exc: Exception | None = None
        for attempt in (1, 2):
            try:
                async with httpx.AsyncClient(timeout=timeout_s) as client:
                    resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"upstream {resp.status_code}", request=resp.request, response=resp
                    )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                if not isinstance(content, str):
                    raise PersonaBackendError("Malformed response: content is not a string")
                return content
            except (httpx.HTTPError, KeyError, ValueError) as e:
                last_exc = e
                log.warning(
                    "persona.vllm.attempt_failed",
                    model_key=self._model_key,
                    attempt=attempt,
                    error=str(e),
                )

        raise PersonaBackendError(
            f"vllm_endpoint call failed after retries: {last_exc}"
        ) from last_exc
