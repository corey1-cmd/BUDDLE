"""Feed routes — /v1/feed (public)."""

from __future__ import annotations

from fastapi import APIRouter, Query

from buddle.api.deps import DB, CurrentUser
from buddle.schemas.post import FeedPage
from buddle.services import post_service

router = APIRouter(prefix="/feed", tags=["feed"])


@router.get(
    "",
    response_model=FeedPage,
    summary="Public feed of posts (cursor paginated)",
)
async def read_feed(
    db: DB,
    _: CurrentUser,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    tag: str | None = Query(
        default=None, max_length=64, description="Filter to posts with this exact tag name"
    ),
    q: str | None = Query(
        default=None,
        max_length=100,
        description="Case-insensitive substring search over post text",
    ),
) -> FeedPage:
    return await post_service.get_feed(db, cursor=cursor, limit=limit, tag=tag, q=q)
