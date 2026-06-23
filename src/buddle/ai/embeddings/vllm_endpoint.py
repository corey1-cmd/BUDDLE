"""Remote embedding provider (OpenAI-compatible /embeddings endpoint).

Works with vLLM's embeddings server, TEI, or any OpenAI-compatible service.

config:
    {
      "endpoint_url": "https://embed.internal/v1",   # required
      "model": "intfloat/multilingual-e5-base",      # required
      "api_key": "...",                              # optional
      "timeout_s": 30
    }

Responses must be EMBED_DIM-dimensional. We L2-normalize defensively in case
the server doesn't.
"""

from __future__ import annotations

import math
from typing import Any

import httpx

from buddle.ai.embeddings.base import EMBED_DIM, EmbeddingError
from buddle.core.logging import get_logger

log = get_logger(__name__)


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec] if norm > 0 else vec


class VllmEmbeddingProvider:
    dim = EMBED_DIM

    def __init__(self, config: dict[str, Any] | None = None):
        self._config = config or {}
        if not self._config.get("endpoint_url"):
            raise EmbeddingError("embedding backend_config.endpoint_url is required")
        if not self._config.get("model"):
            raise EmbeddingError("embedding backend_config.model is required")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        endpoint = str(self._config["endpoint_url"]).rstrip("/")
        url = f"{endpoint}/embeddings"
        headers = {"Content-Type": "application/json"}
        api_key = self._config.get("api_key")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        timeout_s = float(self._config.get("timeout_s", 30))

        payload = {"model": self._config["model"], "input": texts}

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
                items = sorted(data["data"], key=lambda d: d["index"])
                vecs = [item["embedding"] for item in items]
                if any(len(v) != EMBED_DIM for v in vecs):
                    raise EmbeddingError(f"Embedding dim mismatch; expected {EMBED_DIM}")
                return [_l2_normalize(v) for v in vecs]
            except (httpx.HTTPError, KeyError, ValueError) as e:
                last_exc = e
                log.warning("embedding.vllm.attempt_failed", attempt=attempt, error=str(e))

        raise EmbeddingError(f"vllm embedding failed after retries: {last_exc}") from last_exc

    async def embed_one(self, text: str) -> list[float]:
        out = await self.embed([text])
        return out[0]
