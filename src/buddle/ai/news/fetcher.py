"""Open-web tech news fetcher.

Sources (all free, no auth, robots.txt-compliant):
  - Hacker News Firebase REST API (official, open)
  - Techmeme RSS  (public feed, standard aggregator RSS)
  - Dev.to API    (open JSON API)

Each source returns a list of RawArticle dataclasses. The caller deduplicates
by URL hash before passing to the mediator AI for analysis.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import html
import re
import time
from dataclasses import dataclass, field

import httpx

from buddle.core.logging import get_logger

log = get_logger(__name__)

_TIMEOUT = 15.0  # seconds per request
_HN_TOP_STORIES = "https://hacker-news.firebaseio.com/v1/topstories.json"
_HN_ITEM = "https://hacker-news.firebaseio.com/v1/item/{}.json"
_DEVTO_ARTICLES = "https://dev.to/api/articles?top=7&per_page=15"
_TECHMEME_RSS = "https://www.techmeme.com/feed.xml"


@dataclass(frozen=True, slots=True)
class RawArticle:
    url: str
    title: str
    source: str
    score: int = 0
    comments: int = 0
    published_at: int = field(default_factory=lambda: int(time.time()))
    summary: str = ""  # RSS <description>/<summary>, tag-stripped (화제 추출 입력)
    # 해외 기사를 한국어로 번역해 공개할 때 True — 번역 후 텍스트가 한국어라도
    # 범위 분류는 해외로 남아야 하므로(전국 오분류 방지) 원산지 표식을 남긴다.
    translated: bool = False
    # 문서 단위 권리 등급(ai/news/rights.py) — 공공누리 유형별 가공 허용 범위를
    # 파이프라인 하류(번역·요약)가 강제할 수 있도록 수집 시점에 못 박는다.
    rights: str = "default_deny"

    @property
    def url_hash(self) -> str:
        return hashlib.sha256(self.url.encode()).hexdigest()[:16]


def _parse_pubdate(raw_block: str) -> int:
    """Best-effort RFC-822/ISO date from an RSS/Atom item block → unix seconds.

    Recency drives topic scoring, so a real timestamp beats fetch time when the
    feed provides one; on any parse failure we fall back to now.
    """
    m = re.search(
        r"<(?:pubDate|published|updated|dc:date)[^>]*>(.*?)</(?:pubDate|published|updated|dc:date)>",
        raw_block,
        re.DOTALL,
    )
    if not m:
        return int(time.time())
    text = m.group(1).strip()
    try:
        from email.utils import parsedate_to_datetime

        return int(parsedate_to_datetime(text).timestamp())
    except (TypeError, ValueError):
        pass
    try:
        from datetime import datetime

        return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return int(time.time())


async def fetch_hacker_news(*, limit: int = 20) -> list[RawArticle]:
    """Fetch top stories from Hacker News Firebase API.

    The per-item lookups are issued concurrently (one round trip each) instead
    of serially, so fetching N stories takes ~one request latency, not N.
    """
    articles: list[RawArticle] = []
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            r = await client.get(_HN_TOP_STORIES)
            r.raise_for_status()
            ids: list[int] = r.json()[:limit]

            async def _fetch_item(item_id: int) -> RawArticle | None:
                try:
                    ir = await client.get(_HN_ITEM.format(item_id))
                    ir.raise_for_status()
                    item = ir.json()
                    if not item or item.get("type") != "story":
                        return None
                    url = item.get("url") or f"https://news.ycombinator.com/item?id={item_id}"
                    title = (item.get("title") or "").strip()
                    if not title:
                        return None
                    return RawArticle(
                        url=url,
                        title=title,
                        source="hackernews",
                        score=item.get("score", 0),
                        comments=item.get("descendants", 0),
                        published_at=item.get("time", int(time.time())),
                    )
                except Exception as e:
                    log.debug("hn.item_fetch_error", item_id=item_id, error=str(e))
                    return None

            results = await asyncio.gather(*(_fetch_item(i) for i in ids))
            articles = [a for a in results if isinstance(a, RawArticle)]
    except Exception as e:
        log.warning("hn.fetch_error", error=str(e))
    return articles


async def fetch_devto(*, limit: int = 10) -> list[RawArticle]:
    """Fetch trending articles from dev.to public API."""
    articles: list[RawArticle] = []
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            r = await client.get(_DEVTO_ARTICLES, headers={"User-Agent": "buddle-news-bot/1.0"})
            r.raise_for_status()
            for item in r.json()[:limit]:
                url = item.get("url") or item.get("canonical_url", "")
                title = item.get("title", "").strip()
                if not url or not title:
                    continue
                articles.append(
                    RawArticle(
                        url=url,
                        title=title,
                        source="devto",
                        score=item.get("public_reactions_count", 0),
                        comments=item.get("comments_count", 0),
                    )
                )
    except Exception as e:
        log.warning("devto.fetch_error", error=str(e))
    return articles


async def fetch_rss(url: str, *, source_name: str, limit: int = 10) -> list[RawArticle]:
    """Generic RSS/Atom fetcher using simple XML parsing (no third-party lib)."""
    articles: list[RawArticle] = []
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "buddle-news-bot/1.0 (+https://buddle.app)"},
        ) as client:
            r = await client.get(url)
            r.raise_for_status()
            text = r.text
            # Extract <item> or <entry> blocks
            items = re.findall(r"<(?:item|entry)[^>]*>(.*?)</(?:item|entry)>", text, re.DOTALL)
            for raw in items[:limit]:
                title_m = re.search(
                    r"<title[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", raw, re.DOTALL
                )
                link_m = re.search(
                    r"<link[^>]*>(?:<!\[CDATA\[)?(https?://[^\s<]+?)(?:\]\]>)?</link>",
                    raw,
                    re.DOTALL,
                )
                if not link_m:
                    link_m = re.search(r'<link[^>]+href="(https?://[^"]+)"', raw)
                if not title_m or not link_m:
                    continue
                # 태그 제거 후 엔티티 해제 — RSS 제목의 &apos;/&amp; 류가 그대로
                # 사용자 화면까지 노출되는 것을 여기서 끊는다 (라이브 실측 버그).
                title = strip_trailing_attribution(
                    html.unescape(re.sub(r"<[^>]+>", "", title_m.group(1))).strip()
                )
                link = link_m.group(1).strip()
                if not title or not link:
                    continue
                # RSS 구조의 요약(<description>/<summary>) — 화제 추출·발췌 요약 입력.
                desc_m = re.search(
                    r"<(?:description|summary|content)[^>]*>(?:<!\[CDATA\[)?(.*?)"
                    r"(?:\]\]>)?</(?:description|summary|content)>",
                    raw,
                    re.DOTALL,
                )
                summary = (
                    html.unescape(re.sub(r"<[^>]+>", " ", desc_m.group(1))).strip()
                    if desc_m
                    else ""
                )
                articles.append(
                    RawArticle(
                        url=link,
                        title=title,
                        source=source_name,
                        summary=summary[:2000],
                        published_at=_parse_pubdate(raw),
                    )
                )
    except Exception as e:
        log.warning("rss.fetch_error", source=source_name, url=url, error=str(e))
    return articles


# Techmeme류 애그리게이터 제목 말미의 출처 표기 "(Bloomberg)", "(Ina Fried/
# Axios)" — 토큰이 되면 매체명이 가짜 화제가 된다(라이브 실측: #bloomberg,
# #verge). 꼬리의 짧은 괄호 표기를 반복 제거한다(한글 없는 ≤6단어 괄호만 —
# 본문 중간의 의미 있는 괄호는 건드리지 않는다).
_TRAILING_ATTR_RE = re.compile(r"\s*\(([^()]{1,60})\)\s*$")


def strip_trailing_attribution(title: str) -> str:
    t = (title or "").strip()
    for _ in range(3):  # "(Bloomberg) (techmeme)" 같은 다중 꼬리
        m = _TRAILING_ATTR_RE.search(t)
        if not m:
            break
        inner = m.group(1)
        if re.search(r"[가-힣]", inner) or len(inner.split()) > 6:
            break
        t = t[: m.start()].rstrip()
    return t or (title or "").strip()


_SIMHASH_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]{2,}")


def simhash64(text: str) -> int:
    """64-bit SimHash over tokens — 통신사 전재(같은 기사, 다른 URL) 탐지용.

    URL/guid dedup은 '같은 주소'만 거른다. 한국 뉴스 생태계에선 같은 통신사
    기사가 여러 매체 URL로 유입되므로, 제목+요약의 내용 지문이 필요하다.
    해밍거리 ≤ 3이면 준중복으로 판정한다(설계서 §M1-4).
    """
    tokens = _SIMHASH_TOKEN_RE.findall((text or "").lower())
    if not tokens:
        return 0
    v = [0] * 64
    for tok in tokens:
        # blake2b: 비암호 지문 용도 — md5는 보안 린트(S324)에 걸리고,
        # blake2b(digest_size=8)가 같은 일을 더 빠르고 깨끗하게 한다.
        h = int.from_bytes(hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest(), "big")
        for i in range(64):
            v[i] += 1 if (h >> i) & 1 else -1
    out = 0
    for i in range(64):
        if v[i] > 0:
            out |= 1 << i
    return out


def hamming64(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def _dedup(articles: list[RawArticle]) -> list[RawArticle]:
    """Keep the first occurrence per URL."""
    seen: set[str] = set()
    unique: list[RawArticle] = []
    for a in articles:
        if a.url not in seen:
            seen.add(a.url)
            unique.append(a)
    return unique


# data.go.kr 표준 응답에서 기사 목록을 찾는 휴리스틱 — 기관마다 오퍼레이션명이
# 다르지만(과거 api.korea.go.kr→odcloud 개편 사례) 응답 골격(response.body.items)
# 과 필드 관습(제목/링크/일자)은 안정적이다. 매핑을 하드코딩하지 않고 흔한
# 필드명 후보를 순서대로 시도한다 — 새 기관은 소스 등록만으로 붙는다.
_GOVAPI_TITLE_KEYS = ("title", "nttSj", "subject", "bbsSj", "sj", "titl")
_GOVAPI_URL_KEYS = ("url", "link", "orgLink", "nttUrl", "detailUrl", "viewUrl")
_GOVAPI_DATE_KEYS = ("regDate", "pubDate", "createDt", "registDt", "date", "regDt")
_GOVAPI_BODY_KEYS = ("summary", "content", "nttCn", "cn", "description")


def _govapi_items(data: object) -> list[dict[str, object]]:
    """응답 JSON 어디에 있든 항목 리스트를 찾아낸다(response.body.items[.item])."""
    node = data
    for key in ("response", "body", "items", "item", "data"):
        if isinstance(node, list):
            break
        if isinstance(node, dict) and key in node:
            node = node[key]
    if isinstance(node, dict):  # items가 {"item": [...]} 꼴인 변형
        for v in node.values():
            if isinstance(v, list):
                node = v
                break
    return [x for x in node if isinstance(x, dict)] if isinstance(node, list) else []


def _first_str(item: dict[str, object], keys: tuple[str, ...]) -> str:
    for k in keys:
        v = item.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


async def fetch_govapi(
    url: str, *, source_name: str, service_key: str, limit: int = 10
) -> list[RawArticle]:
    """공공데이터포털(data.go.kr) OpenAPI 수집 — 정형 JSON, 가장 안정적인 채널.

    serviceKey는 설정(DATA_GO_KR_SERVICE_KEY)에서만 주입한다 — 소스 레지스트리
    (Redis/admin 화면)에 비밀값을 싣지 않는다. 키 미설정 시 [] 반환(로그만) —
    수집 스윕은 계속된다.
    """
    if not service_key:
        log.info("news.govapi.no_key", source=source_name)
        return []
    params = {"serviceKey": service_key, "numOfRows": str(limit), "pageNo": "1", "type": "json"}
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
    out: list[RawArticle] = []
    for item in _govapi_items(data)[:limit]:
        title = strip_trailing_attribution(html.unescape(_first_str(item, _GOVAPI_TITLE_KEYS)))
        link = _first_str(item, _GOVAPI_URL_KEYS)
        if not title or not link:
            continue
        out.append(
            RawArticle(
                url=link,
                title=title,
                source=source_name,
                summary=html.unescape(_first_str(item, _GOVAPI_BODY_KEYS))[:500],
                published_at=_parse_pubdate(_first_str(item, _GOVAPI_DATE_KEYS)),
            )
        )
    return out


async def fetch_source(source: dict[str, object], *, govapi_key: str = "") -> list[RawArticle]:
    """Fetch one configured source. Dispatches by `kind`:
      - 'hackernews' / 'devto': fixed open APIs (url ignored)
      - 'rss': arbitrary feed `url` (SSRF-validated before the request)
      - 'govapi': 공공데이터포털 OpenAPI (serviceKey는 설정에서만 주입)

    Disabled sources return []. Unknown kinds and unsafe URLs are skipped
    (logged), never raised — one bad source can't break the whole sweep.
    수집된 기사에는 소스의 권리 등급(rights)을 못 박아 하류(번역·요약)가
    공공누리 허용 범위를 강제할 수 있게 한다.
    """
    if not source.get("enabled", True):
        return []
    kind = str(source.get("kind", "")).lower()
    limit_raw = source.get("limit", 10)
    limit = limit_raw if isinstance(limit_raw, int) else 10
    name = str(source.get("id") or source.get("name") or kind)

    def _stamp(arts: list[RawArticle]) -> list[RawArticle]:
        tier = str(source.get("rights") or "") or None
        if not tier:
            from buddle.ai.news.rights import rights_of

            tier = rights_of(str(source.get("name") or name))
        return [dataclasses.replace(a, rights=tier) for a in arts]

    try:
        if kind == "hackernews":
            return _stamp(await fetch_hacker_news(limit=limit))
        if kind == "devto":
            return _stamp(await fetch_devto(limit=limit))
        if kind in ("rss", "govapi"):
            url = str(source.get("url", "")).strip()
            if not url:
                return []
            # Defense-in-depth: re-validate the feed URL at fetch time (config
            # could have been seeded/edited out of band).
            from buddle.core.ssrf import SSRFValidationError, validate_outbound_url

            try:
                validate_outbound_url(url)
            except SSRFValidationError as e:
                log.warning("news.source.unsafe_url", source=name, url=url, error=str(e))
                return []
            if kind == "govapi":
                return _stamp(
                    await fetch_govapi(url, source_name=name, service_key=govapi_key, limit=limit)
                )
            return _stamp(await fetch_rss(url, source_name=name, limit=limit))
        log.warning("news.source.unknown_kind", source=name, kind=kind)
        return []
    except httpx.HTTPStatusError as e:
        # 403/429 = 차단·레이트리밋 신호 — 우회·재시도 없이 스킵하고 다음 틱을
        # 기다린다(컴퓨터등장애업무방해 리스크 원천 차단, docx §컴플라이언스).
        log.warning("news.source.blocked", source=name, kind=kind, status=e.response.status_code)
        return []
    except Exception as e:  # one source failing must not abort the sweep
        log.warning("news.source.fetch_error", source=name, kind=kind, error=str(e))
        return []


async def fetch_configured(
    sources: list[dict[str, object]], *, govapi_key: str = ""
) -> list[RawArticle]:
    """Fetch every enabled configured source concurrently. Dedup by URL.

    동시성은 소스 단위(호스트가 전부 다름) — 같은 호스트를 두들기는 팬아웃이
    아니므로 정중성은 소스별 단일 요청 + 1시간 틱 주기로 충족된다.
    """
    enabled = [s for s in sources if s.get("enabled", True)]
    results = await asyncio.gather(
        *(fetch_source(s, govapi_key=govapi_key) for s in enabled), return_exceptions=True
    )
    all_articles: list[RawArticle] = []
    for r in results:
        if isinstance(r, list):
            all_articles.extend(r)
    return _dedup(all_articles)


async def fetch_all(
    *, hn_limit: int = 15, devto_limit: int = 10, rss_limit: int = 10
) -> list[RawArticle]:
    """Aggregate from the built-in sources (HN + dev.to + Techmeme). Dedup by URL.

    Retained for callers/tests that want the default set without a source store;
    the scheduler path now uses the admin-configured sources via fetch_configured.
    """
    hn, devto, techmeme = await asyncio.gather(
        fetch_hacker_news(limit=hn_limit),
        fetch_devto(limit=devto_limit),
        fetch_rss(_TECHMEME_RSS, source_name="techmeme", limit=rss_limit),
        return_exceptions=True,
    )
    all_articles: list[RawArticle] = []
    for result in (hn, devto, techmeme):
        if isinstance(result, list):
            all_articles.extend(result)
    return _dedup(all_articles)
