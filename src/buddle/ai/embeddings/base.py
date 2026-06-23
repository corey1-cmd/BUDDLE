"""Embedding provider abstraction.

The mediator uses sentence embeddings for content-similarity-based
distribution. Like persona backends, the concrete provider is pluggable so
deployments can choose:

  - stub                  : deterministic hash-based vectors (tests / dev)
  - sentence_transformers : in-process model (e.g. ko-sroberta-multitask)
  - vllm_endpoint         : remote OpenAI-compat /embeddings server

All providers emit fixed-dimension (EMBED_DIM) L2-normalized vectors so
cosine similarity reduces to a dot product and pgvector cosine ops behave
consistently.
"""

from __future__ import annotations

from typing import Protocol

# Must match the vector(N) columns in the schema (personas.context_emb,
# posts.content_emb).
EMBED_DIM = 1024


class EmbeddingError(RuntimeError):
    """Raised when an embedding backend fails. Caller decides fallback."""


class EmbeddingProvider(Protocol):
    """Async embedding interface."""

    dim: int

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one L2-normalized vector per input text."""
        ...

    async def embed_one(self, text: str) -> list[float]:
        """Convenience: embed a single text."""
        ...
