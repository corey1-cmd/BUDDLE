"""Feedback service — the mediator's plaza→persona feedback loop.

Aggregates recent plaza reactions per topic (tag) and applies bounded,
gated nudges to each persona's topic affinity. "Small amount of precise
feedback only": pure guardrailed math from ai/mediator/feedback.py decides the
tiny step; this service just gathers signals and persists clamped affinities.

It also exposes get_topic_offsets() so the dialogue cognition can fold a small
proactivity offset per topic into a persona's dispositions.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from buddle.ai.mediator.feedback import (
    TopicReactions,
    apply_affinity,
    proactivity_adjustment,
)
from buddle.core.logging import get_logger
from buddle.db.models.ethics_alert import EthicsAlert
from buddle.db.models.importance import ImportanceScore
from buddle.db.models.persona_topic_affinity import PersonaTopicAffinity
from buddle.db.models.post import Post
from buddle.db.models.post_like import PostLike
from buddle.db.models.tag import PostTag, Tag

log = get_logger(__name__)


async def _topic_reactions(
    db: AsyncSession, *, window_days: int = 7, limit_topics: int = 20
) -> list[TopicReactions]:
    """Aggregate per-topic reactions across recent public posts.

    likes/importance are positive endorsement; reports (open ethics alerts) are
    the negative/safety signal. Reads come from Post.read_count.
    """
    window_start = datetime.now(UTC) - timedelta(days=window_days)

    # Per topic: sum reads + normalized importance over recent public posts.
    rows = (
        await db.execute(
            select(
                Tag.name,
                func.coalesce(func.sum(Post.read_count), 0),
                func.coalesce(func.sum(ImportanceScore.normalized), 0.0),
                func.count(func.distinct(Post.id)),
            )
            .join(PostTag, PostTag.tag_id == Tag.id)
            .join(Post, Post.id == PostTag.post_id)
            .join(ImportanceScore, ImportanceScore.post_id == Post.id, isouter=True)
            .where(Post.created_at >= window_start)
            .group_by(Tag.name)
            .order_by(func.count(func.distinct(Post.id)).desc())
            .limit(limit_topics)
        )
    ).all()

    reactions: list[TopicReactions] = []
    for name, reads, importance, _ in rows:
        # Reports per topic: open ethics alerts on posts carrying this tag.
        reports = int(
            await db.scalar(
                select(func.count(func.distinct(EthicsAlert.id)))
                .select_from(EthicsAlert)
                .join(Post, Post.id == EthicsAlert.post_id)
                .join(PostTag, PostTag.post_id == Post.id)
                .join(Tag, Tag.id == PostTag.tag_id)
                .where(Tag.name == name, Post.created_at >= window_start)
            )
            or 0
        )
        # Real likes on posts carrying this topic (explicit endorsement signal,
        # replacing the earlier distribution-count proxy for higher precision).
        likes = int(
            await db.scalar(
                select(func.count(PostLike.id))
                .select_from(PostLike)
                .join(Post, Post.id == PostLike.post_id)
                .join(PostTag, PostTag.post_id == Post.id)
                .join(Tag, Tag.id == PostTag.tag_id)
                .where(Tag.name == name, Post.created_at >= window_start)
            )
            or 0
        )
        reactions.append(
            TopicReactions(
                topic=name,
                reads=int(reads),
                likes=likes,
                reports=reports,
                importance=float(importance),
            )
        )
    return reactions


async def _affinity_row(
    db: AsyncSession, persona_id: uuid.UUID, topic: str
) -> PersonaTopicAffinity:
    row = (
        await db.execute(
            select(PersonaTopicAffinity).where(
                PersonaTopicAffinity.persona_id == persona_id,
                PersonaTopicAffinity.topic == topic,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = PersonaTopicAffinity(persona_id=persona_id, topic=topic, affinity=0.0)
        db.add(row)
    return row


async def update_persona_affinities(
    db: AsyncSession, persona_id: uuid.UUID, *, window_days: int = 7
) -> dict[str, float]:
    """Apply one bounded feedback update to a persona's topic affinities.

    Returns the updated {topic: affinity} for topics that changed. Each topic
    moves by at most MAX_STEP and is clamped to ±AFFINITY_CAP (guardrails).
    """
    reactions = await _topic_reactions(db, window_days=window_days)
    changed: dict[str, float] = {}
    for r in reactions:
        row = await _affinity_row(db, persona_id, r.topic)
        new_val = apply_affinity(row.affinity, r)
        if new_val != row.affinity:
            row.affinity = new_val
            row.updated_at = datetime.now(UTC)
            changed[r.topic] = new_val
    if changed:
        await db.commit()
    log.info("feedback.affinity_update", persona_id=str(persona_id), changed=len(changed))
    return changed


async def get_topic_offsets(db: AsyncSession, persona_id: uuid.UUID) -> dict[str, float]:
    """Per-topic proactivity offsets for this persona's dialogue cognition.

    Maps stored affinities to small proactivity offsets (≈ ±0.1). Topics with
    zero affinity are omitted.
    """
    rows = (
        await db.execute(
            select(PersonaTopicAffinity).where(PersonaTopicAffinity.persona_id == persona_id)
        )
    ).scalars()
    offsets: dict[str, float] = {}
    for row in rows:
        if row.affinity != 0.0:
            offsets[row.topic] = proactivity_adjustment(row.affinity)
    return offsets
