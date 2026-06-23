"""In-process sentence-transformers embedding provider.

Loads a model once (module-level cache) and runs encoding in a worker thread
so the event loop isn't blocked. Defaults to a multilingual model good for
Korean+English; override via config.

config:
    {
      "model_id": "jhgan/ko-sroberta-multitask",   # or intfloat/multilingual-e5-base
      "device": "cpu",                              # cpu|cuda
      "batch_size": 32
    }

sentence_transformers + torch are imported lazily so environments using only
the stub provider don't pay the import cost.
"""

from __future__ import annotations

import asyncio
from typing import Any

from buddle.ai.embeddings.base import EMBED_DIM, EmbeddingError
from buddle.core.logging import get_logger

log = get_logger(__name__)

_model_cache: dict[str, Any] = {}
_load_lock = asyncio.Lock()


async def _ensure_model(config: dict[str, Any]) -> Any:
    model_id = config.get("model_id", "jhgan/ko-sroberta-multitask")
    if model_id in _model_cache:
        return _model_cache[model_id]

    async with _load_lock:
        if model_id in _model_cache:
            return _model_cache[model_id]
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise EmbeddingError(
                "sentence_transformers backend requires the 'sentence-transformers' "
                "package. Install it, or use the 'stub'/'vllm_endpoint' provider."
            ) from e

        device = config.get("device", "cpu")
        log.info("embedding.st.loading", model_id=model_id, device=device)
        model = SentenceTransformer(model_id, device=device)

        # Validate the dimension matches our schema's vector(EMBED_DIM)
        dim = int(model.get_sentence_embedding_dimension())
        if dim != EMBED_DIM:
            raise EmbeddingError(
                f"Model '{model_id}' emits dim={dim}, but schema expects {EMBED_DIM}. "
                "Pick a matching model or migrate the vector columns."
            )

        _model_cache[model_id] = model
        return model


def _encode_sync(model: Any, texts: list[str], batch_size: int) -> list[list[float]]:
    vecs = model.encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=True,  # L2-normalized
        convert_to_numpy=True,
    )
    return [v.tolist() for v in vecs]


class SentenceTransformersProvider:
    dim = EMBED_DIM

    def __init__(self, config: dict[str, Any] | None = None):
        self._config = config or {}

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = await _ensure_model(self._config)
        batch_size = int(self._config.get("batch_size", 32))
        try:
            return await asyncio.to_thread(_encode_sync, model, texts, batch_size)
        except Exception as e:
            log.exception("embedding.st.encode_failed")
            raise EmbeddingError(f"sentence_transformers encode failed: {e}") from e

    async def embed_one(self, text: str) -> list[float]:
        out = await self.embed([text])
        return out[0]
