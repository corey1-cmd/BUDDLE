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

from buddle.ai.news.fetcher import RawArticle, fetch_all
from buddle.ai.news.mediator import MediatedArticle, analyse_batch
from buddle.core.logging import get_logger
from buddle.core.types import RedisClient
from buddle.db.models.knowledge_audit import KnowledgeAudit

log = get_logger(__name__)

_BRIEFINGS_KEY = "buddle:news:briefings"
_SEEN_KEY = "buddle:news:seen"
_STATUS_KEY = "buddle:news:status"
_BRIEFINGS_TTL = 60 * 60 * 25   # 25 hours
_SEEN_TTL = 60 * 60 * 48        # 48 hours (dedup window)
_MAX_STORED = 60                 # max articles kept in cache


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


async def news_tick(db: AsyncSession, *, redis: RedisClient) -> dict[str, object]:
    """Main scheduler entry-point. Returns a summary dict for the scheduler log."""
    from buddle.config import get_settings
    settings = get_settings()

    log.info("news.tick.start")
    articles = await fetch_all(hn_limit=20, devto_limit=10)
    fetched = len(articles)
    log.info("news.tick.fetched", count=fetched)

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


async def get_news_briefings(
    redis: RedisClient,
    *,
    topics: list[str] | None = None,
    limit: int = 8,
) -> list[dict[str, object]]:
    """Read path — called by persona AI during conversation (EKB Stage B: Search).

    Returns articles filtered by topic overlap with the current conversation
    topics, sorted by relevance, capped at `limit`.
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

        def _score(b: dict[str, object]) -> float:
            tags_lower = {str(t).lower() for t in (b.get("tags") or [])}
            overlap = len(topic_set & tags_lower)
            return float(b.get("relevance", 0.5)) + overlap * 0.2

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


def build_news_context_block(briefings: list[dict[str, object]]) -> str:
    """EKB Stage B reassembly — produce a compact prompt injection block.

    This block is injected into the synthesize prompt so the persona can
    naturally reference current tech news without hallucinating.
    """
    if not briefings:
        return ""
    lines = ["[최신 기술·사회 뉴스 브리핑 — 자연스럽게 대화에 활용하세요]"]
    for i, b in enumerate(briefings[:5], 1):
        briefing = b.get("ekb_briefing") or b.get("gist_ko") or b.get("title", "")
        tags = ", ".join(str(t) for t in (b.get("tags") or [])[:3])
        lines.append(f"{i}. {briefing}" + (f" [{tags}]" if tags else ""))
    return "\n".join(lines)
