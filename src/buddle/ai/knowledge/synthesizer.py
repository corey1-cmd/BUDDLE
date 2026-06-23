"""Synthesizer abstraction — turns a SynthesisPlan into prose (Layer B).

Same swap-in pattern as ethics/translation. StubSynthesizer is deterministic
(uses synthesis.fallback_summary, no LLM) so the whole pipeline tests offline;
LlmSynthesizer uses a chat endpoint with a prompt that recombines + reasons and
deliberately PRESENTS PERSPECTIVES rather than asserting one conclusion.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import httpx

from buddle.ai.knowledge.synthesis import SynthesisPlan, UnitView, fallback_summary
from buddle.core.logging import get_logger

log = get_logger(__name__)


class SynthesisError(RuntimeError):
    pass


@runtime_checkable
class Synthesizer(Protocol):
    async def synthesize(
        self, *, topic: str, units: list[UnitView], plan: SynthesisPlan, language: str
    ) -> tuple[str, str]: ...  # (summary, reasoning_trace)


class StubSynthesizer:
    """Deterministic synthesizer — no LLM. Uses the pure fallback."""

    async def synthesize(
        self, *, topic: str, units: list[UnitView], plan: SynthesisPlan, language: str
    ) -> tuple[str, str]:
        return fallback_summary(plan, units)


_SYSTEM = (
    "You synthesize many short thoughts from a community into an insight. "
    "Recombine related thoughts, reason about commonalities, tensions, and "
    "implications, and PRESENT PERSPECTIVES — do NOT assert a single conclusion "
    "or make decisions for anyone. Respond in {lang}. Output two sections "
    "exactly:\nSUMMARY: <a few sentences>\nREASONING: <how you grouped and what "
    "you inferred>"
)


class LlmSynthesizer:
    def __init__(self, config: dict[str, Any] | None = None):
        self._config = config or {}
        if not self._config.get("endpoint_url"):
            raise SynthesisError("synthesis backend_config.endpoint_url is required")
        self._model = str(self._config.get("model", "qwen2.5:7b"))
        self._timeout = float(self._config.get("timeout_s", 30))

    async def synthesize(
        self, *, topic: str, units: list[UnitView], plan: SynthesisPlan, language: str
    ) -> tuple[str, str]:
        gists = "\n".join(f"- {u.gist}" for u in units[:30])
        url = self._config["endpoint_url"].rstrip("/") + "/chat/completions"
        headers = {}
        if self._config.get("api_key"):
            headers["Authorization"] = f"Bearer {self._config['api_key']}"
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _SYSTEM.format(lang=language)},
                {"role": "user", "content": f"Topic: {topic}\nThoughts:\n{gists}"},
            ],
            "temperature": 0.5,
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            log.exception("knowledge.synthesize_failed")
            raise SynthesisError(f"synthesize failed: {e}") from e
        return _parse_sections(_extract(data), plan, units)


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


def _parse_sections(
    text: str, plan: SynthesisPlan, units: list[UnitView]
) -> tuple[str, str]:
    """Split a 'SUMMARY:/REASONING:' response; fall back to deterministic on miss."""
    if not text:
        return fallback_summary(plan, units)
    summary, reasoning = "", ""
    low = text.lower()
    if "summary:" in low and "reasoning:" in low:
        s_idx = low.index("summary:") + len("summary:")
        r_idx = low.index("reasoning:")
        summary = text[s_idx:r_idx].strip()
        reasoning = text[r_idx + len("reasoning:") :].strip()
    if not summary:
        summary = text.strip()
    if not reasoning:
        _, reasoning = fallback_summary(plan, units)
    return summary, reasoning


def get_synthesizer() -> Synthesizer:
    from buddle.config import get_settings

    settings = get_settings()
    kind = settings.synthesis_provider
    if kind == "stub":
        return StubSynthesizer()
    if kind == "llm_endpoint":
        return LlmSynthesizer(
            {
                "endpoint_url": settings.synthesis_endpoint_url,
                "model": settings.synthesis_model_id or "qwen2.5:7b",
            }
        )
    raise SynthesisError(f"Unknown synthesis_provider: {kind!r}")
