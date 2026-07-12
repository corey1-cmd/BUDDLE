"""Wikipedia 배경지식 보강 — 파싱·동음이의 기각·네거티브 캐시·조회 상한 계약."""

from __future__ import annotations

import json

import pytest

from buddle.ai.news import wiki
from buddle.ai.news.topics import Topic

pytestmark = pytest.mark.asyncio


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key):  # type: ignore[no-untyped-def]
        return self.store.get(key)

    async def setex(self, key, ttl, value):  # type: ignore[no-untyped-def]
        self.store[key] = value


def _topic(entities: list[str]) -> Topic:
    t = Topic(
        name="테스트 화제",
        score=0.5,
        count=2,
        sources=["a"],
        category="기술",
        scope="전국",
        region="",
        keywords=["테스트 화제"],
    )
    t.entities = entities
    return t


def test_parse_summary_accepts_normal_page():
    brief = wiki.parse_summary(
        {
            "type": "standard",
            "title": "삼성전자",
            "extract": "삼성전자는 대한민국의 전자 기업이다.\n본사는 수원에 있다.",
            "content_urls": {"desktop": {"page": "https://ko.wikipedia.org/wiki/삼성전자"}},
            "thumbnail": {"source": "https://upload.wikimedia.org/x.png"},
        }
    )
    assert brief is not None
    assert brief["name"] == "삼성전자"
    assert brief["summary"].startswith("삼성전자는")
    assert "\n" not in brief["summary"]  # 공백 정규화
    assert brief["url"].endswith("삼성전자")


def test_parse_summary_rejects_disambiguation_and_empty():
    # 동음이의는 어느 항목인지 확정 불가 — 오정보 방지를 위해 기각
    assert wiki.parse_summary({"type": "disambiguation", "extract": "여러 뜻"}) is None
    assert wiki.parse_summary({"type": "standard", "extract": ""}) is None
    assert wiki.parse_summary("not-a-dict") is None


async def test_entity_brief_uses_cache_before_remote(monkeypatch):
    r = FakeRedis()
    r.store[wiki._cache_key("삼성전자")] = json.dumps(
        {"name": "삼성전자", "summary": "캐시된 요약", "url": "", "thumbnail": ""}
    )
    calls = {"n": 0}

    async def boom(_name):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        return None

    monkeypatch.setattr(wiki, "_fetch_summary", boom)
    brief = await wiki.entity_brief(r, "삼성전자")
    assert brief and brief["summary"] == "캐시된 요약"
    assert calls["n"] == 0


async def test_entity_brief_negative_cache_stops_refetch(monkeypatch):
    r = FakeRedis()
    calls = {"n": 0}

    async def missing(_name):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        return None  # 404 — 없는 문서

    monkeypatch.setattr(wiki, "_fetch_summary", missing)
    assert await wiki.entity_brief(r, "없는문서XYZ") is None
    assert await wiki.entity_brief(r, "없는문서XYZ") is None  # 두 번째는 네거티브 캐시
    assert calls["n"] == 1


async def test_enrich_topics_respects_fetch_budget(monkeypatch):
    r = FakeRedis()
    calls = {"n": 0}

    async def counted(_name):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        return {"name": "X", "summary": "요약", "url": "", "thumbnail": ""}

    monkeypatch.setattr(wiki, "_fetch_summary", counted)
    topics = [_topic([f"엔티티{i}a", f"엔티티{i}b"]) for i in range(4)]  # 신규 8건
    attached = await wiki.enrich_topics(r, topics, max_fetch=3)
    assert calls["n"] == 3  # 상한 준수
    assert attached >= 1
    assert any(getattr(t, "entity_briefs", []) for t in topics)


async def test_enrich_topics_stops_on_remote_error(monkeypatch):
    r = FakeRedis()
    calls = {"n": 0}

    async def flaky(_name):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        raise RuntimeError("429")

    monkeypatch.setattr(wiki, "_fetch_summary", flaky)
    topics = [_topic(["가나다"]), _topic(["라마바"]), _topic(["사아자"])]
    await wiki.enrich_topics(r, topics, max_fetch=10)
    assert calls["n"] == 1  # 첫 오류에서 이 틱의 원격 조회 중단(레이트리밋 존중)
