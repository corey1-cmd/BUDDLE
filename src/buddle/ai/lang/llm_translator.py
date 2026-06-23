"""LLM-backed translator (vLLM / OpenAI-chat compatible).

Translates while preserving the persona's voice and the thought's intent
(not a literal word swap). Korean<->English first; the same prompt generalizes
to other pairs. Fails with TranslationError so callers can degrade gracefully.
"""

from __future__ import annotations

from typing import Any

import httpx

from buddle.ai.lang.languages import Language
from buddle.ai.lang.translator import TranslationError
from buddle.core.logging import get_logger

log = get_logger(__name__)

_SYSTEM = (
    "You are a faithful translator for a social app. Translate the user's "
    "message from {src} to {tgt}. Preserve meaning, tone, and the writer's "
    "voice; convey the same intent naturally rather than translating word for "
    "word. Output ONLY the translated text, no quotes or notes."
)


class LlmTranslator:
    def __init__(self, config: dict[str, Any] | None = None):
        self._config = config or {}
        if not self._config.get("endpoint_url"):
            raise TranslationError("translation backend_config.endpoint_url is required")
        self._model = str(self._config.get("model", "qwen2.5:7b"))
        self._timeout = float(self._config.get("timeout_s", 20))

    async def translate(self, text: str, *, source: Language, target: Language) -> str:
        if source == target:
            return text
        url = self._config["endpoint_url"].rstrip("/") + "/chat/completions"
        headers = {}
        if self._config.get("api_key"):
            headers["Authorization"] = f"Bearer {self._config['api_key']}"
        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": _SYSTEM.format(
                        src=source.english_name, tgt=target.english_name
                    ),
                },
                {"role": "user", "content": text},
            ],
            "temperature": 0.3,
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            log.exception("lang.llm_translate_failed")
            raise TranslationError(f"translate failed: {e}") from e
        return _extract(data) or text

    async def translate_many(
        self, text: str, *, source: Language, targets: list[Language]
    ) -> dict[Language, str]:
        out: dict[Language, str] = {}
        for t in targets:
            out[t] = await self.translate(text, source=source, target=t)
        return out


def _extract(data: dict[str, Any]) -> str:
    try:
        choices = data.get("choices") or []
        if choices:
            return str((choices[0].get("message") or {}).get("content", "")).strip()
        if "message" in data:
            return str(data["message"].get("content", "")).strip()
    except (AttributeError, IndexError, KeyError):
        pass
    return ""
