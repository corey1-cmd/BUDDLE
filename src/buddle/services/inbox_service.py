"""Inbox service — list private distributions delivered to the user's personas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from buddle.core.cursor import decode_cursor, encode_cursor
from buddle.core.exceptions import NotFound
from buddle.db.models.distribution import Distribution
from buddle.db.models.persona import Persona
from buddle.db.models.post import Post
from buddle.db.models.tag import PostTag, Tag
from buddle.db.models.user import User
from buddle.schemas.inbox import InboxItem, InboxPage
from buddle.schemas.post import PersonaBrief, TagName
from buddle.services.persona_service import get_persona


async def _user_persona_ids(db: AsyncSession, user: User) -> list[uuid.UUID]:
    rows = await db.execute(select(Persona.id).where(Persona.user_id == user.id))
    return [r[0] for r in rows.all()]


async def list_inbox(
    db: AsyncSession,
    user: User,
    *,
    persona_id: uuid.UUID | None = None,
    cursor: str | None = None,
    limit: int = 20,
) -> InboxPage:
    """Paginate inbox items by (delivered_at, id) descending.

    If persona_id is given, the caller must own it; otherwise pulls across
    every persona owned by the user.
    """
    limit = max(1, min(limit, 50))

    if persona_id is not None:
        await get_persona(db, user, persona_id)
        target_ids = [persona_id]
    else:
        target_ids = await _user_persona_ids(db, user)
        if not target_ids:
            return InboxPage(items=[], next_cursor=None)

    where_clauses: list[Any] = [Distribution.target_persona_id.in_(target_ids)]

    if cursor:
        payload = decode_cursor(cursor)
        ts_str = payload.get("ts")
        last_id_str = payload.get("id")
        if not ts_str or not last_id_str:
            return InboxPage(items=[], next_cursor=None)
        ts = datetime.fromisoformat(ts_str)
        last_id = uuid.UUID(last_id_str)
        where_clauses.append(
            or_(
                Distribution.delivered_at < ts,
                and_(Distribution.delivered_at == ts, Distribution.id < last_id),
            )
        )

    stmt = (
        select(Distribution)
        .where(*where_clauses)
        .order_by(Distribution.delivered_at.desc(), Distribution.id.desc())
        .limit(limit + 1)
    )
    distributions = list((await db.execute(stmt)).scalars().all())
    has_more = len(distributions) > limit
    page = distributions[:limit]

    items = await _build_inbox_items(db, page)

    next_cursor: str | None = None
    if has_more and page:
        last = page[-1]
        next_cursor = encode_cursor({"ts": last.delivered_at.isoformat(), "id": str(last.id)})

    return InboxPage(items=items, next_cursor=next_cursor)


async def mark_seen(db: AsyncSession, user: User, distribution_id: uuid.UUID) -> None:
    """Mark a distribution as seen by the recipient. Idempotent."""
    target_ids = await _user_persona_ids(db, user)
    if not target_ids:
        raise NotFound("Distribution not found.")

    stmt = select(Distribution).where(
        Distribution.id == distribution_id,
        Distribution.target_persona_id.in_(target_ids),
    )
    dist = (await db.execute(stmt)).scalar_one_or_none()
    if not dist:
        raise NotFound("Distribution not found.")

    if dist.seen_at is None:
        dist.seen_at = datetime.now(tz=dist.delivered_at.tzinfo)
        await db.commit()


async def _build_inbox_items(
    db: AsyncSession, distributions: list[Distribution]
) -> list[InboxItem]:
    if not distributions:
        return []

    post_ids = [d.source_post_id for d in distributions]
    target_persona_ids = list({d.target_persona_id for d in distributions})

    # Posts
    posts_result = await db.execute(select(Post).where(Post.id.in_(post_ids)))
    posts_by_id = {p.id: p for p in posts_result.scalars().all()}

    # Source + target personas
    source_persona_ids = [p.source_persona_id for p in posts_by_id.values() if p.source_persona_id]
    persona_ids_to_load = list({*target_persona_ids, *source_persona_ids})
    persona_map: dict[uuid.UUID, Persona] = {}
    if persona_ids_to_load:
        prs = await db.execute(select(Persona).where(Persona.id.in_(persona_ids_to_load)))
        persona_map = {p.id: p for p in prs.scalars().all()}

    # Tags per post
    tag_rows = await db.execute(
        select(PostTag.post_id, Tag.id, Tag.name)
        .join(Tag, Tag.id == PostTag.tag_id)
        .where(PostTag.post_id.in_(post_ids))
    )
    tags_by_post: dict[uuid.UUID, list[TagName]] = {}
    for post_id, tag_id, tag_name in tag_rows.all():
        tags_by_post.setdefault(post_id, []).append(TagName(id=tag_id, name=tag_name))

    items: list[InboxItem] = []
    for dist in distributions:
        post = posts_by_id.get(dist.source_post_id)
        if not post:
            continue
        target = persona_map.get(dist.target_persona_id)
        if not target:
            continue
        source = persona_map.get(post.source_persona_id) if post.source_persona_id else None
        items.append(
            InboxItem(
                distribution_id=dist.id,
                target_persona=PersonaBrief.model_validate(target),
                source_persona=(PersonaBrief.model_validate(source) if source else None),
                content_transformed=post.content_transformed,
                tags=tags_by_post.get(post.id, []),
                relevance_score=float(dist.relevance_score),
                delivered_at=dist.delivered_at,
                seen_at=dist.seen_at,
            )
        )
    return items
