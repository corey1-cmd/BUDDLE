"""Post service — creates posts via persona+mediator stubs and serves the feed."""

from __future__ import annotations

import contextlib
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from buddle.ai.mediator import MediatorService
from buddle.ai.personas import PersonaService
from buddle.core import metrics
from buddle.core.cursor import decode_cursor, encode_cursor
from buddle.core.exceptions import PostNotFound
from buddle.core.logging import get_logger
from buddle.core.types import RedisClient
from buddle.db.models.comment import Comment
from buddle.db.models.distribution import Distribution
from buddle.db.models.enums import AIRole, PostVisibility, TransformationTypeEnum
from buddle.db.models.importance import ImportanceScore
from buddle.db.models.persona import Persona
from buddle.db.models.post import Post
from buddle.db.models.post_like import PostLike
from buddle.db.models.tag import PostTag, Tag
from buddle.db.models.user import User
from buddle.schemas.post import (
    FeedPage,
    MyPostItem,
    MyPostsPage,
    PersonaBrief,
    PostCreate,
    PostFeedItem,
    PostRead,
    TagName,
)
from buddle.services import argument_service, profile_service, translation_service
from buddle.services.leukocyte_service import apply_mention, assess_post
from buddle.services.mediator_policy_service import get_policy_values
from buddle.services.persona_service import get_persona
from buddle.services.session_service import touch_session
from buddle.services.technician_service import record_transformation

log = get_logger(__name__)

# ── Create ─────────────────────────────────────────────────────────────


async def _ingest_post(
    db: AsyncSession,
    post: Post,
    *,
    distribute_from_persona_id: uuid.UUID | None,
) -> int:
    """Shared ingestion pipeline for ANY public-plaza post (human, persona-AI,
    or external-AI). Runs the leukocyte ethics gate and the mediator
    (tag/restructure/embed/distribute). The post must already be added + flushed
    so it has an id. Returns the distribution count.

    Centralizing this guarantees every author kind passes the SAME ethics and
    mediator gates — no author can bypass them.
    """
    db.add(ImportanceScore(post_id=post.id, raw_score=0.0, normalized=0.0))

    # Leukocyte: ethics assessment on the raw authored content.
    leuko = await assess_post(db, post.id, post.content_raw, commit=False)
    if leuko.should_suppress:
        post.is_suppressed = True

    # Mediator: tag + restructure + embed.
    policy = await get_policy_values(db)
    mediator = MediatorService(db, policy)
    tagging = await mediator.tag_and_restructure(
        content_transformed=post.content_transformed,
        existing_tags=[],
    )
    if tagging.content_embedding is not None:
        post.content_emb = tagging.content_embedding
        # Interest centroid (profile layer): reuse this embedding — zero extra
        # embed calls. Suppressed content must not shape interests; virtual
        # (user-less) personas resolve to None and skip naturally.
        if not post.is_suppressed and post.source_persona_id is not None:
            owner_id = (
                await db.execute(
                    select(Persona.user_id).where(
                        Persona.id == post.source_persona_id,
                        Persona.is_virtual.is_(False),  # 광장 가상 페르소나 제외
                    )
                )
            ).scalar_one_or_none()
            if owner_id is not None:
                try:
                    await profile_service.observe_interest_embedding(
                        db,
                        user_id=owner_id,
                        embedding=list(tagging.content_embedding),
                        commit=False,
                    )
                except Exception as e:  # profiling must never break a post
                    log.warning("profile.interest_observe_failed", error=str(e))
    if tagging.tag_names:
        tag_ids = await _attach_tags(db, post.id, tagging.tag_names)
        # Argument extraction (debate dashboard): only for visible posts —
        # suppressed content must not seed the dashboard. Same atomic
        # transaction (commit=False); failure never blocks the post.
        if not post.is_suppressed and tag_ids:
            try:
                await argument_service.extract_and_store(
                    db,
                    post_id=post.id,
                    content=post.content_transformed,
                    tag_ids=tag_ids,
                    commit=False,
                )
            except Exception as e:  # argument mining must never break a post
                log.warning("argument.extract_failed", error=str(e))

    # Distribution only applies to private persona posts (existing behavior).
    distribution_count = 0
    if (
        distribute_from_persona_id is not None
        and post.visibility == PostVisibility.PRIVATE
        and not post.is_suppressed
    ):
        targets = await mediator.select_distribution_targets(
            source_persona_id=distribute_from_persona_id,
            content_transformed=post.content_transformed,
            tag_names=tagging.tag_names,
            content_embedding=tagging.content_embedding,
        )
        for tgt in targets:
            db.add(
                Distribution(
                    source_post_id=post.id,
                    target_persona_id=tgt.target_persona_id,
                    relevance_score=tgt.relevance_score,
                )
            )
            distribution_count += 1
        for _ in range(distribution_count):
            await apply_mention(db, post.id, commit=False)
        if distribution_count > 0:
            await record_transformation(
                db,
                source_ai=AIRole.MEDIATOR,
                target_data_id=post.id,
                target_data_type="post",
                magnitude=float(distribution_count),
                transformation_type=TransformationTypeEnum.INJECT,
                verified=True,
                commit=False,
            )
    return distribution_count


async def create_post(
    db: AsyncSession,
    user: User,
    payload: PostCreate,
    *,
    redis_client: RedisClient | None = None,
) -> Post:
    """Run the full pipeline: persona transform -> persist -> mediator tag -> distribute."""

    # 1. Persona ownership + transform (via factory: real backend or fallback to stub)
    persona = await get_persona(db, user, payload.persona_id)
    persona_ai = PersonaService(db, redis_client)
    persona_result = await persona_ai.interpret(
        persona_name=persona.name,
        model_key=persona.model_key,
        content_raw=payload.content_raw,
    )
    _record_inference_metric(persona_result.metadata)

    # 2. Persist post + zero-initialized importance
    post = Post(
        source_persona_id=persona.id,
        content_raw=payload.content_raw,
        content_transformed=persona_result.content_transformed,
        visibility=payload.visibility,
        source_language=persona.preferred_language,
    )
    db.add(post)
    await db.flush()

    # 3-5. Shared ingestion (leukocyte + mediator + distribution).
    distribution_count = await _ingest_post(db, post, distribute_from_persona_id=persona.id)

    await db.commit()
    await db.refresh(post)

    # Multilingual: produce other-language versions so the mediator can deliver
    # each recipient the post in their language (best-effort; source always ok).
    with contextlib.suppress(Exception):
        await translation_service.translate_post(db, post.id)

    # Layer B: consider the post for the knowledge reorganization space. Pure
    # selection gate decides retain-vs-let-pass; best-effort, never blocks
    # publishing, never mutates post state.
    with contextlib.suppress(Exception):
        from buddle.services import knowledge_service

        await knowledge_service.consider_post(db, post.id)

    metrics.post_created_total.labels(visibility=payload.visibility.value).inc()
    for _ in range(distribution_count):
        metrics.distribution_created_total.inc()

    # Record this as user activity for engagement/session metrics (best-effort).
    await touch_session(db, user.id)

    return post


def _record_inference_metric(metadata: dict[str, str]) -> None:
    """Map persona interpretation metadata to the inference counter."""
    backend = metadata.get("backend", "stub")
    if metadata.get("cache_hit") == "true":
        outcome = "cache_hit"
    elif metadata.get("stub") == "true" and backend != "stub":
        outcome = "fallback"
    else:
        outcome = "ok"
    metrics.persona_inference_total.labels(backend=backend, outcome=outcome).inc()


async def _attach_tags(db: AsyncSession, post_id: uuid.UUID, names: list[str]) -> list[uuid.UUID]:
    """Get-or-create tags by name and link them to the post. Returns tag IDs."""
    # Look up existing tags
    existing = await db.execute(select(Tag).where(Tag.name.in_(names)))
    existing_by_name = {t.name: t for t in existing.scalars().all()}

    to_create = [n for n in names if n not in existing_by_name]
    new_tags: list[Tag] = []
    for n in to_create:
        t = Tag(name=n)
        db.add(t)
        new_tags.append(t)
    if new_tags:
        await db.flush()  # populate IDs

    all_by_name = {**existing_by_name, **{t.name: t for t in new_tags}}
    tag_ids: list[uuid.UUID] = []
    for n in names:
        tag = all_by_name[n]
        db.add(PostTag(post_id=post_id, tag_id=tag.id))
        tag_ids.append(tag.id)
    return tag_ids


# ── Read single ────────────────────────────────────────────────────────


async def get_post_for_owner(db: AsyncSession, user: User, post_id: uuid.UUID) -> PostRead:
    """Fetch a post owned by the user (via persona). Raises if not found/owned."""
    post = (await db.execute(select(Post).where(Post.id == post_id))).scalar_one_or_none()
    if not post:
        raise PostNotFound()

    persona = None
    if post.source_persona_id:
        persona = (
            await db.execute(select(Persona).where(Persona.id == post.source_persona_id))
        ).scalar_one_or_none()
        if not persona or persona.user_id != user.id:
            raise PostNotFound()

    tags = await _post_tags(db, post.id)
    return PostRead(
        id=post.id,
        source_persona=PersonaBrief.model_validate(persona) if persona else None,
        content_raw=post.content_raw,
        content_transformed=post.content_transformed,
        visibility=post.visibility,
        is_suppressed=post.is_suppressed,
        tags=tags,
        created_at=post.created_at,
    )


async def _post_tags(db: AsyncSession, post_id: uuid.UUID) -> list[TagName]:
    rows = await db.execute(
        select(Tag).join(PostTag, PostTag.tag_id == Tag.id).where(PostTag.post_id == post_id)
    )
    return [TagName(id=t.id, name=t.name) for t in rows.scalars().all()]


# ── Feed ───────────────────────────────────────────────────────────────


async def get_feed(
    db: AsyncSession,
    *,
    cursor: str | None,
    limit: int,
    tag: str | None = None,
    q: str | None = None,
) -> FeedPage:
    """Public feed paginated by (created_at, id) descending.

    Excludes leukocyte-suppressed posts. Each item carries its normalized
    importance; clients/UI may re-rank within a page. (A fully
    importance-ranked cursor is a follow-up: it requires a score-based cursor
    rather than the time-based one used here.)

    ``tag`` filters to posts carrying that exact tag name (server-side). This
    must live in the query — not the client — because client-side filtering of
    a cursor page silently drops matches that fall on later pages, breaking
    both pagination and the "더 보기" button.

    ``q`` is a case-insensitive substring search over the published text
    (content_transformed only — content_raw stays private to the author).
    Same server-side rationale as ``tag``; composes with cursor and tag.
    """
    limit = max(1, min(limit, 50))

    where_clauses: list[Any] = [
        Post.visibility == PostVisibility.PUBLIC,
        Post.is_suppressed.is_(False),
    ]

    if cursor:
        payload = decode_cursor(cursor)
        ts_str = payload.get("ts")
        last_id_str = payload.get("id")
        if not ts_str or not last_id_str:
            raise PostNotFound()  # treat malformed cursor as no more items
        ts = datetime.fromisoformat(ts_str)
        last_id = uuid.UUID(last_id_str)
        where_clauses.append(
            or_(
                Post.created_at < ts,
                and_(Post.created_at == ts, Post.id < last_id),
            )
        )

    if q:
        # ILIKE with escaped wildcards so a user-supplied % or _ can't change
        # match semantics (same escaping as the tags router).
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where_clauses.append(Post.content_transformed.ilike(f"%{escaped}%", escape="\\"))

    stmt = select(Post).where(*where_clauses)

    if tag:
        # Restrict to posts tagged with this exact name. EXISTS keeps it a
        # single row per post (no fan-out join duplicates) and composes
        # cleanly with the keyset cursor above.
        tag_exists = (
            select(PostTag.post_id)
            .join(Tag, Tag.id == PostTag.tag_id)
            .where(PostTag.post_id == Post.id, Tag.name == tag)
        )
        stmt = stmt.where(tag_exists.exists())

    stmt = stmt.order_by(Post.created_at.desc(), Post.id.desc()).limit(limit + 1)
    rows = (await db.execute(stmt)).scalars().all()

    has_more = len(rows) > limit
    page_rows = list(rows[:limit])

    # Prefetch personas + tags + importance for page
    items = await _feed_items_for_posts(db, page_rows)

    next_cursor: str | None = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor({"ts": last.created_at.isoformat(), "id": str(last.id)})

    return FeedPage(items=items, next_cursor=next_cursor)


async def get_my_posts(
    db: AsyncSession,
    user: User,
    *,
    cursor: str | None,
    limit: int,
) -> MyPostsPage:
    """소유자 프로필의 글 목록 — 인스타식 헤더 통계 + 한 줄 카드용 데이터.

    내 페르소나가 작성한 모든 글(비공개·억제 포함 — 자기 글은 자기에게 항상
    보인다)을 (created_at, id) 키셋 커서로 최신순 페이지네이션하고, 글별
    좋아요·댓글 수와 전체 합계(게시물·받은 좋아요·받은 댓글)를 동반한다.
    """
    limit = max(1, min(limit, 50))
    my_persona_ids = select(Persona.id).where(Persona.user_id == user.id)

    where_clauses: list[Any] = [Post.source_persona_id.in_(my_persona_ids)]
    if cursor:
        payload = decode_cursor(cursor)
        ts_str = payload.get("ts")
        last_id_str = payload.get("id")
        if not ts_str or not last_id_str:
            raise PostNotFound()
        ts = datetime.fromisoformat(ts_str)
        last_id = uuid.UUID(last_id_str)
        where_clauses.append(
            or_(Post.created_at < ts, and_(Post.created_at == ts, Post.id < last_id))
        )

    rows = (
        (
            await db.execute(
                select(Post)
                .where(*where_clauses)
                .order_by(Post.created_at.desc(), Post.id.desc())
                .limit(limit + 1)
            )
        )
        .scalars()
        .all()
    )
    has_more = len(rows) > limit
    page_rows = list(rows[:limit])
    post_ids = [p.id for p in page_rows]

    # 글별 카운트 + 태그 + 페르소나 (페이지 범위만)
    like_map: dict[uuid.UUID, int] = {}
    comment_map: dict[uuid.UUID, int] = {}
    tags_by_post: dict[uuid.UUID, list[TagName]] = {}
    persona_map: dict[uuid.UUID, Persona] = {}
    if post_ids:
        for pid, n in (
            await db.execute(
                select(PostLike.post_id, func.count())
                .where(PostLike.post_id.in_(post_ids))
                .group_by(PostLike.post_id)
            )
        ).all():
            like_map[pid] = int(n)
        for pid, n in (
            await db.execute(
                select(Comment.post_id, func.count())
                .where(Comment.post_id.in_(post_ids))
                .group_by(Comment.post_id)
            )
        ).all():
            comment_map[pid] = int(n)
        for pid, tag_id, tag_name in (
            await db.execute(
                select(PostTag.post_id, Tag.id, Tag.name)
                .join(Tag, Tag.id == PostTag.tag_id)
                .where(PostTag.post_id.in_(post_ids))
            )
        ).all():
            tags_by_post.setdefault(pid, []).append(TagName(id=tag_id, name=tag_name))
        persona_ids = [p.source_persona_id for p in page_rows if p.source_persona_id]
        if persona_ids:
            prs = await db.execute(select(Persona).where(Persona.id.in_(persona_ids)))
            persona_map = {p.id: p for p in prs.scalars().all()}

    # 헤더 통계 — 전체 합계(페이지가 아니라 프로필 전체 기준)
    post_count = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Post)
                .where(Post.source_persona_id.in_(my_persona_ids))
            )
        ).scalar_one()
    )
    like_total = int(
        (
            await db.execute(
                select(func.count())
                .select_from(PostLike)
                .join(Post, Post.id == PostLike.post_id)
                .where(Post.source_persona_id.in_(my_persona_ids))
            )
        ).scalar_one()
    )
    comment_total = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Comment)
                .join(Post, Post.id == Comment.post_id)
                .where(Post.source_persona_id.in_(my_persona_ids))
            )
        ).scalar_one()
    )

    next_cursor: str | None = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor({"ts": last.created_at.isoformat(), "id": str(last.id)})

    return MyPostsPage(
        items=[
            MyPostItem(
                id=p.id,
                source_persona=(
                    PersonaBrief.model_validate(persona_map[p.source_persona_id])
                    if p.source_persona_id and p.source_persona_id in persona_map
                    else None
                ),
                content_transformed=p.content_transformed,
                visibility=p.visibility,
                is_suppressed=p.is_suppressed,
                tags=tags_by_post.get(p.id, []),
                like_count=like_map.get(p.id, 0),
                comment_count=comment_map.get(p.id, 0),
                created_at=p.created_at,
            )
            for p in page_rows
        ],
        next_cursor=next_cursor,
        post_count=post_count,
        like_count=like_total,
        comment_count=comment_total,
    )


async def _feed_items_for_posts(db: AsyncSession, posts: list[Post]) -> list[PostFeedItem]:
    if not posts:
        return []

    post_ids = [p.id for p in posts]
    persona_ids = [p.source_persona_id for p in posts if p.source_persona_id]

    # Personas
    persona_map: dict[uuid.UUID, Persona] = {}
    if persona_ids:
        prs = await db.execute(select(Persona).where(Persona.id.in_(persona_ids)))
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

    # Importance per post
    imp_rows = await db.execute(
        select(ImportanceScore.post_id, ImportanceScore.normalized).where(
            ImportanceScore.post_id.in_(post_ids)
        )
    )
    importance_map = {pid: float(norm) for pid, norm in imp_rows.all()}

    # 카드 하단 '주요 주장'(≤3) — 글에서 추출된 claim(추출 순서 유지).
    # 본문에 그대로 들어 있는 문장(추출이 원문을 복사한 메아리)은 거른다:
    # 본문 반복은 주장이 아니라 소음이고, 사용자 방침은 "없으면 그냥 없게"다.
    from buddle.db.models.argument_unit import ArgumentUnit
    from buddle.db.models.enums import ArgumentKindEnum

    claim_rows = await db.execute(
        select(ArgumentUnit.post_id, ArgumentUnit.text)
        .where(
            ArgumentUnit.post_id.in_(post_ids),
            ArgumentUnit.kind == ArgumentKindEnum.CLAIM,
        )
        .order_by(ArgumentUnit.created_at.asc())
    )
    raw_claims: dict[uuid.UUID, list[str]] = {}
    for pid, text in claim_rows.all():
        lst = raw_claims.setdefault(pid, [])
        if text and text not in lst:
            lst.append(text)
    body_by_post = {p.id: (p.content_transformed or "") for p in posts}
    claims_by_post: dict[uuid.UUID, list[str]] = {}
    for pid, texts in raw_claims.items():
        kept = [c for c in texts if c not in body_by_post.get(pid, "")][:3]
        if kept:
            claims_by_post[pid] = kept

    # 화제 글('지금 화제')은 자체 추출이 없다 — 그 태그 아래 토론에서 나온
    # 최근 claim을 폴백으로 붙인다. 일반 글엔 폴백을 쓰지 않는다(남의 글
    # 주장이 섞이는 소음 방지). 그것도 없으면 빈 리스트(카드에 아무것도 없음).
    topic_posts = [p for p in posts if p.author_label == "지금 화제"]
    fallback_tag_ids = {
        t.id
        for p in topic_posts
        if p.id not in claims_by_post
        for t in tags_by_post.get(p.id, [])
        if t.id is not None
    }
    claims_by_tag: dict[uuid.UUID, list[str]] = {}
    if fallback_tag_ids:
        tag_claim_rows = await db.execute(
            select(ArgumentUnit.topic_tag_id, ArgumentUnit.text)
            .where(
                ArgumentUnit.topic_tag_id.in_(fallback_tag_ids),
                ArgumentUnit.kind == ArgumentKindEnum.CLAIM,
            )
            .order_by(ArgumentUnit.created_at.desc())
        )
        for tid, text in tag_claim_rows.all():
            lst = claims_by_tag.setdefault(tid, [])
            if text and text not in lst and len(lst) < 3:
                lst.append(text)

    def _claims_for(p: Post) -> list[str]:
        own = claims_by_post.get(p.id)
        if own:
            return own
        if p.author_label != "지금 화제":
            return []
        body = body_by_post.get(p.id, "")
        for t in tags_by_post.get(p.id, []):
            if t.id is None:
                continue
            cand = [c for c in claims_by_tag.get(t.id, []) if c not in body]
            if cand:
                return cand[:3]
        return []

    return [
        PostFeedItem(
            id=p.id,
            source_persona=(
                PersonaBrief.model_validate(persona_map[p.source_persona_id])
                if p.source_persona_id and p.source_persona_id in persona_map
                else None
            ),
            author_label=p.author_label,
            content_transformed=p.content_transformed,
            tags=tags_by_post.get(p.id, []),
            importance=importance_map.get(p.id, 0.0),
            created_at=p.created_at,
            claims=_claims_for(p),
        )
        for p in posts
    ]
