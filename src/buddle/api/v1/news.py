"""News routes — /v1/news (authenticated users, read-only).

The pipeline (fetch → mediate → store) stays admin/scheduler-driven; these
routes only expose the cached results so the app's topic feed can show
"what's happening" teasers. Field filtering is enforced here by constructing
the response models explicitly — a new internal field added to the cache can
never leak to users by accident.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from buddle.ai.news.rights import rights_of
from buddle.api.deps import DB, CurrentUser, Redis
from buddle.schemas.news import NewsBriefingOut, NewsDigestOut, NewsTopicHeadline, NewsTopicOut
from buddle.services import news_service

router = APIRouter(prefix="/news", tags=["news"])


def _tags_of(value: object) -> list[str]:
    """Cache values are untyped JSON — only a real list yields tags."""
    if not isinstance(value, list):
        return []
    return [str(t) for t in value if str(t)]


def _to_public(b: dict[str, object]) -> NewsBriefingOut:
    return NewsBriefingOut(
        title=str(b.get("title") or ""),
        url=str(b.get("url") or ""),
        source=str(b.get("source") or ""),
        gist_ko=str(b.get("gist_ko") or ""),
        tags=_tags_of(b.get("tags")),
        rights=rights_of(str(b.get("source") or "")),
        stored_at=int(b.get("stored_at") or 0),  # type: ignore[call-overload]
    )


@router.get(
    "/briefings",
    response_model=list[NewsBriefingOut],
    summary="News teasers (title + link + our gist), newest first",
)
async def list_briefings(
    _: CurrentUser,
    redis: Redis,
    limit: int = Query(default=20, ge=1, le=60),
    tag: str | None = Query(
        default=None, max_length=64, description="Filter to briefings carrying this topic tag"
    ),
) -> list[NewsBriefingOut]:
    # Fetch unfiltered then tag-filter here: the store caps at 60 items, so a
    # full read stays cheap and the filter can't under-fill the page.
    briefings = await news_service.get_news_briefings(redis, limit=60)
    if tag:
        needle = tag.lower()
        briefings = [
            b for b in briefings if any(needle == t.lower() for t in _tags_of(b.get("tags")))
        ]
    return [_to_public(b) for b in briefings[:limit]]


@router.get(
    "/digest",
    response_model=NewsDigestOut,
    summary="Combined cross-article digest (our own synthesis)",
)
async def read_digest(_: CurrentUser, redis: Redis) -> NewsDigestOut:
    d = await news_service.get_news_digest(redis)
    return NewsDigestOut(
        text=str(d.get("text") or ""),
        tags=_tags_of(d.get("tags")),
        count=int(d.get("count") or 0),  # type: ignore[call-overload]
        ts=int(d.get("ts") or 0),  # type: ignore[call-overload]
    )


_TOPIC_SCOPES = ("동네", "시", "도", "전국", "해외")
_TOPIC_CATEGORIES = ("환경", "교육", "경제", "정치", "기술", "사회")


@router.get(
    "/topics",
    response_model=list[NewsTopicOut],
    summary="알고리즘 집계 화제 — 범위/주제/위치 필터로 탐색 (위치 자동 매칭 없음)",
)
async def list_topics(
    user: CurrentUser,
    db: DB,
    redis: Redis,
    scope: str | None = Query(default=None, description="동네|시|도|전국|해외"),
    category: str | None = Query(default=None, description="환경|교육|경제|정치|기술|사회"),
    region: str | None = Query(
        default=None,
        max_length=40,
        description="선택 — 지역 이슈를 좁힐 때만 (예: 성남). 전국/해외엔 불필요",
    ),
    limit: int = Query(default=12, ge=1, le=24),
    mode: str = Query(
        default="score",
        description="score=전체 점수순 | recommend=홈 추천(점수+취향 가산) | interest=관심 일치 우선",
    ),
) -> list[NewsTopicOut]:
    if scope and scope not in _TOPIC_SCOPES:
        scope = None
    if category and category not in _TOPIC_CATEGORIES:
        category = None
    if mode not in ("score", "recommend", "interest"):
        mode = "score"
    topics = await news_service.get_news_topics(
        db,
        redis,
        scope=scope,
        category=category,
        region=region,
        limit=limit,
        mode=mode,
        user_id=user.id,
    )
    out: list[NewsTopicOut] = []
    for t in topics:
        heads_raw = t.get("headlines")
        heads = heads_raw if isinstance(heads_raw, list) else []
        sources_raw = t.get("sources")
        sources_list = sources_raw if isinstance(sources_raw, list) else []
        kws_raw = t.get("display_keywords")
        kws_list = kws_raw if isinstance(kws_raw, list) else []
        out.append(
            NewsTopicOut(
                name=str(t.get("name") or ""),
                count=int(t.get("count") or 0),  # type: ignore[call-overload]
                sources=[str(x) for x in sources_list],
                category=str(t.get("category") or "사회"),
                scope=str(t.get("scope") or "해외"),
                region=str(t.get("region") or ""),
                headlines=[
                    NewsTopicHeadline(
                        title=str(h.get("title") or ""),
                        url=str(h.get("url") or ""),
                        source=str(h.get("source") or ""),
                        date=str(h.get("date") or ""),
                    )
                    for h in heads
                    if isinstance(h, dict)
                ],
                trend=str(t.get("trend") or "유지"),
                p_rise=float(t.get("p_rise") or 0.0),  # type: ignore[arg-type]
                post_id=(str(t["post_id"]) if t.get("post_id") else None),
                title=str(t.get("title") or ""),
                summary=str(t.get("summary") or ""),
                keywords=[str(k) for k in kws_list],
                like_count=int(t.get("like_count") or 0),  # type: ignore[call-overload]
                comment_count=int(t.get("comment_count") or 0),  # type: ignore[call-overload]
            )
        )
    return out
