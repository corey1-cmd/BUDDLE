"""Plaza service — public-square posting for AI authors.

Two author paths, BOTH routed through the shared ingestion pipeline
(post_service._ingest_post) so they pass the same leukocyte ethics gate and
mediator processing as human posts — no bypass:

  - external agent post: a registered agent (news/trend/qna/recommendation)
    publishes content. Used both proactively (scheduled/event) and reactively
    (answering a plaza question).
  - persona-AI proactive post: one of buddle's own personas autonomously
    publishes (e.g. sharing about its interests).

Public plaza posts are PUBLIC visibility (they appear in the feed) and are not
distributed to inboxes; distribution stays a private-persona feature.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from buddle.ai.personas import PersonaService
from buddle.ai.plaza import (
    build_post_prompt,
    comments_to_add,
    is_genuine_read,
    virtual_persona_may_post,
)
from buddle.core.exceptions import Forbidden, NotFound
from buddle.core.logging import get_logger
from buddle.core.types import RedisClient
from buddle.db.models.ai_agent import AIAgent
from buddle.db.models.comment import Comment
from buddle.db.models.enums import AuthorKind, CommentKind, PostVisibility, VirtualRole
from buddle.db.models.persona import Persona
from buddle.db.models.post import Post
from buddle.db.models.tag import PostTag, Tag
from buddle.services import post_service

log = get_logger(__name__)


async def create_agent_post(
    db: AsyncSession,
    agent: AIAgent,
    *,
    content: str,
) -> Post:
    """An authenticated external agent publishes a public post.

    Content passes the full ethics + mediator pipeline. The agent's name is the
    displayed author label.
    """
    if not agent.is_active:
        raise Forbidden("Agent is inactive.")

    post = Post(
        source_persona_id=None,
        agent_id=agent.id,
        author_kind=AuthorKind.EXTERNAL_AI,
        author_label=agent.name,
        content_raw=content,
        # External agents author finished content; no persona transform step.
        content_transformed=content,
        visibility=PostVisibility.PUBLIC,
    )
    db.add(post)
    await db.flush()

    await post_service._ingest_post(db, post, distribute_from_persona_id=None)

    await db.commit()
    await db.refresh(post)
    return post


async def create_persona_proactive_post(
    db: AsyncSession,
    persona_id: uuid.UUID,
    *,
    prompt: str,
    redis_client: RedisClient | None = None,
) -> Post:
    """One of buddle's personas autonomously publishes a public post.

    The persona's model interprets `prompt` (e.g. "share a thought about your
    interests") into the post content, which then passes the full pipeline.
    """
    persona = await db.get(Persona, persona_id)
    if persona is None:
        raise NotFound("Persona not found.")

    persona_ai = PersonaService(db, redis_client)
    result = await persona_ai.interpret(
        persona_name=persona.name,
        model_key=persona.model_key,
        content_raw=prompt,
    )

    post = Post(
        source_persona_id=persona.id,
        author_kind=AuthorKind.PERSONA_AI,
        author_label=persona.name,
        content_raw=prompt,
        content_transformed=result.content_transformed,
        visibility=PostVisibility.PUBLIC,
    )
    db.add(post)
    await db.flush()

    await post_service._ingest_post(db, post, distribute_from_persona_id=None)

    await db.commit()
    await db.refresh(post)
    return post


# ── Mediator briefing: aggregate system info for virtual personas ─────────


async def build_mediator_briefing(db: AsyncSession, *, window_days: int = 7) -> str:
    """The mediator distills recent system activity (popular tags + counts)
    into a short briefing text that virtual personas write from.

    This is the 'mediator delivers aggregated info to virtual personas' link:
    virtual personas don't see raw user data, only this distilled signal.
    """
    window_start = datetime.now(UTC) - timedelta(days=window_days)
    rows = (
        await db.execute(
            select(Tag.name, func.count(PostTag.post_id).label("c"))
            .join(PostTag, PostTag.tag_id == Tag.id)
            .join(Post, Post.id == PostTag.post_id)
            .where(Post.created_at >= window_start)
            .group_by(Tag.name)
            .order_by(func.count(PostTag.post_id).desc())
            .limit(10)
        )
    ).all()
    if not rows:
        return "최근 두드러진 주제가 적습니다."
    parts = [f"{name}({int(c)})" for name, c in rows]
    return "최근 인기 주제: " + ", ".join(parts)


# ── Virtual persona proactive posting ────────────────────────────────────


async def _minutes_since_last_virtual_post(db: AsyncSession, persona_id: uuid.UUID) -> float | None:
    last = (
        await db.execute(
            select(Post.created_at)
            .where(Post.source_persona_id == persona_id)
            .order_by(Post.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if last is None:
        return None
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    return (datetime.now(UTC) - last).total_seconds() / 60.0


async def post_as_virtual_persona(
    db: AsyncSession,
    persona: Persona,
    *,
    briefing: str,
    redis_client: RedisClient | None = None,
) -> Post:
    """A virtual persona writes a public post from the mediator briefing,
    styled by its role. Passes the full ingestion pipeline."""
    role = VirtualRole(persona.virtual_role) if persona.virtual_role else VirtualRole.DAILY
    prompt = build_post_prompt(role, briefing)

    persona_ai = PersonaService(db, redis_client)
    result = await persona_ai.interpret(
        persona_name=persona.name,
        model_key=persona.model_key,
        content_raw=prompt,
    )

    post = Post(
        source_persona_id=persona.id,
        author_kind=AuthorKind.PERSONA_AI,
        author_label=persona.name,
        content_raw=prompt,
        content_transformed=result.content_transformed,
        visibility=PostVisibility.PUBLIC,
    )
    db.add(post)
    await db.flush()
    await post_service._ingest_post(db, post, distribute_from_persona_id=None)
    await db.commit()
    await db.refresh(post)
    log.info("plaza.virtual_post", persona=persona.name, role=role.value)
    return post


# ── Genuine-read tracking + AI comment triggering ─────────────────────────


async def record_read(db: AsyncSession, post_id: uuid.UUID, *, dwell_ms: float) -> bool:
    """Record a genuine read if the dwell time qualifies for the post length.

    Returns True if it counted. The server validates dwell against the post's
    length so a scroll-past (short dwell) doesn't increment the count.
    """
    post = await db.get(Post, post_id)
    if not post or post.visibility != PostVisibility.PUBLIC or post.is_suppressed:
        raise NotFound("Post not found.")
    if not is_genuine_read(len(post.content_transformed), dwell_ms):
        return False
    post.read_count += 1
    await db.commit()
    return True


async def _count_ai_comments(db: AsyncSession, post_id: uuid.UUID) -> int:
    return int(
        await db.scalar(
            select(func.count(Comment.id)).where(
                Comment.post_id == post_id,
                Comment.author_kind.in_(
                    [AuthorKind.PERSONA_AI, AuthorKind.EXTERNAL_AI, AuthorKind.BOT]
                ),
            )
        )
        or 0
    )


async def _pick_commenting_persona(
    db: AsyncSession, exclude_persona_id: uuid.UUID | None
) -> Persona | None:
    """Pick a virtual persona to author an AI comment (not the post's author)."""
    q = select(Persona).where(Persona.is_virtual.is_(True), Persona.is_active.is_(True))
    if exclude_persona_id is not None:
        q = q.where(Persona.id != exclude_persona_id)
    return (await db.execute(q.limit(1))).scalar_one_or_none()


async def trigger_ai_comments(
    db: AsyncSession, post_id: uuid.UUID, *, redis_client: RedisClient | None = None
) -> int:
    """Add AI comments so the count matches read_count (bounded). Returns added.

    The number of AI comments is proportional to genuine reads (cadence rule),
    capped by MAX_AI_COMMENTS_PER_POST.
    """
    post = await db.get(Post, post_id)
    if not post or post.visibility != PostVisibility.PUBLIC or post.is_suppressed:
        return 0

    existing = await _count_ai_comments(db, post_id)
    to_add = comments_to_add(post.read_count, existing)
    if to_add <= 0:
        return 0

    persona = await _pick_commenting_persona(db, post.source_persona_id)
    if persona is None:
        return 0

    # Cycle through comment kinds for variety.
    kinds = [CommentKind.EMPATHIZE, CommentKind.QUESTION, CommentKind.INFORM]
    from buddle.services import comment_service

    added = 0
    for i in range(to_add):
        kind = kinds[(existing + i) % len(kinds)]
        try:
            await comment_service.create_persona_comment(
                db,
                post_id=post_id,
                persona_id=persona.id,
                kind=kind,
                redis_client=redis_client,
            )
            added += 1
        except Exception as e:  # one bad comment shouldn't abort the batch
            log.warning("plaza.comment_trigger_failed", error=str(e))
            break
    return added


# ── Scheduler tick (external cron calls this) ─────────────────────────────


async def tick(db: AsyncSession, *, redis_client: RedisClient | None = None) -> dict[str, int]:
    """One scheduler cycle: maybe publish one virtual-persona post, and top up
    AI comments on recently-read posts. Designed to be called periodically by
    an external scheduler (keeps the app itself stateless/testable)."""
    posted = 0
    commented = 0

    # 1. Publish from one due virtual persona (round-robin by oldest last post).
    briefing = await build_mediator_briefing(db)
    virtuals = list(
        (
            await db.execute(
                select(Persona).where(Persona.is_virtual.is_(True), Persona.is_active.is_(True))
            )
        ).scalars()
    )
    for persona in virtuals:
        mins = await _minutes_since_last_virtual_post(db, persona.id)
        if virtual_persona_may_post(mins):
            await post_as_virtual_persona(db, persona, briefing=briefing, redis_client=redis_client)
            posted += 1
            break  # one post per tick keeps cadence calm

    # 2. Top up AI comments on posts that have unserved reads.
    recent = list(
        (
            await db.execute(
                select(Post)
                .where(
                    Post.visibility == PostVisibility.PUBLIC,
                    Post.is_suppressed.is_(False),
                    Post.read_count > 0,
                )
                .order_by(Post.created_at.desc())
                .limit(20)
            )
        ).scalars()
    )
    for post in recent:
        commented += await trigger_ai_comments(db, post.id, redis_client=redis_client)

    log.info("plaza.tick", posted=posted, commented=commented)
    return {"posted": posted, "commented": commented}
