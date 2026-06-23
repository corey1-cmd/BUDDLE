"""Embedding providers + factory.

Use get_embedding_provider() to obtain the configured provider (singleton
per process). The mediator and backfill script both go through this.
"""

from __future__ import annotations

from functools import lru_cache

from buddle.ai.embeddings.base import EMBED_DIM, EmbeddingError, EmbeddingProvider
from buddle.ai.embeddings.stub import StubEmbeddingProvider
from buddle.config import get_settings
from buddle.core.logging import get_logger

log = get_logger(__name__)


@lru_cache(maxsize=1)
def get_embedding_provider() -> EmbeddingProvider:
    """Return the configured embedding provider (cached for the process)."""
    settings = get_settings()
    kind = settings.embedding_provider

    if kind == "stub":
        return StubEmbeddingProvider()

    if kind == "sentence_transformers":
        from buddle.ai.embeddings.sentence_transformers import (
            SentenceTransformersProvider,
        )

        return SentenceTransformersProvider(
            {
                "model_id": settings.embedding_model_id,
                "device": settings.embedding_device,
            }
        )

    if kind == "vllm_endpoint":
        from buddle.ai.embeddings.vllm_endpoint import VllmEmbeddingProvider

        return VllmEmbeddingProvider(
            {
                "endpoint_url": settings.embedding_endpoint_url,
                "model": settings.embedding_model_id,
            }
        )

    raise EmbeddingError(f"Unknown embedding_provider: {kind!r}")


__all__ = [
    "EMBED_DIM",
    "EmbeddingError",
    "EmbeddingProvider",
    "StubEmbeddingProvider",
    "get_embedding_provider",
]
