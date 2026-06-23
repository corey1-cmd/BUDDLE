"""Llama Guard 3 ethics classifier adapter.

Calls a Llama-Guard-3-style chat endpoint (vLLM / Ollama / TGI compatible) and
parses its canonical output format into our MLCommons CategoryResult list:

    line 1: "safe" | "unsafe"
    line 2 (if unsafe): comma-separated violated category codes, e.g. "S1,S10"

Llama Guard 3's categories ARE the MLCommons 13-hazard taxonomy (S1..S13), so
the codes map straight onto buddle's HazardCategory — no remapping needed.

Two roles are supported (the key reason to use Llama Guard): it can classify
either a user message ("user") or an assistant/persona reply ("assistant").
That makes this adapter reusable for both the input gate and the response-side
gate.

config:
    {
      "endpoint_url": "http://llamaguard.internal/v1",  # required, OpenAI-chat shape
      "model": "llama-guard3:8b",
      "api_key": "...",                                  # optional
      "timeout_s": 15,
      "default_severity07": 6,        # severity to assign a fired category
      "category_severity07": {"S4": 7, "S9": 7}          # optional per-cat overrides
    }

On transport/parse failure raises EthicsError; the caller decides fallback.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from buddle.ai.ethics.base import CategoryResult, EthicsAssessment, EthicsError
from buddle.ai.ethics.taxonomy import HazardCategory
from buddle.core.logging import get_logger

log = get_logger(__name__)

_VALID_CODES = {c.value for c in HazardCategory}  # {"S1",...,"S13"}
_CODE_RE = re.compile(r"\bS(?:1[0-3]|[1-9])\b")  # S1..S13 word-bounded


class LlamaGuardEthicsClassifier:
    def __init__(self, config: dict[str, Any] | None = None):
        self._config = config or {}
        if not self._config.get("endpoint_url"):
            raise EthicsError("llama_guard ethics backend_config.endpoint_url is required")
        self._model = str(self._config.get("model", "llama-guard3:8b"))
        self._timeout = float(self._config.get("timeout_s", 15))
        self._default_sev = int(self._config.get("default_severity07", 6))
        self._cat_sev = {
            str(k): int(v) for k, v in self._config.get("category_severity07", {}).items()
        }

    def _severity_for(self, code: str) -> int:
        return self._cat_sev.get(code, self._default_sev)

    @staticmethod
    def parse_response(text: str) -> list[str]:
        """Parse Llama Guard output → list of violated category codes.

        Robust to whitespace/casing and to the codes being on the same or a
        second line. 'safe' (no codes) → []. Static so it is unit-testable
        without a live endpoint.
        """
        lowered = text.strip().lower()
        if lowered.startswith("safe") and "unsafe" not in lowered.split("\n")[0]:
            return []
        codes = [m.group(0).upper() for m in _CODE_RE.finditer(text.upper())]
        # de-dup, keep only valid taxonomy codes, preserve order
        seen: list[str] = []
        for c in codes:
            if c in _VALID_CODES and c not in seen:
                seen.append(c)
        return seen

    def _build_messages(self, text: str, *, role: str) -> list[dict[str, str]]:
        # Llama Guard inspects the LAST message of the given role. For response
        # screening we present the text as an assistant turn; for input
        # screening, as a user turn.
        if role == "assistant":
            return [
                {"role": "user", "content": "(이전 사용자 메시지)"},
                {"role": "assistant", "content": text},
            ]
        return [{"role": "user", "content": text}]

    async def assess(self, text: str, *, role: str = "user") -> EthicsAssessment:
        url = self._config["endpoint_url"].rstrip("/") + "/chat/completions"
        headers = {}
        if self._config.get("api_key"):
            headers["Authorization"] = f"Bearer {self._config['api_key']}"
        payload = {
            "model": self._model,
            "messages": self._build_messages(text, role=role),
            "stream": False,
            "temperature": 0.0,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            log.exception("ethics.llama_guard.request_failed")
            raise EthicsError(f"llama_guard request failed: {e}") from e

        content = _extract_content(data)
        codes = self.parse_response(content)
        if not codes:
            return EthicsAssessment.safe(
                metadata={"classifier": "llama_guard", "model": self._model, "role": role}
            )
        results = [
            CategoryResult(
                category=HazardCategory(code),
                severity07=self._severity_for(code),
                score=min(1.0, self._severity_for(code) / 7.0),
            )
            for code in codes
        ]
        return EthicsAssessment.from_categories(
            results,
            reason=f"llama_guard flagged: {', '.join(codes)}",
            metadata={"classifier": "llama_guard", "model": self._model, "role": role},
        )


def _extract_content(data: dict[str, Any]) -> str:
    """Pull assistant text from an OpenAI-chat-style response."""
    try:
        choices = data.get("choices") or []
        if choices:
            msg = choices[0].get("message") or {}
            return str(msg.get("content", ""))
        # Ollama /api/chat shape
        if "message" in data:
            return str(data["message"].get("content", ""))
    except (AttributeError, IndexError, KeyError):
        pass
    return ""
