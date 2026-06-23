"""Embedding provider tests (stub provider, the test/dev default)."""

from __future__ import annotations

import math

import pytest

from buddle.ai.embeddings import EMBED_DIM, StubEmbeddingProvider

pytestmark = pytest.mark.asyncio


async def test_stub_embedding_dim_and_normalization():
    p = StubEmbeddingProvider()
    v = await p.embed_one("여행 좋아하는 사람")
    assert len(v) == EMBED_DIM
    norm = math.sqrt(sum(x * x for x in v))
    assert abs(norm - 1.0) < 1e-6


async def test_stub_embedding_deterministic():
    p = StubEmbeddingProvider()
    a = await p.embed_one("같은 텍스트입니다")
    b = await p.embed_one("같은 텍스트입니다")
    assert a == b


async def test_stub_embedding_token_overlap_increases_similarity():
    p = StubEmbeddingProvider()
    a = await p.embed_one("여행 여행 여행 코스")
    b = await p.embed_one("여행 코스 추천 정보")
    c = await p.embed_one("주식 투자 금융 시장")
    sim_ab = sum(x * y for x, y in zip(a, b, strict=True))
    sim_ac = sum(x * y for x, y in zip(a, c, strict=True))
    assert sim_ab > sim_ac


async def test_stub_embedding_batch():
    p = StubEmbeddingProvider()
    out = await p.embed(["하나", "둘", "셋"])
    assert len(out) == 3
    assert all(len(v) == EMBED_DIM for v in out)


async def test_stub_embedding_empty_text_is_zero_vector():
    p = StubEmbeddingProvider()
    v = await p.embed_one("")
    assert v == [0.0] * EMBED_DIM
