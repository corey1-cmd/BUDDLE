"""User-facing news read API — rights-filtered briefings + digest.

The pipeline stays admin-driven; these routes expose cached results to any
authenticated user. The contract under test is the content-rights filter:
ONLY title / url / source / gist_ko / tags / stored_at may leave the server —
internal pipeline fields (ekb_briefing, relevance, stub) must not.
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.asyncio

_BRIEFINGS_KEY = "buddle:news:briefings"
_DIGEST_KEY = "buddle:news:digest"

_PUBLIC_FIELDS = {"title", "url", "source", "gist_ko", "tags", "rights", "stored_at"}


async def _seed_briefings(app, items):  # type: ignore[no-untyped-def]
    """Push briefing dicts into the app's (fake) Redis, newest first."""
    redis = app.state.redis  # same instance the routes use
    for item in reversed(items):
        await redis.lpush(_BRIEFINGS_KEY, json.dumps(item, ensure_ascii=False))


def _briefing(title, *, tags, gist="한 줄 요약"):  # type: ignore[no-untyped-def]
    return {
        "url": f"https://example.com/{title}",
        "title": title,
        "source": "Example Outlet",
        "gist_ko": gist,
        "tags": tags,
        "ekb_briefing": "INTERNAL — must never reach users",
        "relevance": 0.9,
        "stub": False,
        "stored_at": 1_700_000_000,
    }


async def test_briefings_require_auth(client):  # type: ignore[no-untyped-def]
    r = await client.get("/v1/news/briefings")
    assert r.status_code == 401
    r = await client.get("/v1/news/digest")
    assert r.status_code == 401


async def test_briefings_are_rights_filtered(app, client, signup_and_login):  # type: ignore[no-untyped-def]
    info = await signup_and_login()
    h = {"Authorization": f"Bearer {info['access_token']}"}
    await _seed_briefings(app, [_briefing("AI 규제 논의", tags=["AI", "정책"])])

    r = await client.get("/v1/news/briefings", headers=h)
    assert r.status_code == 200
    items = r.json()
    assert items, "seeded briefing should be returned"
    item = next(i for i in items if i["title"] == "AI 규제 논의")
    # Exactly the public shape — internal fields stripped.
    assert set(item) == _PUBLIC_FIELDS
    assert item["url"].startswith("https://example.com/")
    assert item["gist_ko"] == "한 줄 요약"
    assert item["rights"] == "default_deny"  # 미등록 출처 = 기본 차단 등급
    assert "INTERNAL" not in json.dumps(items)


async def test_briefings_tag_filter(app, client, signup_and_login):  # type: ignore[no-untyped-def]
    info = await signup_and_login()
    h = {"Authorization": f"Bearer {info['access_token']}"}
    await _seed_briefings(
        app,
        [
            _briefing("반도체 수출 동향", tags=["반도체", "경제"]),
            _briefing("스포츠 소식", tags=["스포츠"]),
        ],
    )

    r = await client.get("/v1/news/briefings?tag=반도체", headers=h)
    assert r.status_code == 200
    titles = [i["title"] for i in r.json()]
    assert "반도체 수출 동향" in titles
    assert "스포츠 소식" not in titles

    r = await client.get("/v1/news/briefings?tag=없는태그zzz", headers=h)
    assert r.json() == []


async def test_digest_returns_our_synthesis(app, client, signup_and_login):  # type: ignore[no-untyped-def]
    info = await signup_and_login()
    h = {"Authorization": f"Bearer {info['access_token']}"}
    redis = app.state.redis
    await redis.set(
        _DIGEST_KEY,
        json.dumps({"text": "오늘의 종합 브리핑", "tags": ["AI"], "count": 3, "ts": 1}),
    )

    r = await client.get("/v1/news/digest", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body == {"text": "오늘의 종합 브리핑", "tags": ["AI"], "count": 3, "ts": 1}


async def test_digest_empty_cache_degrades(app, client, signup_and_login):  # type: ignore[no-untyped-def]
    info = await signup_and_login()
    h = {"Authorization": f"Bearer {info['access_token']}"}
    redis = app.state.redis
    await redis.delete(_DIGEST_KEY)

    r = await client.get("/v1/news/digest", headers=h)
    assert r.status_code == 200
    assert r.json() == {"text": "", "tags": [], "count": 0, "ts": 0}


def test_default_sources_include_public_rss():
    """Fresh deploys seed the expanded public-RSS set (Phase 2)."""
    from buddle.services.news_service import DEFAULT_SOURCES

    ids = {s["id"] for s in DEFAULT_SOURCES}
    assert {"guardian-world", "bbc-news", "the-verge", "ars-technica"} <= ids
    # rss sources must carry a feed url
    for s in DEFAULT_SOURCES:
        if s["kind"] == "rss":
            assert str(s["url"]).startswith("https://")


def test_government_sources_are_kogl_open():
    """정부·공공 소스는 공공누리 1유형으로 등록되어 인용 추천 대상이 된다."""
    from buddle.ai.news.rights import KOGL_TYPE1, is_open_license, rights_of
    from buddle.services.news_service import DEFAULT_SOURCES

    gov = [s for s in DEFAULT_SOURCES if s.get("rights") == KOGL_TYPE1]
    assert {"korea-kr-policy", "korea-kr-dept", "korea-kr-fact"} <= {s["id"] for s in gov}
    for s in gov:
        assert rights_of(str(s["name"])) == KOGL_TYPE1
        assert is_open_license(str(s["name"]))
    # 언론사는 default_deny 유지 (권리 엔진 기본 정책)
    assert rights_of("BBC") == "default_deny"
    assert not is_open_license("The Guardian")


async def test_briefings_expose_kogl_rights(app, client, signup_and_login):  # type: ignore[no-untyped-def]
    """정부 출처 브리핑은 rights=kogl_type1로 내려가 앱이 인용 배지를 달 수 있다."""
    info = await signup_and_login()
    h = {"Authorization": f"Bearer {info['access_token']}"}
    gov = _briefing("청년 주거 지원 대책 발표", tags=["주거", "정책"])
    gov["source"] = "대한민국 정책브리핑"
    await _seed_briefings(app, [gov])

    r = await client.get("/v1/news/briefings", headers=h)
    item = next(i for i in r.json() if i["title"] == "청년 주거 지원 대책 발표")
    assert item["rights"] == "kogl_type1"
