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
from buddle.api.deps import CurrentUser, Redis
from buddle.schemas.news import NewsBriefingOut, NewsDigestOut
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
