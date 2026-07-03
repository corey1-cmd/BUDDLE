"""Bookmark service — idempotent save / unsave on public posts (저장).

Mirrors like_service: the (user, post) UNIQUE constraint makes saving
idempotent, and the unique-violation race is swallowed so two concurrent save
requests both end "saved". Unlike likes, bookmarks are *private curation* —
they generate no notification and feed no importance/mediator signal, so a
user can save freely without socially endorsing anything.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from buddle.core.exceptions import NotFound
from buddle.db.models.enums import PostVisibility
from buddle.db.models.post import Post
from buddle.db.models.post_bookmark import PostBookmark
from buddle.schemas.post import PostFeedItem


async def _public_post_or_404(db: AsyncSession, post_id: uuid.UUID) -> Post:
    post = await db.get(Post, post_id)
    if not post or post.visibility != PostVisibility.PUBLIC or post.is_suppressed:
        raise NotFound("Post not found.")
    return post


async def bookmark_post(db: AsyncSession, user_id: uuid.UUID, post_id: uuid.UUID) -> bool:
    """Save a post (idempotent). Returns True if a new bookmark was created."""
    await _public_post_or_404(db, post_id)
    existing = (
        await db.execute(
            select(PostBookmark.id).where(
                PostBookmark.user_id == user_id, PostBookmark.post_id == post_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return False  # already saved — no-op
    db.add(PostBookmark(user_id=user_id, post_id=post_id))
    try:
        await db.commit()
    except IntegrityError:
        # Concurrent save won the race; the end state is still "saved".
        await db.rollback()
        return False
    return True


async def unbookmark_post(db: AsyncSession, user_id: uuid.UUID, post_id: uuid.UUID) -> bool:
    """Remove a bookmark (idempotent). Returns True if one was removed."""
    result = await db.execute(
        delete(PostBookmark).where(PostBookmark.user_id == user_id, PostBookmark.post_id == post_id)
    )
    await db.commit()
    return bool(result.rowcount)


async def has_bookmarked(db: AsyncSession, user_id: uuid.UUID, post_id: uuid.UUID) -> bool:
    return (
        await db.execute(
            select(PostBookmark.id).where(
                PostBookmark.user_id == user_id, PostBookmark.post_id == post_id
            )
        )
    ).scalar_one_or_none() is not None


async def bookmark_count(db: AsyncSession, user_id: uuid.UUID) -> int:
    return int(
        await db.scalar(select(func.count(PostBookmark.id)).where(PostBookmark.user_id == user_id))
        or 0
    )


async def list_bookmarked_posts(
    db: AsyncSession, user_id: uuid.UUID, *, limit: int = 30
) -> list[PostFeedItem]:
    """The user's saved posts, most recently saved first.

    Suppressed / no-longer-public posts drop out of the list (the bookmark row
    survives, so a post restored to public reappears). Rendered with the same
    feed-item shape the feed uses, so the client reuses its card renderer.
    """
    limit = max(1, min(limit, 100))
    rows = await db.execute(
        select(Post)
        .join(PostBookmark, PostBookmark.post_id == Post.id)
        .where(
            PostBookmark.user_id == user_id,
            Post.visibility == PostVisibility.PUBLIC,
            Post.is_suppressed.is_(False),
        )
        .order_by(PostBookmark.created_at.desc())
        .limit(limit)
    )
    posts = list(rows.scalars())

    # Reuse the feed's item assembler (personas + tags + importance prefetch).
    from buddle.services.post_service import _feed_items_for_posts

    return await _feed_items_for_posts(db, posts)
