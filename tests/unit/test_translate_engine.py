"""번역 엔진 디스패치·캐시·폴백 — ai/news/translate.py 의 계약 검증.

계약: (1) 캐시 히트는 엔진 호출 0회 (2) marian 성공 시 결과가 캐시에 저장
(3) marian 사용 불가(None) 시 llm 폴백 (4) 실패는 원문 유지(fail-open).
"""

from __future__ import annotations

import json

import pytest

from buddle.ai.news import translate as tr
from buddle.ai.news.fetcher import RawArticle

pytestmark = pytest.mark.asyncio


class FakeRedis:
    """get/setex만 있는 최소 스텁 — translate가 쓰는 표면 전부."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key):  # type: ignore[no-untyped-def]
        return self.store.get(key)

    async def setex(self, key, ttl, value):  # type: ignore[no-untyped-def]
        self.store[key] = value


class _Settings:
    news_translate_marian_model = ""

    def __init__(self, engine: str = "llm") -> None:
        self.news_translate_engine = engine


def _art(title: str, summary: str = "") -> RawArticle:
    return RawArticle(url="https://x/" + title[:8], title=title, source="bbc", summary=summary)


def test_cache_key_stable_and_content_sensitive():
    a = _art("Spain wildfire contained")
    assert tr.cache_key(a) == tr.cache_key(_art("Spain wildfire contained"))
    # 요약이 다르면 다른 원문 — 다른 키
    assert tr.cache_key(a) != tr.cache_key(_art("Spain wildfire contained", "new detail"))


async def test_cache_hit_skips_engines(monkeypatch):
    a = _art("Spain battles wildfire")
    r = FakeRedis()
    r.store[tr.cache_key(a)] = json.dumps({"t": "스페인 산불 진화 총력", "s": "요약문"})
    calls = {"n": 0}

    async def boom(*_args, **_kw):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        return None

    monkeypatch.setattr(tr, "_call_ai", boom)
    out = await tr.translate_articles([a], settings=_Settings("llm"), redis=r)
    assert out[0].translated and out[0].title == "스페인 산불 진화 총력"
    assert calls["n"] == 0  # 캐시가 있으면 어떤 엔진도 부르지 않는다


async def test_marian_engine_translates_and_caches(monkeypatch):
    from buddle.ai.news import marian

    async def fake_batch(texts, *, model_name=None):  # type: ignore[no-untyped-def]
        return ["한국어 번역: " + t for t in texts]

    monkeypatch.setattr(marian, "translate_batch", fake_batch)
    a = _art("Wildfire contained", "Firefighters succeed")
    r = FakeRedis()
    out = await tr.translate_articles([a], settings=_Settings("marian"), redis=r)
    assert out[0].translated and out[0].title.startswith("한국어 번역:")
    assert out[0].summary.startswith("한국어 번역:")
    assert tr.cache_key(a) in r.store  # 성공분은 캐시에 저장된다


async def test_marian_unavailable_keeps_original_without_calling_api(monkeypatch):
    """오프라인 계약: marian 실패 시 클라우드 번역 API로 폴백하지 않는다.

    번역 단계에서 외부 API를 절대 부르지 않아야 하므로, 엔진이 marian이면
    로드 실패 시 원문(영문)을 그대로 유지하고 _call_ai는 한 번도 불리지 않는다.
    """
    from buddle.ai.news import marian

    async def none_batch(_texts, *, model_name=None):  # type: ignore[no-untyped-def]
        return None  # 미설치/로드 실패 신호

    api_calls = {"n": 0}

    async def spy_ai(*_a, **_kw):  # type: ignore[no-untyped-def]
        api_calls["n"] += 1
        return json.dumps({"items": [{"i": 0, "title_ko": "부르면 안 됨", "summary_ko": "x"}]})

    monkeypatch.setattr(marian, "translate_batch", none_batch)
    monkeypatch.setattr(tr, "_call_ai", spy_ai)
    a = _art("Original stays intact")
    out = await tr.translate_articles([a], settings=_Settings("marian"))
    assert not out[0].translated and out[0].title == a.title  # 원문 유지(fail-open)
    assert api_calls["n"] == 0  # 번역 단계에서 API 미호출


async def test_llm_engine_is_explicit_opt_in(monkeypatch):
    """레거시 opt-in: 엔진을 명시적으로 'llm'으로 골랐을 때만 API를 쓴다."""
    from buddle.ai.news import marian

    async def boom_batch(_texts, *, model_name=None):  # type: ignore[no-untyped-def]
        raise AssertionError("marian이 llm 경로에서 호출되면 안 된다")

    async def fake_ai(_messages, *, settings, json_mode, max_tokens):  # type: ignore[no-untyped-def]
        return json.dumps({"items": [{"i": 0, "title_ko": "명시적 LLM 번역", "summary_ko": "요약"}]})

    monkeypatch.setattr(marian, "translate_batch", boom_batch)
    monkeypatch.setattr(tr, "_call_ai", fake_ai)
    out = await tr.translate_articles([_art("Opt-in path check")], settings=_Settings("llm"))
    assert out[0].translated and out[0].title == "명시적 LLM 번역"


def test_marian_postprocess_normalises_quotes_and_spaces():
    from buddle.ai.news.marian import _postprocess

    assert _postprocess("  “스마트  따옴표”  ") == '"스마트 따옴표"'
