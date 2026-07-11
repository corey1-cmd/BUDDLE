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

import contextlib
import datetime as dt
import json
import time
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from buddle.ai.news.fetcher import RawArticle, fetch_configured, hamming64, simhash64
from buddle.ai.news.topics import (
    Topic,
    TopicInput,
    build_topics,
    classify_category,
    classify_region,
    clean_text,
    compose_digest,
    extract_keywords,
    extractive_gist,
)
from buddle.core.logging import get_logger
from buddle.core.types import RedisClient
from buddle.db.models.knowledge_audit import KnowledgeAudit
from buddle.db.models.news_item import NewsItem

log = get_logger(__name__)

_BRIEFINGS_KEY = "buddle:news:briefings"
_SEEN_KEY = "buddle:news:seen"
_STATUS_KEY = "buddle:news:status"
_DIGEST_KEY = "buddle:news:digest"  # combined briefing (the 'combination' stage)
_SOURCES_KEY = "buddle:news:sources"  # admin-configured fetch sources (where to search)
_TOPICS_KEY = "buddle:news:topics"  # algorithmic 화제 cache (홈·관심주제 노출용)
_SIMHASH_KEY = "buddle:news:simhash"  # 최근 기사 내용 지문(준중복 탐지, 48h)
_BRIEFINGS_TTL = 60 * 60 * 25  # 25 hours
_SEEN_TTL = 60 * 60 * 48  # 48 hours (dedup window)
_MAX_STORED = 60  # max articles kept in cache
_TOPIC_WINDOW_H = 72  # 화제 집계 윈도우 (DB 기준)

# Source kinds the fetcher can dispatch. 'rss' takes an arbitrary feed url
# (Techmeme, WSJ, New Yorker, …); the API kinds use their own fixed endpoints.
_ALLOWED_KINDS = ("rss", "hackernews", "devto")

# 한국어 서비스 방침: 국내 정부·공공 RSS + 해외 RSS를 함께 수집하되, 해외
# 기사는 수집 직후 한국어로 배치 번역해 공개한다(NEWS_TRANSLATE_FOREIGN,
# ai/news/translate.py — 번역 실패 시 원문 공개·해외 분류 유지). 지자체 RSS는
# admin 화면(뉴스 소스 추가)에서 URL만 등록하면 된다.
DEFAULT_SOURCES: list[dict[str, object]] = [
    {
        "id": "hackernews",
        "name": "Hacker News",
        "kind": "hackernews",
        "url": "",
        "enabled": True,
        "limit": 20,
    },
    {"id": "devto", "name": "dev.to", "kind": "devto", "url": "", "enabled": True, "limit": 10},
    {
        "id": "techmeme",
        "name": "Techmeme",
        "kind": "rss",
        "url": "https://www.techmeme.com/feed.xml",
        "enabled": True,
        "limit": 10,
    },
    # Public RSS expansion (beta Phase 2). Official feeds only — the rights
    # engine's default-deny policy means we store title+link+meta and write
    # our own gist from the snippet; article bodies are never collected.
    {
        "id": "guardian-world",
        "name": "The Guardian",
        "kind": "rss",
        "url": "https://www.theguardian.com/world/rss",
        "enabled": True,
        "limit": 10,
    },
    {
        "id": "bbc-news",
        "name": "BBC",
        "kind": "rss",
        "url": "https://feeds.bbci.co.uk/news/rss.xml",
        "enabled": True,
        "limit": 10,
    },
    {
        "id": "the-verge",
        "name": "The Verge",
        "kind": "rss",
        "url": "https://www.theverge.com/rss/index.xml",
        "enabled": True,
        "limit": 10,
    },
    {
        "id": "ars-technica",
        "name": "Ars Technica",
        "kind": "rss",
        "url": "https://feeds.arstechnica.com/arstechnica/index",
        "enabled": True,
        "limit": 10,
    },
    # ── 정부·공공(공공누리 제1유형 = 출처표시 시 상업적 이용·2차 창작 허용) ──
    # 정책브리핑(korea.kr)의 표준 RSS. 개방 등급이라 인용 추천에 우선 노출된다
    # (ai/news/rights.py). korea.kr는 국외 IP를 차단하는 경우가 있으나 소스별
    # fetch 실패는 파이프라인이 무중단 처리한다(국내 리전 서버에선 정상 수집).
    {
        "id": "korea-kr-policy",
        "name": "대한민국 정책브리핑",
        "kind": "rss",
        "url": "https://www.korea.kr/rss/policy.xml",
        "enabled": True,
        "limit": 10,
        "rights": "kogl_type1",
    },
    {
        "id": "korea-kr-dept",
        "name": "정부 부처 보도자료",
        "kind": "rss",
        "url": "https://www.korea.kr/rss/dept_all.xml",
        "enabled": True,
        "limit": 10,
        "rights": "kogl_type1",
    },
    {
        "id": "korea-kr-fact",
        "name": "정부 팩트체크(사실은 이렇습니다)",
        "kind": "rss",
        "url": "https://www.korea.kr/rss/fact.xml",
        "enabled": True,
        "limit": 5,
        "rights": "kogl_type1",
    },
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


async def _store_briefing_dicts(redis: RedisClient, briefings: list[dict[str, object]]) -> None:
    """Prepend new briefings to the Redis list, cap at MAX_STORED.

    Takes ready-made dicts (algorithmic or LLM path both produce the same
    shape), so the storage layer no longer depends on the mediator types.
    """
    serialised = [json.dumps(b, ensure_ascii=False) for b in briefings]
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
        "id": sid,
        "name": name,
        "kind": kind,
        "url": url,
        "enabled": bool(enabled),
        "limit": max(1, min(int(limit), 50)),
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


async def reset_news_sources(redis: RedisClient) -> list[dict[str, object]]:
    """Overwrite the registry with DEFAULT_SOURCES.

    레지스트리는 Redis에 영속되므로 코드의 기본값을 바꿔도 기존 배포엔 반영되지
    않는다 — 한국 전용 기본값(해외 비활성)을 라이브에 적용하는 1클릭 경로.
    """
    await _save_sources(redis, list(DEFAULT_SOURCES))
    return list(DEFAULT_SOURCES)


def _analyse_algorithmic(article: RawArticle) -> dict[str, object]:
    """Per-article analysis with zero API calls — the LLM 대체 경로.

    Produces the same briefing dict shape the Redis cache has always held
    (gist_ko / tags / ekb_briefing / relevance), so every existing consumer
    (persona dialogue injection, user /v1/news, admin dashboard) keeps working
    unchanged. gist = 발췌(첫 문장), tags = 키워드, relevance = 소스 휴리스틱.
    """
    from buddle.ai.news.rights import is_open_license

    text = f"{article.title} {clean_text(article.summary)}"
    keywords = extract_keywords(text, limit=5)
    gist = extractive_gist(article.title, article.summary)
    category = classify_category(keywords, text)
    if article.translated:
        # 번역 후 텍스트는 한국어지만 원산지는 해외 — 언어 기반 분류가
        # '전국'으로 오분류하는 것을 원산지 표식으로 차단한다.
        scope, region = "해외", ""
    else:
        scope, region = classify_region(text, article.source)
    # 개방 라이선스(공공누리 1유형)는 인용 추천 우선순위가 높다; 그 외에는
    # 참여도(로그 스케일)를 살짝 반영한 고정 기본값 — 임계 필터(0.3)는 통과.
    relevance = 0.9 if is_open_license(article.source) else min(0.85, 0.6 + article.score / 400)
    return {
        "url": article.url,
        "title": article.title,
        "source": article.source,
        "gist_ko": gist,
        "tags": keywords or [category],
        "ekb_briefing": f"{article.title} — {gist}" if gist != article.title else article.title,
        "relevance": round(relevance, 2),
        "stub": False,
        "category": category,
        "scope": scope,
        "region": region,
        "stored_at": int(time.time()),
    }


async def _persist_items(
    db: AsyncSession, articles: list[RawArticle], analysed: list[dict[str, object]]
) -> int:
    """DB 저장 + 중복 제거: guid UNIQUE에 ON CONFLICT DO NOTHING.

    Returns the number of genuinely new rows — the pipeline's dedup truth
    (Redis seen-set stays as a cheap pre-filter but is no longer load-bearing).
    """
    if not articles:
        return 0
    rows = [
        {
            "guid": a.url_hash,
            "source": a.source,
            "title": a.title[:500],
            "url": a.url,
            "summary": clean_text(a.summary)[:2000],
            "category": str(meta["category"]),
            "scope": str(meta["scope"]),
            "region": str(meta["region"]),
            "published_at": dt.datetime.fromtimestamp(a.published_at, tz=dt.UTC),
        }
        for a, meta in zip(articles, analysed, strict=True)
    ]
    stmt = pg_insert(NewsItem).values(rows).on_conflict_do_nothing(index_elements=["guid"])
    result = await db.execute(stmt)
    await db.commit()
    return int(result.rowcount or 0)


async def _backfill_translations(db: AsyncSession, *, settings: object, limit: int = 20) -> int:
    """저장돼 있는 미번역(한글 없는) 기사를 소급 번역해 DB를 치유한다.

    번역은 원래 수집 시점에만 돌기 때문에 (a) 번역 기능 배포 이전에 저장된
    기사와 (b) fail-open으로 원문이 저장된 기사가 72시간 화제 윈도우 안에
    영어로 남는다(라이브 실측: 화제 카드가 통째로 영어). 틱마다 최신순으로
    최대 limit건을 배치 번역해 UPDATE — 시스템이 스스로 낫는다.
    """
    from buddle.ai.news.translate import translate_articles

    since = dt.datetime.now(dt.UTC) - dt.timedelta(hours=_TOPIC_WINDOW_H)
    rows = (
        (
            await db.execute(
                select(NewsItem)
                .where(NewsItem.published_at >= since, ~NewsItem.title.regexp_match("[가-힣]"))
                .order_by(NewsItem.published_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return 0
    pseudo = [
        RawArticle(
            url=r.url,
            title=r.title,
            source=r.source,
            summary=r.summary,
            published_at=int(r.published_at.timestamp()),
        )
        for r in rows
    ]
    translated = await translate_articles(pseudo, settings=settings)
    healed = 0
    for row, art in zip(rows, translated, strict=True):
        if art.translated:
            row.title = art.title[:500]
            row.summary = art.summary
            healed += 1
    if healed:
        await db.commit()
        log.info("news.backfill_translate", scanned=len(rows), healed=healed)
    return healed


async def _prune_topic_posts(db: AsyncSession, redis: RedisClient, topics: list[Topic]) -> int:
    """유효하지 않은 화제 글을 정리한다 — 단, 참여가 있으면 절대 지우지 않는다.

    삭제 조건(모두 충족): author_label='지금 화제' + 좋아요 0 + 댓글 0 +
    (태그가 현재 화제 집합에 없음 또는 72h 초과). 알고리즘이 오탐 화제
    (#bloomberg류)를 만들었다가 고쳐졌을 때 그 잔재가 피드에 남지 않게 한다.
    사용자 참여가 붙은 글은 화제가 사라져도 대화 기록으로 보존된다.
    """
    from sqlalchemy import func as sa_func

    from buddle.db.models.comment import Comment
    from buddle.db.models.post import Post
    from buddle.db.models.post_like import PostLike
    from buddle.db.models.tag import PostTag, Tag

    current = {t.name[:64] for t in topics}
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(hours=_TOPIC_WINDOW_H)
    rows = (
        await db.execute(
            select(Post.id, Post.created_at, Tag.name)
            .join(PostTag, PostTag.post_id == Post.id)
            .join(Tag, Tag.id == PostTag.tag_id)
            .where(Post.author_label == NEWS_AUTHOR_LABEL)
        )
    ).all()
    pruned = 0
    for post_id, created_at, tag_name in rows:
        stale = tag_name not in current or created_at < cutoff
        if not stale:
            continue
        likes = (
            await db.execute(
                select(sa_func.count()).select_from(PostLike).where(PostLike.post_id == post_id)
            )
        ).scalar_one()
        comments = (
            await db.execute(
                select(sa_func.count()).select_from(Comment).where(Comment.post_id == post_id)
            )
        ).scalar_one()
        if likes or comments:
            continue
        post = await db.get(Post, post_id)
        if post is not None:
            await db.delete(post)
            pruned += 1
        with contextlib.suppress(Exception):
            await redis.delete(_TOPICPOST_KEY + tag_name)
    if pruned:
        await db.commit()
        log.info("news.topic_post.pruned", count=pruned)
    return pruned


async def _rebuild_topics(db: AsyncSession, redis: RedisClient) -> list[Topic]:
    """최근 윈도우의 DB 아이템으로 화제를 재계산하고 Redis에 캐시한다."""
    since = dt.datetime.now(tz=dt.UTC) - dt.timedelta(hours=_TOPIC_WINDOW_H)
    rows = (
        (await db.execute(select(NewsItem).where(NewsItem.published_at >= since).limit(500)))
        .scalars()
        .all()
    )
    inputs = [
        TopicInput(
            title=r.title,
            url=r.url,
            source=r.source,
            summary=r.summary,
            published_at=int(r.published_at.timestamp()),
            # 수집 시점 분류를 힌트로 승계 — 번역된 해외 기사가 화제 재분류에서
            # '전국'으로 뒤집히는 것을 막는다(다수결, topics.build_topics).
            category=r.category,
            scope=r.scope,
            region=r.region,
        )
        for r in rows
    ]
    topics = build_topics(inputs)
    await _cache_topics(redis, topics)
    return topics


# 캐시 포맷 버전 — 필드가 늘 때 올린다. 구버전 캐시(title 없음 등)는 배포
# 직후 그대로 서빙되면 "#키워드" 카드가 뜨므로(라이브 실측) 재계산으로 우회.
_TOPICS_CACHE_V = 2


async def _cache_topics(redis: RedisClient, topics: list[Topic]) -> None:
    await redis.setex(
        _TOPICS_KEY,
        _BRIEFINGS_TTL,
        json.dumps(
            {
                "v": _TOPICS_CACHE_V,
                "topics": [t.to_dict() for t in topics],
                "ts": int(time.time()),
            },
            ensure_ascii=False,
        ),
    )


async def news_tick(db: AsyncSession, *, redis: RedisClient) -> dict[str, object]:
    """Main scheduler entry-point. Returns a summary dict for the scheduler log.

    RSS 수집 → 파싱 → DB 저장(중복 제거) → 알고리즘 분석 → 화제/브리핑/다이제스트.
    기본 경로는 외부 AI 호출 0회. (기사당 LLM 1회를 쓰던 이전 경로는
    NEWS_AI_ANALYSIS_ENABLED=true 로만 활성화되는 opt-in으로 강등 — 무료 쿼터를
    태우고 429를 유발하던 원인이었다.)
    """
    from buddle.config import get_settings

    settings = get_settings()

    log.info("news.tick.start")
    # Where to search: consult the admin-configured source store first.
    sources = await get_news_sources(redis)
    articles = await fetch_configured(sources)
    fetched = len(articles)
    log.info("news.tick.fetched", count=fetched, sources=len(sources))

    # Redis seen-set: 같은 틱 주기 안에서의 값싼 선필터 (진짜 중복 제거는 DB UNIQUE)
    unseen: list[RawArticle] = []
    for a in articles:
        if not await _is_seen(redis, a.url_hash):
            unseen.append(a)

    # SimHash 준중복: URL은 다른데 내용이 같은 전재 기사(통신사 기사가 여러
    # 매체로 유입)를 거른다. 임계 ≤10 — 제목+요약 20~40토큰 규모에서 표기
    # 한두 곳 차이는 거리 4~6, 무관 기사 쌍은 최소 27로 실측돼(분포 27~43)
    # 여유가 17비트다. seen 처리해 다음 틱 재검사도 막는다. (설계서 §M1-4)
    new_articles: list[RawArticle] = []
    if unseen:
        near_dup = 0
        now_s = time.time()
        raw_hashes = await redis.zrangebyscore(_SIMHASH_KEY, now_s - _SEEN_TTL, "+inf")
        recent_hashes = [int(h) for h in raw_hashes if str(h).isdigit()]
        fresh_hashes: dict[str, float] = {}
        for a in unseen:
            sh = simhash64(f"{a.title} {a.summary[:300]}")
            if sh and any(hamming64(sh, r) <= 10 for r in recent_hashes):
                near_dup += 1
                await _mark_seen(redis, a.url_hash)
                continue
            if sh:
                recent_hashes.append(sh)
                fresh_hashes[str(sh)] = now_s
            new_articles.append(a)
        if fresh_hashes:
            await redis.zadd(_SIMHASH_KEY, fresh_hashes)
            await redis.zremrangebyscore(_SIMHASH_KEY, 0, now_s - _SEEN_TTL)
            await redis.expire(_SIMHASH_KEY, _SEEN_TTL)
        if near_dup:
            log.info("news.tick.near_dup", count=near_dup)

    # 해외 기사 배치 번역 — 한국어로 피드에 공개한다. 기사당이 아니라 배치당
    # 1회 호출(429 fan-out 없음), 실패 시 원문 공개(fail-open).
    if new_articles and getattr(settings, "news_translate_foreign", True):
        from buddle.ai.news.translate import needs_translation, translate_articles

        foreign_idx = [i for i, a in enumerate(new_articles) if needs_translation(a)]
        if foreign_idx:
            try:
                translated = await translate_articles(
                    [new_articles[i] for i in foreign_idx], settings=settings
                )
                for i, art in zip(foreign_idx, translated, strict=True):
                    new_articles[i] = art
            except Exception as e:
                log.warning("news.translate_error", error=str(e))
    log.info("news.tick.new", count=len(new_articles))

    stored = 0
    if new_articles:
        if getattr(settings, "news_ai_analysis_enabled", False):
            # Opt-in legacy path: per-article LLM analysis (429-prone, costly).
            from buddle.ai.news.mediator import analyse_batch

            mediated = await analyse_batch(new_articles, settings=settings, max_concurrent=3)
            threshold = getattr(settings, "news_relevance_threshold", 0.3)
            analysed = [
                {
                    "url": m.raw.url,
                    "title": m.raw.title,
                    "source": m.raw.source,
                    "gist_ko": m.gist_ko,
                    "tags": m.tags,
                    "ekb_briefing": m.ekb_briefing,
                    "relevance": m.relevance,
                    "stub": m.stub,
                    "category": classify_category(m.tags, m.raw.title),
                    "scope": classify_region(m.raw.title, m.raw.source)[0],
                    "region": classify_region(m.raw.title, m.raw.source)[1],
                    "stored_at": int(time.time()),
                }
                for m in mediated
                if m.relevance >= threshold
            ]
            kept_articles = [
                a for a, m in zip(new_articles, mediated, strict=True) if m.relevance >= threshold
            ]
        else:
            # Default path: pure algorithmic analysis — zero API calls.
            analysed = [_analyse_algorithmic(a) for a in new_articles]
            kept_articles = new_articles

        try:
            stored = await _persist_items(db, kept_articles, analysed)
        except Exception as e:  # DB unavailable must not kill the Redis path
            log.warning("news.persist_error", error=str(e))
            stored = len(kept_articles)

        await _store_briefing_dicts(redis, analysed)
        for a in kept_articles:
            await _mark_seen(redis, a.url_hash)

    # 화제 재계산(수집이 없어도 최신 윈도우 반영) + 결정론적 다이제스트.
    topics: list[Topic] = []
    try:
        topics = await _rebuild_topics(db, redis)
    except Exception as e:
        log.warning("news.topics_error", error=str(e))

    # 저장돼 있는 미번역 기사 소급 번역 — 배포 이전/실패분을 매 틱 치유.
    if getattr(settings, "news_translate_foreign", True):
        try:
            healed = await _backfill_translations(db, settings=settings)
            if healed:
                # 번역된 텍스트로 화제를 다시 계산해야 한국어 카드가 나온다.
                topics = await _rebuild_topics(db, redis)
        except Exception as e:
            log.warning("news.backfill_error", error=str(e))

    # 카드 문안 정제(틱당 배치 1회): 키워드 이름 대신 "무슨 일이 일어났는가"
    # 문장형 제목·요약·한국어 키워드. 실패해도 결정론 폴백(대표 헤드라인)이
    # 이미 채워져 있어 서빙은 계속된다.
    if topics and getattr(settings, "news_topic_refine_enabled", True):
        try:
            from buddle.ai.news.refine import refine_topics

            applied = await refine_topics(topics, settings=settings)
            if applied:
                await _cache_topics(redis, topics)
        except Exception as e:
            log.warning("news.refine_error", error=str(e))

    # 화제 → 광장 글 승격(멱등) — 상호작용(좋아요·댓글·토론)의 대상을 만든다.
    try:
        await _ensure_topic_posts(db, redis, topics)
    except Exception as e:
        log.warning("news.topic_post_error", error=str(e))

    # 잔재 화제 글 정리 — 참여 없는 오탐/만료 화제 글만 삭제(참여 글은 보존).
    try:
        await _prune_topic_posts(db, redis, topics)
    except Exception as e:
        log.warning("news.topic_post_prune_error", error=str(e))

    try:
        digest_text = compose_digest(topics)
        if digest_text:
            digest_tags = [t.name for t in topics[:8]]
            await redis.setex(
                _DIGEST_KEY,
                _BRIEFINGS_TTL,
                json.dumps(
                    {
                        "text": digest_text,
                        "tags": digest_tags,
                        "count": stored,
                        "ts": int(time.time()),
                    },
                    ensure_ascii=False,
                ),
            )
    except Exception as e:
        log.warning("news.digest_error", error=str(e))

    # Save status snapshot
    kept_sources = list({a.source for a in new_articles})
    status = {
        "last_run_ts": time.time(),
        "fetched": fetched,
        "new_items": len(new_articles),
        "stored": stored,
        "sources": kept_sources,
    }
    await redis.setex(_STATUS_KEY, _BRIEFINGS_TTL, json.dumps(status, ensure_ascii=False))

    # KnowledgeAudit log
    if stored:
        try:
            await _audit(db, stored, ",".join(kept_sources))
        except Exception as e:
            log.warning("news.audit_error", error=str(e))

    log.info(
        "news.tick.done",
        fetched=fetched,
        new=len(new_articles),
        stored=stored,
        topics=len(topics),
    )
    return {"fetched": fetched, "new": len(new_articles), "stored": stored, "topics": len(topics)}


# ── 화제 → 광장 글 승격 (레딧식 상호작용의 대상 엔티티) ─────────────────────
#
# 화제 카드를 눌렀을 때 외부 뉴스 링크가 아니라 좋아요·댓글·토론이 있는 글로
# 가야 한다. 화제마다 시스템 글을 1건 만들어 기존 상호작용(좋아요/댓글/토론/
# 논증 대화)을 전부 재사용한다 — 새 상호작용 테이블이 필요 없다.

_TOPICPOST_KEY = "buddle:news:topicpost:"  # + 화제명 → post_id (72h TTL)
_TOPICPOST_TTL = _TOPIC_WINDOW_H * 3600
NEWS_AUTHOR_LABEL = "지금 화제"


def compose_topic_post(t: Topic) -> str:
    """화제 글 본문 — 새 출력 형식: 화제/유형/핵심 사건/핵심 문제/핵심 기술/
    관련 기업/핵심 질문/미래 전망 + 관련 기사(출처 무생략).

    채워진 필드만 표기한다: 결정론 폴백은 사건·질문까지만 만들고(추측 금지),
    문제·전망은 LLM 정제가 성공했을 때만 존재한다. 이 텍스트가 논증 대화와
    댓글의 시드가 된다.
    """
    title = t.title or t.name
    lines = [f"[지금 화제] {title}", ""]
    if t.summary:
        lines += [t.summary, ""]
    meta_bits = [
        t.type_label or f"{t.category} 이슈",
        t.scope + (f" · {t.region}" if t.region else ""),
    ]
    lines.append("유형: " + " · ".join(b for b in meta_bits if b))
    if t.event and t.event != title:
        lines.append(f"핵심 사건: {t.event}")
    if t.problem:
        lines.append(f"핵심 문제: {t.problem}")
    if t.technologies:
        lines.append("핵심 기술: " + ", ".join(t.technologies))
    if t.entities:
        lines.append("관련 기업·인물: " + ", ".join(t.entities))
    if t.question:
        lines.append(f"핵심 질문: {t.question}")
    if t.forecast:
        lines.append(f"미래 전망: {t.forecast}")
    if t.display_keywords:
        lines.append("관련 키워드: " + ", ".join(t.display_keywords))
    lines.append("")
    lines.append(f"관련 기사 {t.count}건 · 매체 {len(t.sources)}곳 · 추세 {t.trend}:")
    for h in t.headlines[:4]:
        date = f", {h['date']}" if h.get("date") else ""
        lines.append(f"· {h.get('title', '')} ({h.get('source', '')}{date})")
    lines += ["", "이 화제, 어떻게 생각하세요? 댓글이나 토론으로 생각을 나눠보세요."]
    return "\n".join(lines)


async def _ensure_topic_posts(
    db: AsyncSession, redis: RedisClient, topics: list[Topic]
) -> dict[str, str]:
    """화제마다 공개 글을 정확히 1건 보장하고 {화제명: post_id}를 돌려준다.

    멱등성 2중 보장: Redis 매핑(72h TTL) 선조회 → 미스 시 DB에서 같은 태그의
    최근 시스템 글을 재사용(Redis 재시작 대비) → 그래도 없으면 생성.

    의도적으로 post_service._ingest_post(윤리 게이트+mediator)를 타지 않는다:
    본문이 집계값·헤드라인 발췌로만 조립되는 결정론적 자체 생성 텍스트라
    LLM 게이트가 불필요하고, 2분 틱마다 모델 호출을 유발하면 무-LLM 원칙이
    깨진다. 사용자 유래 텍스트는 이 경로에 절대 섞이지 않는다.
    """
    from buddle.db.models.enums import AuthorKind, PostVisibility
    from buddle.db.models.importance import ImportanceScore
    from buddle.db.models.post import Post
    from buddle.db.models.tag import PostTag, Tag

    mapping: dict[str, str] = {}
    since = dt.datetime.now(dt.UTC) - dt.timedelta(hours=_TOPIC_WINDOW_H)
    for t in topics:
        if t.count < 2 or not t.name:
            continue
        tag_name = t.name[:64]
        key = _TOPICPOST_KEY + tag_name
        cached = await redis.get(key)
        if cached:
            mapping[t.name] = str(cached)
            continue

        # DB 폴백 — Redis가 비워져도 같은 화제 글을 중복 생성하지 않는다.
        existing = (
            await db.execute(
                select(Post.id)
                .join(PostTag, PostTag.post_id == Post.id)
                .join(Tag, Tag.id == PostTag.tag_id)
                .where(
                    Tag.name == tag_name,
                    Post.author_kind == AuthorKind.EXTERNAL_AI,
                    Post.author_label == NEWS_AUTHOR_LABEL,
                    Post.created_at >= since,
                )
                .order_by(Post.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            mapping[t.name] = str(existing)
            await redis.setex(key, _TOPICPOST_TTL, str(existing))
            continue

        content = compose_topic_post(t)
        post = Post(
            source_persona_id=None,
            agent_id=None,
            author_kind=AuthorKind.EXTERNAL_AI,
            author_label=NEWS_AUTHOR_LABEL,
            content_raw=content,
            content_transformed=content,
            visibility=PostVisibility.PUBLIC,
        )
        db.add(post)
        await db.flush()
        db.add(ImportanceScore(post_id=post.id, raw_score=0.0, normalized=0.0))
        tag = (await db.execute(select(Tag).where(Tag.name == tag_name))).scalar_one_or_none()
        if tag is None:
            tag = Tag(name=tag_name)
            db.add(tag)
            await db.flush()
        db.add(PostTag(post_id=post.id, tag_id=tag.id))
        await db.commit()
        mapping[t.name] = str(post.id)
        await redis.setex(key, _TOPICPOST_TTL, str(post.id))
        log.info("news.topic_post.created", topic=t.name, post_id=str(post.id))
    return mapping


async def _attach_topic_posts(
    db: AsyncSession, redis: RedisClient, topics: list[dict[str, object]]
) -> list[dict[str, object]]:
    """서빙 직전에 화제 dict에 post_id + 좋아요/댓글 수를 붙인다.

    카드의 상호작용 버튼(좋아요·댓글·토론)이 실카운트를 보여야 하므로,
    Redis 매핑 일괄 조회 후 카운트는 그룹 집계 2쿼리로 끝낸다.
    """
    import uuid as _uuid

    from sqlalchemy import func as sa_func

    from buddle.db.models.comment import Comment
    from buddle.db.models.post_like import PostLike

    if not topics:
        return topics
    keys = [_TOPICPOST_KEY + str(t.get("name") or "")[:64] for t in topics]
    values = await redis.mget(keys)
    post_ids: list[_uuid.UUID] = []
    for t, v in zip(topics, values, strict=True):
        if v:
            t["post_id"] = str(v)
            with contextlib.suppress(ValueError):
                post_ids.append(_uuid.UUID(str(v)))
    if post_ids:
        like_map = {
            pid: int(n)
            for pid, n in (
                await db.execute(
                    select(PostLike.post_id, sa_func.count())
                    .where(PostLike.post_id.in_(post_ids))
                    .group_by(PostLike.post_id)
                )
            ).all()
        }
        cmt_map = {
            pid: int(n)
            for pid, n in (
                await db.execute(
                    select(Comment.post_id, sa_func.count())
                    .where(Comment.post_id.in_(post_ids))
                    .group_by(Comment.post_id)
                )
            ).all()
        }
        for t in topics:
            if t.get("post_id"):
                with contextlib.suppress(ValueError):
                    pid = _uuid.UUID(str(t["post_id"]))
                    t["like_count"] = like_map.get(pid, 0)
                    t["comment_count"] = cmt_map.get(pid, 0)
    return topics


_UINTEREST_KEY = "buddle:news:uinterest:"  # + user_id → 관심 용어 캐시 (10분)
_UINTEREST_TTL = 600


async def _user_interest_terms(db: AsyncSession, redis: RedisClient, user_id: object) -> set[str]:
    """사용자의 관심 용어 집합 — 전부 사용자의 명시적 행동에서 나온다.

    원천: ① 페르소나 관심 태그 ② 좋아요한 글의 태그 ③ 저장한 글의 태그
    ④ 내가 쓴 글의 태그. 프로파일링 추론이 아니라 행동 기록의 태그 합집합이라
    설명 가능하고, opt-out 개념도 불필요(자기 행동 그 자체). 10분 캐시.
    """
    key = _UINTEREST_KEY + str(user_id)
    cached = await redis.get(key)
    if cached:
        with contextlib.suppress(json.JSONDecodeError):
            return {str(x) for x in json.loads(cached)}

    from buddle.db.models.persona import Persona
    from buddle.db.models.post import Post
    from buddle.db.models.post_bookmark import PostBookmark
    from buddle.db.models.post_like import PostLike
    from buddle.db.models.tag import PersonaInterestTag, PostTag, Tag

    terms: set[str] = set()
    my_personas = select(Persona.id).where(Persona.user_id == user_id)
    for row in (
        await db.execute(
            select(Tag.name)
            .join(PersonaInterestTag, PersonaInterestTag.tag_id == Tag.id)
            .where(PersonaInterestTag.persona_id.in_(my_personas))
        )
    ).all():
        terms.add(row[0])
    for model, cond in (
        (PostLike, PostLike.user_id == user_id),
        (PostBookmark, PostBookmark.user_id == user_id),
    ):
        for row in (
            await db.execute(
                select(Tag.name)
                .join(PostTag, PostTag.tag_id == Tag.id)
                .join(model, model.post_id == PostTag.post_id)
                .where(cond)
                .limit(200)
            )
        ).all():
            terms.add(row[0])
    for row in (
        await db.execute(
            select(Tag.name)
            .join(PostTag, PostTag.tag_id == Tag.id)
            .join(Post, Post.id == PostTag.post_id)
            .where(Post.source_persona_id.in_(my_personas))
            .limit(200)
        )
    ).all():
        terms.add(row[0])

    terms = {t.lower() for t in terms if t}
    with contextlib.suppress(Exception):
        await redis.setex(key, _UINTEREST_TTL, json.dumps(sorted(terms), ensure_ascii=False))
    return terms


def _topic_affinity(terms: set[str], t: dict[str, object]) -> int:
    """화제와 관심 용어의 겹침 수 — 이름·키워드·표시 키워드·카테고리 기준."""
    if not terms:
        return 0
    topic_terms: set[str] = {str(t.get("category") or "").lower()}
    for field_name in ("keywords", "display_keywords"):
        v = t.get(field_name)
        if isinstance(v, list):
            topic_terms.update(str(k).lower() for k in v)
    name = str(t.get("name") or "").lower()
    if name:
        topic_terms.add(name)
        topic_terms.update(name.split())
    return len(terms & topic_terms)


def rank_topics_for_user(
    topics: list[dict[str, object]], terms: set[str], mode: str
) -> list[dict[str, object]]:
    """개인화 정렬 (순수 함수 — 단위테스트 대상).

    - recommend(홈): 전체 화제 점수가 주도하되 관심 일치가 가산 —
      score × (1 + 0.3·min(affinity, 3)). "지금 뜨는 것 + 당신 취향".
    - interest(피드): 관심 일치 우선, 동률은 점수순 — "당신이 관심 가질 것".
      일치 0인 화제도 뒤에 남긴다(콜드스타트에도 빈 화면이 없다).
    """
    if mode == "interest":
        return sorted(
            topics,
            key=lambda t: (_topic_affinity(terms, t), float(t.get("score") or 0.0)),
            reverse=True,
        )
    return sorted(
        topics,
        key=lambda t: float(t.get("score") or 0.0)
        * (1.0 + 0.3 * min(_topic_affinity(terms, t), 3)),
        reverse=True,
    )


async def get_news_topics(
    db: AsyncSession,
    redis: RedisClient,
    *,
    scope: str | None = None,
    category: str | None = None,
    region: str | None = None,
    limit: int = 12,
    mode: str = "score",
    user_id: object | None = None,
) -> list[dict[str, object]]:
    """화제 읽기 경로 — 필터(범위·주제·위치)로 좁힌다. 위치 자동 매칭은 없다:
    사용자가 명시적으로 고른 필터만 적용된다(전국/해외 이슈는 위치 불필요).

    Redis 캐시 우선, 비어 있으면 DB에서 재계산(콜드스타트/재기동 복원).
    """
    topics: list[dict[str, object]] = []
    raw = await redis.get(_TOPICS_KEY)
    if raw:
        with contextlib.suppress(json.JSONDecodeError):
            payload = json.loads(raw)
            if payload.get("v") == _TOPICS_CACHE_V:
                topics = payload.get("topics") or []
    if not topics:
        with contextlib.suppress(Exception):
            topics = [t.to_dict() for t in await _rebuild_topics(db, redis)]

    if scope:
        topics = [t for t in topics if str(t.get("scope")) == scope]
    if category:
        topics = [t for t in topics if str(t.get("category")) == category]
    if region:
        needle = region.strip()
        topics = [t for t in topics if needle and needle in str(t.get("region") or "")]
    # 개인화: recommend(홈)=점수 주도+취향 가산 / interest(피드)=관심 일치 우선.
    # 실패해도 점수순으로 서빙(개인화는 품질 레이어, 가용성 의존성 아님).
    if user_id is not None and mode in ("recommend", "interest"):
        with contextlib.suppress(Exception):
            terms = await _user_interest_terms(db, redis, user_id)
            topics = rank_topics_for_user(topics, terms, mode)
    with contextlib.suppress(Exception):
        topics = await _attach_topic_posts(db, redis, topics)
    return topics[:limit]


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
        with contextlib.suppress(json.JSONDecodeError):
            briefings.append(json.loads(raw))

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
        raw_tags = b.get("tags")
        tags_seq = raw_tags if isinstance(raw_tags, list) else []
        tags = ", ".join(str(t) for t in tags_seq[:3])
        lines.append(f"{i}. {briefing}" + (f" [{tags}]" if tags else ""))
    return "\n".join(lines)
