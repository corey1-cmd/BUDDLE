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
import hashlib
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
                title = re.sub(r"<[^>]+>", "", title_m.group(1)).strip()
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
                summary = re.sub(r"<[^>]+>", " ", desc_m.group(1)).strip() if desc_m else ""
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


def _dedup(articles: list[RawArticle]) -> list[RawArticle]:
    """Keep the first occurrence per URL."""
    seen: set[str] = set()
    unique: list[RawArticle] = []
    for a in articles:
        if a.url not in seen:
            seen.add(a.url)
            unique.append(a)
    return unique


async def fetch_source(source: dict[str, object]) -> list[RawArticle]:
    """Fetch one configured source. Dispatches by `kind`:
      - 'hackernews' / 'devto': fixed open APIs (url ignored)
      - 'rss': arbitrary feed `url` (SSRF-validated before the request)

    Disabled sources return []. Unknown kinds and unsafe URLs are skipped
    (logged), never raised — one bad source can't break the whole sweep.
    """
    if not source.get("enabled", True):
        return []
    kind = str(source.get("kind", "")).lower()
    limit_raw = source.get("limit", 10)
    limit = limit_raw if isinstance(limit_raw, int) else 10
    name = str(source.get("id") or source.get("name") or kind)
    try:
        if kind == "hackernews":
            return await fetch_hacker_news(limit=limit)
        if kind == "devto":
            return await fetch_devto(limit=limit)
        if kind == "rss":
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
            return await fetch_rss(url, source_name=name, limit=limit)
        log.warning("news.source.unknown_kind", source=name, kind=kind)
        return []
    except Exception as e:  # one source failing must not abort the sweep
        log.warning("news.source.fetch_error", source=name, kind=kind, error=str(e))
        return []


async def fetch_configured(sources: list[dict[str, object]]) -> list[RawArticle]:
    """Fetch every enabled configured source concurrently. Dedup by URL."""
    enabled = [s for s in sources if s.get("enabled", True)]
    results = await asyncio.gather(*(fetch_source(s) for s in enabled), return_exceptions=True)
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
