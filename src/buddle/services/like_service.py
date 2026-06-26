"""Like service — idempotent like / unlike on public posts.

The (user, post) UNIQUE constraint makes likes idempotent: liking twice is a
no-op, unliking removes the row. We swallow the unique-violation race so two
concurrent like requests both end "liked" without error.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from buddle.core.exceptions import NotFound
from buddle.db.models.enums import PostVisibility
from buddle.db.models.post import Post
from buddle.db.models.post_like import PostLike


async def _public_post_or_404(db: AsyncSession, post_id: uuid.UUID) -> Post:
    post = await db.get(Post, post_id)
    if not post or post.visibility != PostVisibility.PUBLIC or post.is_suppressed:
        raise NotFound("Post not found.")
    return post


async def like_post(db: AsyncSession, user_id: uuid.UUID, post_id: uuid.UUID) -> bool:
    """Like a post (idempotent). Returns True if a new like was created."""
    await _public_post_or_404(db, post_id)
    existing = (
        await db.execute(
            select(PostLike.id).where(PostLike.user_id == user_id, PostLike.post_id == post_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return False  # already liked — no-op
    db.add(PostLike(user_id=user_id, post_id=post_id))
    try:
        await db.commit()
    except IntegrityError:
        # Concurrent like won the race; the end state is still "liked".
        await db.rollback()
        return False
    return True


async def unlike_post(db: AsyncSession, user_id: uuid.UUID, post_id: uuid.UUID) -> bool:
    """Remove a like (idempotent). Returns True if a like was removed."""
    result = await db.execute(
        delete(PostLike).where(PostLike.user_id == user_id, PostLike.post_id == post_id)
    )
    await db.commit()
    return bool(result.rowcount)


async def like_count(db: AsyncSession, post_id: uuid.UUID) -> int:
    return int(
        await db.scalar(select(func.count(PostLike.id)).where(PostLike.post_id == post_id)) or 0
    )


async def has_liked(db: AsyncSession, user_id: uuid.UUID, post_id: uuid.UUID) -> bool:
    return (
        await db.execute(
            select(PostLike.id).where(PostLike.user_id == user_id, PostLike.post_id == post_id)
        )
    ).scalar_one_or_none() is not None
