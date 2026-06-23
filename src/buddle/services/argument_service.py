"""Argument service — extraction/persistence + the debate dashboard query.

Two halves:

  extract_and_store()   — called from the post pipeline (after leukocyte
                          passes). Extracts Toulmin-reduced units from the post
                          body, embeds the claims (reusing the content
                          embedding provider), and stores them under each of
                          the post's topic tags. Never breaks a post.
  build_dashboard()     — the /v1/topics/{tag}/debate aggregation. Pulls a
                          topic's claims, clusters them into conversation axes,
                          and for each axis returns {representative claim,
                          pro/con/neutral split, ground/rebuttal counts, recent
                          activity trend}.

The dashboard is the "정리" buddle promises: who is arguing what, with which
grounds, and where each axis is heading.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from buddle.ai.argument import (
    ArgumentKind,
    FlatUnit,
    GraphView,
    OppositionView,
    StanceDistribution,
    build_graph_view,
    build_opposition_view,
    cluster_claims,
    extract_arguments,
    representative_index,
)
from buddle.ai.embeddings import EmbeddingError, get_embedding_provider
from buddle.config import get_settings
from buddle.core.logging import get_logger
from buddle.db.models.argument_unit import ArgumentUnit
from buddle.db.models.enums import ArgumentKindEnum, ArgumentStanceEnum
from buddle.db.models.post import Post
from buddle.db.models.tag import PostTag, Tag

log = get_logger(__name__)

_TREND_WINDOW_DAYS = 7
_MAX_CLAIMS_FOR_DASHBOARD = 200


@dataclass(frozen=True, slots=True)
class AxisView:
    """One conversation axis in the dashboard."""

    representative_claim: str
    representative_post_id: uuid.UUID | None
    claim_count: int
    pro: int
    con: int
    neutral: int
    ground_count: int
    rebuttal_count: int
    recent_claims: int  # claims added in the trend window (where it's heading)


@dataclass(frozen=True, slots=True)
class DashboardView:
    """The full topic debate dashboard."""

    topic_tag_id: uuid.UUID
    total_claims: int
    total_grounds: int
    total_rebuttals: int
    total_questions: int
    axes: list[AxisView] = field(default_factory=list)


async def _embed_many_or_none(texts: list[str]) -> list[list[float]] | None:
    """Batch-embed several texts in one call. None on failure (claims then
    store without embeddings and fall into the residual axis)."""
    if not texts:
        return []
    try:
        provider = get_embedding_provider()
        return await provider.embed(texts)
    except EmbeddingError as e:
        log.warning("argument.embed_batch_failed", error=str(e))
        return None


async def extract_and_store(
    db: AsyncSession,
    *,
    post_id: uuid.UUID,
    content: str,
    tag_ids: list[uuid.UUID],
    commit: bool = True,
) -> int:
    """Extract argument units from a post and store them under each topic tag.

    Claims are embedded (for clustering); grounds/rebuttals/questions are not.
    Returns the number of (unit × tag) rows written. No-op when there are no
    tags (an argument needs a topic to argue under) or extraction is disabled.
    """
    if not get_settings().argument_enabled or not tag_ids:
        return 0

    units = extract_arguments(content)
    if not units:
        return 0

    # Embed all claims in ONE batched call (not one round-trip per claim).
    # Grounds/rebuttals/questions ride along without embeddings.
    claim_indices = [i for i, u in enumerate(units) if u.kind == ArgumentKind.CLAIM]
    claim_embs: dict[int, list[float] | None] = {}
    if claim_indices:
        claim_texts = [units[i].text for i in claim_indices]
        embeddings = await _embed_many_or_none(claim_texts)
        for slot, i in enumerate(claim_indices):
            claim_embs[i] = embeddings[slot] if embeddings is not None else None

    written = 0
    for tag_id in tag_ids:
        for i, u in enumerate(units):
            db.add(
                ArgumentUnit(
                    post_id=post_id,
                    topic_tag_id=tag_id,
                    kind=ArgumentKindEnum(u.kind.value),
                    stance=ArgumentStanceEnum(u.stance.value),
                    text=u.text,
                    emb=claim_embs.get(i),
                )
            )
            written += 1

    if commit:
        await db.commit()
    return written


async def get_or_create_tag(db: AsyncSession, name: str) -> Tag:
    """Get-or-create a topic tag by name (idempotent, used by any caller that
    only has a topic *name* in hand — e.g. a chat's current topic chip —
    rather than an existing tag_id)."""
    tag = (await db.execute(select(Tag).where(Tag.name == name))).scalar_one_or_none()
    if tag is None:
        tag = Tag(name=name)
        db.add(tag)
        await db.flush()
    return tag


@dataclass(frozen=True, slots=True)
class PromoteResult:
    """Outcome of promoting a post into a debate topic seed."""

    tag_id: uuid.UUID
    topic_name: str
    seeded_units: int


async def promote_post_to_topic(
    db: AsyncSession,
    *,
    post: Post,
    topic_name: str | None,
    commit: bool = True,
) -> PromoteResult | None:
    """Promote a post into a debate topic seed (idempotent).

    Gets-or-creates the topic tag, links it to the post if not already linked,
    and extracts the post's argument units under that tag so the post becomes
    the debate's first conversation axis. Returns None if argument mining is
    disabled. Reuses the same tag/extraction path as the post pipeline, so a
    post that already carries the tag (and units) is a no-op for those parts.
    """
    if not get_settings().argument_enabled:
        return None

    # Resolve the topic name: explicit, else the post's first existing tag.
    name = (topic_name or "").strip()
    if not name:
        existing_first = (
            await db.execute(
                select(Tag.name)
                .join(PostTag, PostTag.tag_id == Tag.id)
                .where(PostTag.post_id == post.id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing_first is None:
            return None  # caller turns this into 400 (need a topic name)
        name = existing_first

    # Get-or-create the tag.
    tag = await get_or_create_tag(db, name)

    # Link tag to post if not already linked (idempotent).
    link = (
        await db.execute(
            select(PostTag).where(PostTag.post_id == post.id, PostTag.tag_id == tag.id)
        )
    ).scalar_one_or_none()
    if link is None:
        db.add(PostTag(post_id=post.id, tag_id=tag.id))

    # Seed the debate: extract this post's argument units under the tag, unless
    # they already exist for this (post, tag) pair.
    already = (
        await db.execute(
            select(func.count(ArgumentUnit.id)).where(
                ArgumentUnit.post_id == post.id, ArgumentUnit.topic_tag_id == tag.id
            )
        )
    ).scalar_one()
    seeded = 0
    if int(already) == 0:
        seeded = await extract_and_store(
            db,
            post_id=post.id,
            content=post.content_transformed or "",
            tag_ids=[tag.id],
            commit=False,
        )

    if commit:
        await db.commit()
    return PromoteResult(tag_id=tag.id, topic_name=name, seeded_units=seeded)


async def add_stance_contribution(
    db: AsyncSession,
    *,
    topic_tag_id: uuid.UUID,
    stance: str,
    claim: str,
    grounds: list[str],
    commit: bool = True,
) -> int:
    """Add a user's claim (+ optional grounds) on a chosen side of a topic.

    The claim and each ground become argument_units under the topic tag, so the
    contribution immediately reshapes the opposition geometry and the dashboard.
    The claim is embedded (for clustering); grounds reference the claim via
    parent_unit_id. These units have no source post (post_id is null) — they are
    direct, tag-level contributions. Stance is taken as given (the user picked
    their side explicitly).
    """
    if not get_settings().argument_enabled:
        return 0
    stance_enum = ArgumentStanceEnum(stance)
    embeddings = await _embed_many_or_none([claim])
    claim_emb = embeddings[0] if embeddings else None

    added = 0
    # Claim first.
    claim_unit = ArgumentUnit(
        post_id=None,
        topic_tag_id=topic_tag_id,
        kind=ArgumentKindEnum.CLAIM,
        stance=stance_enum,
        text=claim.strip()[:240],
        emb=claim_emb,
    )
    db.add(claim_unit)
    await db.flush()
    added += 1
    # Grounds reference the claim.
    for g in grounds:
        if not g.strip():
            continue
        db.add(
            ArgumentUnit(
                post_id=None,
                topic_tag_id=topic_tag_id,
                kind=ArgumentKindEnum.GROUND,
                stance=stance_enum,
                text=g.strip()[:240],
                parent_unit_id=claim_unit.id,
            )
        )
        added += 1

    if commit:
        await db.commit()
    return added


async def add_stance_contribution_by_name(
    db: AsyncSession,
    *,
    topic_name: str,
    stance: str,
    claim: str,
    grounds: list[str],
    commit: bool = True,
) -> tuple[uuid.UUID, int]:
    """Same as add_stance_contribution, but get-or-creates the topic tag by
    name first. For callers that only have a topic *name* in hand — chiefly
    "근거로 추가" from inside a chat, where the screen only shows the topic
    chip's display name, never a tag_id."""
    tag = await get_or_create_tag(db, topic_name.strip())
    added = await add_stance_contribution(
        db,
        topic_tag_id=tag.id,
        stance=stance,
        claim=claim,
        grounds=grounds,
        commit=commit,
    )
    return tag.id, added


async def build_opposition(db: AsyncSession, *, topic_tag_id: uuid.UUID) -> OppositionView:
    """Build the geometric opposition view for a topic.

    Derives a 5-level stance distribution from the topic's claims (a claim is
    "strong" when at least one ground from the same post backs it), counts the
    conversation axes and rebuttals, then classifies the opposition shape and
    computes its geometry. Empty topics yield an empty spectrum.
    """
    rows = list(
        (
            await db.execute(
                select(ArgumentUnit)
                .where(ArgumentUnit.topic_tag_id == topic_tag_id)
                .limit(_MAX_CLAIMS_FOR_DASHBOARD * 3)
            )
        )
        .scalars()
        .all()
    )
    claims = [r for r in rows if r.kind == ArgumentKindEnum.CLAIM]
    grounds = [r for r in rows if r.kind == ArgumentKindEnum.GROUND]
    rebuttals = [r for r in rows if r.kind == ArgumentKindEnum.REBUTTAL]

    # Which posts have a ground → their claims count as "strong".
    posts_with_ground = {g.post_id for g in grounds}

    sc = c = nt = pr = spr = 0
    for cl in claims:
        strong = cl.post_id in posts_with_ground
        if cl.stance == ArgumentStanceEnum.PRO:
            if strong:
                spr += 1
            else:
                pr += 1
        elif cl.stance == ArgumentStanceEnum.CON:
            if strong:
                sc += 1
            else:
                c += 1
        else:
            nt += 1

    # Axis count: reuse the dashboard's clustering result size (bounded).
    embedded = [cl for cl in claims if cl.emb is not None]
    axis_count = 1
    if embedded:
        embs = [list(cl.emb) for cl in embedded if cl.emb is not None]
        axis_count = max(1, len(cluster_claims(embs)))

    dist = StanceDistribution(
        strong_con=sc,
        con=c,
        neutral=nt,
        pro=pr,
        strong_pro=spr,
        axis_count=axis_count,
        rebuttal_count=len(rebuttals),
    )
    return build_opposition_view(dist)


async def build_argument_graph(
    db: AsyncSession, *, topic_tag_id: uuid.UUID
) -> GraphView:
    """Build the Kialo-style argument graph for a topic.

    Reads the topic's argument units (claim / ground / rebuttal / question with
    parent_unit_id links) and hands them to the pure graph builder, which
    arranges them as a claim-rooted hierarchy (claim → dimension → ground /
    evidence / rebuttal). Empty topics yield an empty graph.
    """
    rows = list(
        (
            await db.execute(
                select(ArgumentUnit)
                .where(ArgumentUnit.topic_tag_id == topic_tag_id)
                .order_by(ArgumentUnit.created_at.desc())
                .limit(_MAX_CLAIMS_FOR_DASHBOARD * 4)
            )
        )
        .scalars()
        .all()
    )
    flat = [
        FlatUnit(
            id=r.id,
            kind=str(r.kind.value),
            stance=str(r.stance.value),
            text=r.text,
            parent_unit_id=r.parent_unit_id,
        )
        for r in rows
    ]
    return build_graph_view(topic_tag_id, flat)


async def build_dashboard(
    db: AsyncSession, *, topic_tag_id: uuid.UUID, now: datetime | None = None
) -> DashboardView:
    """Aggregate a topic's arguments into the conversation-axis dashboard."""
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=_TREND_WINDOW_DAYS)

    rows = list(
        (
            await db.execute(
                select(ArgumentUnit)
                .where(ArgumentUnit.topic_tag_id == topic_tag_id)
                .order_by(ArgumentUnit.created_at.desc())
                .limit(_MAX_CLAIMS_FOR_DASHBOARD * 3)
            )
        )
        .scalars()
        .all()
    )

    claims = [r for r in rows if r.kind == ArgumentKindEnum.CLAIM]
    grounds = [r for r in rows if r.kind == ArgumentKindEnum.GROUND]
    rebuttals = [r for r in rows if r.kind == ArgumentKindEnum.REBUTTAL]
    questions = [r for r in rows if r.kind == ArgumentKindEnum.QUESTION]

    totals = DashboardView(
        topic_tag_id=topic_tag_id,
        total_claims=len(claims),
        total_grounds=len(grounds),
        total_rebuttals=len(rebuttals),
        total_questions=len(questions),
        axes=[],
    )
    if not claims:
        return totals

    # Cluster claims with embeddings; claims lacking an embedding fall into a
    # single residual axis so they're still represented.
    embedded = [c for c in claims if c.emb is not None]
    unembedded = [c for c in claims if c.emb is None]

    axes: list[AxisView] = []
    if embedded:
        embs = [list(c.emb) for c in embedded if c.emb is not None]
        clusters = cluster_claims(embs)
        for cl in clusters:
            members = [embedded[i] for i in cl.member_indices]
            rep_i = representative_index(cl, embs)
            axes.append(_axis_view(embedded[rep_i], members, grounds, rebuttals, cutoff))

    if unembedded:
        axes.append(_axis_view(unembedded[0], unembedded, grounds, rebuttals, cutoff))

    return DashboardView(
        topic_tag_id=topic_tag_id,
        total_claims=len(claims),
        total_grounds=len(grounds),
        total_rebuttals=len(rebuttals),
        total_questions=len(questions),
        axes=axes,
    )


def _axis_view(
    representative: ArgumentUnit,
    members: list[ArgumentUnit],
    grounds: list[ArgumentUnit],
    rebuttals: list[ArgumentUnit],
    cutoff: datetime,
) -> AxisView:
    """Build one axis summary from its member claims."""
    pro = sum(1 for m in members if m.stance == ArgumentStanceEnum.PRO)
    con = sum(1 for m in members if m.stance == ArgumentStanceEnum.CON)
    neutral = sum(1 for m in members if m.stance == ArgumentStanceEnum.NEUTRAL)
    member_posts = {m.post_id for m in members}
    # Grounds/rebuttals from the same posts as this axis's claims.
    g = sum(1 for x in grounds if x.post_id in member_posts)
    r = sum(1 for x in rebuttals if x.post_id in member_posts)
    recent = sum(1 for m in members if _as_utc(m.created_at) >= cutoff)
    return AxisView(
        representative_claim=representative.text,
        representative_post_id=representative.post_id,
        claim_count=len(members),
        pro=pro,
        con=con,
        neutral=neutral,
        ground_count=g,
        rebuttal_count=r,
        recent_claims=recent,
    )


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
