"""Bookmark routes — /v1/bookmarks (my saved posts, 저장한 글).

The save/unsave toggle itself lives beside the like toggle in the plaza
router (PUT/DELETE /v1/plaza/posts/{id}/bookmark); this router is the private
reading list. Items reuse the feed's PostFeedItem shape so the client renders
saved posts with the same card component as the feed.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from buddle.api.deps import DB, CurrentUser
from buddle.schemas.post import PostFeedItem
from buddle.services import bookmark_service

router = APIRouter(prefix="/bookmarks", tags=["bookmarks"])


@router.get(
    "",
    response_model=list[PostFeedItem],
    summary="My saved posts, most recently saved first",
)
async def list_my_bookmarks(
    user: CurrentUser,
    db: DB,
    limit: int = Query(default=30, ge=1, le=100),
) -> list[PostFeedItem]:
    return await bookmark_service.list_bookmarked_posts(db, user.id, limit=limit)
