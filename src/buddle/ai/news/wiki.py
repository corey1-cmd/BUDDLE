"""Wikipedia 배경지식 보강 — 화제 entities에 한국어 위키백과 요약을 붙인다.

설계(docs/design/CONTENT_TRUST_UPGRADE.md §기능3): REST Summary API 단일 채택.
호출 시점은 수집 틱 내부(refine 직후, 신규 엔티티 발견 시점)뿐이다 — 사용자
조회 경로는 절대 원격 호출을 하지 않고 화제 캐시에 실린 결과만 읽는다.

저장은 Redis 단독: `buddle:know:wiki:{정규화명}` TTL 7일 + 부재 네거티브 캐시
1일(존재하지 않는 문서를 틱마다 다시 두드리지 않는다). DB 테이블은 두지 않는다
— 원본이 Wikipedia라 재조회로 완전 복원되고, 캐시 유실은 다음 틱이 자가 치유.

Wikimedia 정책 준수: User-Agent 명시, 틱당 신규 조회 상한(기본 12), 순차 호출,
429/5xx 시 즉시 중단(다음 틱 재시도). 동음이의(type=disambiguation) 응답은
버린다 — 엉뚱한 인물 요약을 붙이는 것보다 없는 편이 낫다(오정보 방지).
노출 시 출처(위키백과 링크)와 CC BY-SA 4.0 표기를 생략하지 않는다.
"""

from __future__ import annotations

import contextlib
import json

import httpx

from buddle.core.logging import get_logger

log = get_logger(__name__)

_SUMMARY_API = "https://ko.wikipedia.org/api/rest_v1/page/summary/{title}"
_UA = "buddle/0.1 (https://buddle-a8h0.onrender.com; news-topic-enrichment)"
_TIMEOUT = 8.0

_CACHE_PREFIX = "buddle:know:wiki:"
_TTL = 7 * 24 * 3600  # 문서 요약은 천천히 변한다 — 7일이면 충분히 신선
_NEG_TTL = 24 * 3600  # 부재(404·동음이의)는 1일 뒤 재확인
_NEG_SENTINEL = '{"miss": true}'

_MAX_SUMMARY = 200  # 카드에 붙는 배경지식은 1~2문장이면 족하다


def _norm(name: str) -> str:
    return " ".join((name or "").split()).casefold()


def _cache_key(name: str) -> str:
    return _CACHE_PREFIX + _norm(name)


def parse_summary(data: object) -> dict[str, str] | None:
    """Summary API 응답 → 배경지식 dict. 쓸 수 없는 응답은 None.

    사용 필드(extract/title/content_urls/thumbnail)만 소비해 Wikipedia 측
    스키마 변화에 내성을 갖는다. 동음이의 문서는 기각한다.
    """
    if not isinstance(data, dict):
        return None
    if str(data.get("type") or "") == "disambiguation":
        return None  # 어느 항목인지 확정 불가 — 오정보 방지 우선
    extract = " ".join(str(data.get("extract") or "").split())
    if not extract:
        return None
    urls = data.get("content_urls")
    page_url = ""
    if isinstance(urls, dict):
        desktop = urls.get("desktop")
        if isinstance(desktop, dict):
            page_url = str(desktop.get("page") or "")
    thumb = data.get("thumbnail")
    thumb_url = str(thumb.get("source") or "") if isinstance(thumb, dict) else ""
    return {
        "name": str(data.get("title") or ""),
        "summary": extract[:_MAX_SUMMARY],
        "url": page_url,
        "thumbnail": thumb_url,
    }


async def _fetch_summary(name: str) -> dict[str, str] | None:
    """원격 1건 조회 — 404(없음/삭제/병합 미해결)는 None, 나머지 오류는 예외."""
    async with httpx.AsyncClient(
        timeout=_TIMEOUT, follow_redirects=True, headers={"User-Agent": _UA}
    ) as client:
        resp = await client.get(_SUMMARY_API.format(title=name.strip().replace(" ", "_")))
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return parse_summary(resp.json())


async def entity_brief(redis: object, name: str) -> dict[str, str] | None:
    """캐시 우선 엔티티 배경지식. 원격 실패는 None(fail-open) — 예외 전파 없음."""
    if not name or not name.strip():
        return None
    key = _cache_key(name)
    with contextlib.suppress(Exception):
        raw = await redis.get(key)  # type: ignore[attr-defined]
        if raw:
            data = json.loads(raw)
            return None if data.get("miss") else data
    try:
        brief = await _fetch_summary(name)
    except Exception as e:
        log.warning("news.wiki.fetch_error", entity=name, error=str(e))
        raise  # 상한 관리 주체(enrich_topics)가 중단 판단을 하도록 올린다
    with contextlib.suppress(Exception):
        if brief:
            await redis.setex(key, _TTL, json.dumps(brief, ensure_ascii=False))  # type: ignore[attr-defined]
        else:
            await redis.setex(key, _NEG_TTL, _NEG_SENTINEL)  # type: ignore[attr-defined]
    return brief


async def enrich_topics(redis: object, topics: list[object], *, max_fetch: int = 12) -> int:
    """화제들의 entities에 배경지식을 붙인다(topic.entity_briefs).

    캐시 히트는 무제한, 원격 신규 조회는 틱당 max_fetch 건으로 제한한다.
    원격 오류가 나면 그 틱의 신규 조회를 즉시 멈춘다(레이트리밋 존중) —
    이미 붙인 것은 유지되고 다음 틱이 이어서 채운다.
    """
    fetched = 0
    attached = 0
    remote_ok = True
    for t in topics:
        names = [n for n in getattr(t, "entities", []) if isinstance(n, str) and n.strip()]
        briefs: list[dict[str, str]] = []
        for name in names[:3]:  # 화제당 상위 3개면 배경 맥락으로 충분
            key = _cache_key(name)
            cached = None
            with contextlib.suppress(Exception):
                raw = await redis.get(key)  # type: ignore[attr-defined]
                cached = json.loads(raw) if raw else None
            if cached is not None:
                if not cached.get("miss"):
                    briefs.append(cached)
                continue
            if not remote_ok or fetched >= max_fetch:
                continue
            fetched += 1
            try:
                brief = await entity_brief(redis, name)
            except Exception:
                remote_ok = False  # 이 틱은 여기까지 — 다음 틱이 이어받는다
                continue
            if brief:
                briefs.append(brief)
        if briefs:
            t.entity_briefs = briefs  # type: ignore[attr-defined]
            attached += 1
    if attached or fetched:
        log.info("news.wiki.enriched", topics=attached, remote_calls=fetched)
    return attached
