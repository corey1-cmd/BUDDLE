"""Open-web tech news fetcher.

Sources (all free, no auth, robots.txt-compliant):
  - Hacker News Firebase REST API (official, open)
  - Techmeme RSS  (public feed, standard aggregator RSS)
  - Dev.to API    (open JSON API)

Each source returns a list of RawArticle dataclasses. The caller deduplicates
by URL hash before passing to the mediator AI for analysis.
"""

from __future__ import annotations

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


@dataclass(frozen=True, slots=True)
class RawArticle:
    url: str
    title: str
    source: str
    score: int = 0
    comments: int = 0
    published_at: int = field(default_factory=lambda: int(time.time()))

    @property
    def url_hash(self) -> str:
        return hashlib.sha256(self.url.encode()).hexdigest()[:16]


async def fetch_hacker_news(*, limit: int = 20) -> list[RawArticle]:
    """Fetch top stories from Hacker News Firebase API."""
    articles: list[RawArticle] = []
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            r = await client.get(_HN_TOP_STORIES)
            r.raise_for_status()
            ids: list[int] = r.json()[:limit]

            for item_id in ids:
                try:
                    ir = await client.get(_HN_ITEM.format(item_id))
                    ir.raise_for_status()
                    item = ir.json()
                    if not item or item.get("type") != "story":
                        continue
                    url = item.get("url") or f"https://news.ycombinator.com/item?id={item_id}"
                    title = item.get("title", "").strip()
                    if not title:
                        continue
                    articles.append(RawArticle(
                        url=url,
                        title=title,
                        source="hackernews",
                        score=item.get("score", 0),
                        comments=item.get("descendants", 0),
                        published_at=item.get("time", int(time.time())),
                    ))
                except Exception as e:
                    log.debug("hn.item_fetch_error", item_id=item_id, error=str(e))
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
                articles.append(RawArticle(
                    url=url,
                    title=title,
                    source="devto",
                    score=item.get("public_reactions_count", 0),
                    comments=item.get("comments_count", 0),
                ))
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
                title_m = re.search(r"<title[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", raw, re.DOTALL)
                link_m = re.search(r"<link[^>]*>(?:<!\[CDATA\[)?(https?://[^\s<]+?)(?:\]\]>)?</link>", raw, re.DOTALL)
                if not link_m:
                    link_m = re.search(r'<link[^>]+href="(https?://[^"]+)"', raw)
                if not title_m or not link_m:
                    continue
                title = re.sub(r"<[^>]+>", "", title_m.group(1)).strip()
                link = link_m.group(1).strip()
                if not title or not link:
                    continue
                articles.append(RawArticle(url=link, title=title, source=source_name))
    except Exception as e:
        log.warning("rss.fetch_error", source=source_name, url=url, error=str(e))
    return articles


async def fetch_all(*, hn_limit: int = 15, devto_limit: int = 10) -> list[RawArticle]:
    """Aggregate from all configured sources. Dedup by URL."""
    import asyncio

    hn, devto = await asyncio.gather(
        fetch_hacker_news(limit=hn_limit),
        fetch_devto(limit=devto_limit),
        return_exceptions=True,
    )
    all_articles: list[RawArticle] = []
    for result in (hn, devto):
        if isinstance(result, list):
            all_articles.extend(result)

    # Dedup by URL (keep first occurrence per URL)
    seen: set[str] = set()
    unique: list[RawArticle] = []
    for a in all_articles:
        if a.url not in seen:
            seen.add(a.url)
            unique.append(a)
    return unique
