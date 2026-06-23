"""Deterministic, dependency-free embedding provider for dev and tests.

Produces stable vectors from text via hashing, so:
  - the same text always maps to the same vector,
  - texts sharing tokens land closer together (shared hashed dimensions),
giving the mediator's cosine-similarity path something meaningful to test
against without loading a real model.

This is NOT a semantic embedding — it's a hashing-trick bag-of-tokens vector.
Good enough for wiring and tests; replace with sentence_transformers or a
remote endpoint in production.
"""

from __future__ import annotations

import hashlib
import math
import re

from buddle.ai.embeddings.base import EMBED_DIM

_TOKEN_RE = re.compile(r"[A-Za-z가-힣0-9]{2,}")


def _hash_to_index(token: str) -> int:
    digest = hashlib.sha256(token.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % EMBED_DIM


def _hash_sign(token: str) -> float:
    digest = hashlib.sha256(("sign:" + token).encode("utf-8")).digest()
    return 1.0 if (digest[0] & 1) == 0 else -1.0


def _embed_text(text: str) -> list[float]:
    vec = [0.0] * EMBED_DIM
    tokens = [t.lower() for t in _TOKEN_RE.findall(text)]
    for tok in tokens:
        idx = _hash_to_index(tok)
        vec[idx] += _hash_sign(tok)

    # L2 normalize (zero vector stays zero)
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


class StubEmbeddingProvider:
    dim = EMBED_DIM

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [_embed_text(t) for t in texts]

    async def embed_one(self, text: str) -> list[float]:
        return _embed_text(text)
