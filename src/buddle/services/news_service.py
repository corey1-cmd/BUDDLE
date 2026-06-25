"""News ingestion service — orchestrates fetch → mediate → store → audit.

Storage strategy (Redis-first, no schema changes required):
  - Fetched/analysed articles → Redis key `buddle:news:briefings` (JSON list, 25h TTL)
  - Seen URL hashes → Redis SET `buddle:news:seen` (48h TTL per member, no-dedup drift)
  - KnowledgeAudit → DB (append-only log, existing table)

EKB reassembly:
  The `get_news_briefing(topics)` function is called by the persona AI during
  conversation (Stage B: Search step). It retrieves the stored MediatedArticles
  filtered by topic overlap and returns a compact briefing block for injection
  into the synthesis prompt.

Admin endpoint returns:
  - `GET /v1/admin/news/status` — last_run, fetched_count, stored_count, sources
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from buddle.ai.news.fetcher import RawArticle, fetch_configured
from buddle.ai.news.mediator import MediatedArticle, analyse_batch, synthesize_digest
from buddle.core.logging import get_logger
from buddle.core.types import RedisClient
from buddle.db.models.knowledge_audit import KnowledgeAudit

log = get_logger(__name__)

_BRIEFINGS_KEY = "buddle:news:briefings"
_SEEN_KEY = "buddle:news:seen"
_STATUS_KEY = "buddle:news:status"
_DIGEST_KEY = "buddle:news:digest"   # mediator-combined briefing (the 'combination' stage)
_SOURCES_KEY = "buddle:news:sources"  # admin-configured fetch sources (where to search)
_BRIEFINGS_TTL = 60 * 60 * 25   # 25 hours
_SEEN_TTL = 60 * 60 * 48        # 48 hours (dedup window)
_MAX_STORED = 60                 # max articles kept in cache

# Source kinds the fetcher can dispatch. 'rss' takes an arbitrary feed url
# (Techmeme, WSJ, New Yorker, …); the API kinds use their own fixed endpoints.
_ALLOWED_KINDS = ("rss", "hackernews", "devto")

# Seeded on first read so behaviour matches the previous hardcoded set. Techmeme
# is the worked example of a free, public RSS feed; add WSJ/New Yorker as rss too.
DEFAULT_SOURCES: list[dict[str, object]] = [
    {"id": "hackernews", "name": "Hacker News", "kind": "hackernews",
     "url": "", "enabled": True, "limit": 20},
    {"id": "devto", "name": "dev.to", "kind": "devto",
     "url": "", "enabled": True, "limit": 10},
    {"id": "techmeme", "name": "Techmeme", "kind": "rss",
     "url": "https://www.techmeme.com/feed.xml", "enabled": True, "limit": 10},
]


@dataclass
class NewsStatus:
    last_run_ts: float = 0.0
    fetched: int = 0
    new_items: int = 0
    stored: int = 0
    sources: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.sources is None:
            self.sources = []


async def _is_seen(redis: RedisClient, url_hash: str) -> bool:
    return bool(await redis.sismember(_SEEN_KEY, url_hash))


async def _mark_seen(redis: RedisClient, url_hash: str) -> None:
    await redis.sadd(_SEEN_KEY, url_hash)
    await redis.expire(_SEEN_KEY, _SEEN_TTL)


async def _store_briefings(redis: RedisClient, articles: list[MediatedArticle]) -> None:
    """Prepend new briefings to the Redis list, cap at MAX_STORED."""
    serialised = [json.dumps({
        "url": a.raw.url,
        "title": a.raw.title,
        "source": a.raw.source,
        "gist_ko": a.gist_ko,
        "tags": a.tags,
        "ekb_briefing": a.ekb_briefing,
        "relevance": a.relevance,
        "stub": a.stub,
        "stored_at": int(time.time()),
    }, ensure_ascii=False) for a in articles]

    if not serialised:
        return

    pipe = redis.pipeline()
    for s in reversed(serialised):
        pipe.lpush(_BRIEFINGS_KEY, s)
    pipe.ltrim(_BRIEFINGS_KEY, 0, _MAX_STORED - 1)
    pipe.expire(_BRIEFINGS_KEY, _BRIEFINGS_TTL)
    await pipe.execute()


async def _audit(db: AsyncSession, count: int, source_summary: str) -> None:
    audit = KnowledgeAudit(
        actor_ai="mediator",
        action="news_ingest",
        target_type="external_content",
        target_id=None,
        verdict="retained",
        note=f"articles={count}; sources={source_summary}",
    )
    db.add(audit)
    await db.commit()


# ── News-source store (where to fetch from) ────────────────────────────────
#
# The admin configures which sources the pipeline searches. Stored as a JSON
# list under a single Redis key (Redis-first, like the rest of the news
# pipeline). The fetch path (news_tick) reads this store before searching, so
# adding Techmeme / WSJ / New Yorker is a config change, not a code change.


def _slugify(name: str) -> str:
    import re

    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "source"


async def get_news_sources(redis: RedisClient) -> list[dict[str, object]]:
    """Return the configured sources, seeding the defaults on first use."""
    raw = await redis.get(_SOURCES_KEY)
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass
    await _save_sources(redis, DEFAULT_SOURCES)
    return list(DEFAULT_SOURCES)


async def _save_sources(redis: RedisClient, sources: list[dict[str, object]]) -> None:
    await redis.set(_SOURCES_KEY, json.dumps(sources, ensure_ascii=False))


async def add_news_source(
    redis: RedisClient,
    *,
    name: str,
    kind: str,
    url: str = "",
    limit: int = 10,
    enabled: bool = True,
) -> dict[str, object]:
    """Add a source. Validates kind, and for `rss` validates the URL (scheme +
    SSRF). Raises ValueError on bad input (the endpoint maps it to 400)."""
    name = (name or "").strip()
    kind = (kind or "").strip().lower()
    url = (url or "").strip()
    if not name:
        raise ValueError("name is required")
    if kind not in _ALLOWED_KINDS:
        raise ValueError(f"kind must be one of {_ALLOWED_KINDS}")
    if kind == "rss":
        if not url:
            raise ValueError("rss source requires a feed url")
        from buddle.core.ssrf import SSRFValidationError, validate_outbound_url

        try:
            validate_outbound_url(url)
        except SSRFValidationError as e:
            raise ValueError(f"unsafe url: {e}") from e
    else:
        url = ""  # API kinds use fixed endpoints

    sources = await get_news_sources(redis)
    base = _slugify(name)
    existing = {str(s.get("id")) for s in sources}
    sid = base
    i = 2
    while sid in existing:
        sid = f"{base}-{i}"
        i += 1
    source: dict[str, object] = {
        "id": sid, "name": name, "kind": kind, "url": url,
        "enabled": bool(enabled), "limit": max(1, min(int(limit), 50)),
        "added_at": int(time.time()),
    }
    sources.append(source)
    await _save_sources(redis, sources)
    return source


async def set_source_enabled(redis: RedisClient, source_id: str, enabled: bool) -> bool:
    sources = await get_news_sources(redis)
    found = False
    for s in sources:
        if str(s.get("id")) == source_id:
            s["enabled"] = bool(enabled)
            found = True
    if found:
        await _save_sources(redis, sources)
    return found


async def delete_news_source(redis: RedisClient, source_id: str) -> bool:
    sources = await get_news_sources(redis)
    remaining = [s for s in sources if str(s.get("id")) != source_id]
    if len(remaining) == len(sources):
        return False
    await _save_sources(redis, remaining)
    return True


async def news_tick(db: AsyncSession, *, redis: RedisClient) -> dict[str, object]:
    """Main scheduler entry-point. Returns a summary dict for the scheduler log."""
    from buddle.config import get_settings
    settings = get_settings()

    log.info("news.tick.start")
    # Where to search: consult the admin-configured source store first.
    sources = await get_news_sources(redis)
    articles = await fetch_configured(sources)
    fetched = len(articles)
    log.info("news.tick.fetched", count=fetched, sources=len(sources))

    # Filter already-seen articles
    new_articles: list[RawArticle] = []
    for a in articles:
        if not await _is_seen(redis, a.url_hash):
            new_articles.append(a)

    log.info("news.tick.new", count=len(new_articles))
    if not new_articles:
        return {"fetched": fetched, "new": 0, "stored": 0}

    # AI analysis via mediator
    mediated = await analyse_batch(new_articles, settings=settings, max_concurrent=3)

    # Filter by relevance threshold
    threshold = getattr(settings, "news_relevance_threshold", 0.3)
    kept = [m for m in mediated if m.relevance >= threshold]

    # Store in Redis + mark seen
    await _store_briefings(redis, kept)
    for m in kept:
        await _mark_seen(redis, m.raw.url_hash)

    # Combination stage — the mediator weaves the kept articles into ONE cohesive
    # digest (not a flat list). Stored separately for the background page and as
    # the lead block delivered to personas. Failure here never breaks ingestion.
    digest_text = ""
    if kept:
        try:
            digest_text = await synthesize_digest(kept, settings=settings)
            if digest_text:
                digest_tags = list({t for m in kept for t in m.tags})[:8]
                await redis.setex(_DIGEST_KEY, _BRIEFINGS_TTL, json.dumps(
                    {"text": digest_text, "tags": digest_tags,
                     "count": len(kept), "ts": int(time.time())},
                    ensure_ascii=False,
                ))
        except Exception as e:
            log.warning("news.digest_error", error=str(e))

    # Save status snapshot
    sources = list({m.raw.source for m in kept})
    status = {
        "last_run_ts": time.time(),
        "fetched": fetched,
        "new_items": len(new_articles),
        "stored": len(kept),
        "sources": sources,
    }
    await redis.setex(_STATUS_KEY, _BRIEFINGS_TTL, json.dumps(status, ensure_ascii=False))

    # KnowledgeAudit log
    try:
        await _audit(db, len(kept), ",".join(sources))
    except Exception as e:
        log.warning("news.audit_error", error=str(e))

    log.info("news.tick.done", fetched=fetched, new=len(new_articles), stored=len(kept))
    return {"fetched": fetched, "new": len(new_articles), "stored": len(kept)}


def _topic_overlap(briefing: dict[str, object], topic_set: set[str]) -> int:
    """Number of briefing tags that appear (substring-aware) in the topics.

    Tags are short Korean/English topical labels; conversation topics are
    salient content tokens. We count a tag as overlapping when it shares a
    token with — or is a substring of — any topic, so '인공지능' matches a
    topic of 'AI인공지능' and vice versa.
    """
    tags_lower = {str(t).lower() for t in (briefing.get("tags") or [])}
    overlap = 0
    for tag in tags_lower:
        if tag in topic_set or any(tag in t or t in tag for t in topic_set):
            overlap += 1
    return overlap


async def get_news_briefings(
    redis: RedisClient,
    *,
    topics: list[str] | None = None,
    limit: int = 8,
    require_topic_match: bool = False,
) -> list[dict[str, object]]:
    """Read path — called by persona AI during conversation (EKB Stage B: Search).

    Returns articles sorted by relevance (boosted by topic overlap), capped at
    `limit`. When `require_topic_match` is True and `topics` are given, briefings
    with zero topic overlap are dropped — so casual conversation turns are not
    derailed by unrelated tech news. With no topics (admin view) all are returned.
    """
    raw_items = await redis.lrange(_BRIEFINGS_KEY, 0, _MAX_STORED - 1)
    briefings: list[dict[str, object]] = []
    for raw in raw_items:
        try:
            briefings.append(json.loads(raw))
        except json.JSONDecodeError:
            pass

    if topics:
        topic_set = {t.lower() for t in topics}

        if require_topic_match:
            briefings = [b for b in briefings if _topic_overlap(b, topic_set) > 0]

        def _score(b: dict[str, object]) -> float:
            return float(b.get("relevance", 0.5)) + _topic_overlap(b, topic_set) * 0.2

        briefings.sort(key=_score, reverse=True)

    return briefings[:limit]


async def get_news_status(redis: RedisClient) -> dict[str, object]:
    """Return the last-run status for the admin dashboard."""
    raw = await redis.get(_STATUS_KEY)
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return {"last_run_ts": 0, "fetched": 0, "new_items": 0, "stored": 0, "sources": []}


async def get_news_digest(redis: RedisClient) -> dict[str, object]:
    """Return the mediator-combined digest (the 'combination' stage output)."""
    raw = await redis.get(_DIGEST_KEY)
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return {"text": "", "tags": [], "count": 0, "ts": 0}


def build_news_context_block(
    briefings: list[dict[str, object]],
    *,
    digest: str = "",
) -> str:
    """EKB Stage B reassembly — produce a compact prompt injection block.

    Injected into the synthesis prompt so the persona can naturally reference
    current tech news without hallucinating. When a mediator-combined `digest`
    is provided it leads the block (the synthesised view), followed by the
    specific topic-relevant items.
    """
    if not briefings and not digest:
        return ""
    lines = ["[최신 기술·사회 뉴스 브리핑 — 자연스럽게 대화에 활용하세요]"]
    if digest:
        lines.append(f"· 매개자 종합: {digest}")
    for i, b in enumerate(briefings[:5], 1):
        briefing = b.get("ekb_briefing") or b.get("gist_ko") or b.get("title", "")
        tags = ", ".join(str(t) for t in (b.get("tags") or [])[:3])
        lines.append(f"{i}. {briefing}" + (f" [{tags}]" if tags else ""))
    return "\n".join(lines)
