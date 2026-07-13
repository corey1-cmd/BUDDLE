"""Post routes — /v1/posts (+ reactions: like / report)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from buddle.api.deps import DB, CurrentUser, Redis
from buddle.core.exceptions import PostNotFound, ValidationError
from buddle.db.models.enums import PostVisibility
from buddle.db.models.post import Post
from buddle.schemas.debate import DebateTopicCreated, DebateTopicRequest
from buddle.schemas.post import MyPostsPage, PostCreate, PostRead
from buddle.schemas.reaction import ImportanceView, ReportAck, ReportRequest
from buddle.services import (
    argument_service,
    importance_service,
    leukocyte_service,
    post_service,
)

router = APIRouter(prefix="/posts", tags=["posts"])


@router.post(
    "",
    response_model=PostRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a post via one of your personas",
)
async def create_post(
    payload: PostCreate,
    user: CurrentUser,
    db: DB,
    redis: Redis,
) -> PostRead:
    post = await post_service.create_post(db, user, payload, redis_client=redis)
    return await post_service.get_post_for_owner(db, user, post.id)


@router.get(
    "",
    response_model=MyPostsPage,
    summary="My posts (프로필 목록) — 통계 + 최신순 키셋 페이지",
)
async def list_my_posts(
    user: CurrentUser,
    db: DB,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
) -> MyPostsPage:
    return await post_service.get_my_posts(db, user, cursor=cursor, limit=limit)


@router.get(
    "/{post_id}",
    response_model=PostRead,
    summary="Get a post you authored",
)
async def get_post(
    post_id: uuid.UUID,
    user: CurrentUser,
    db: DB,
) -> PostRead:
    return await post_service.get_post_for_owner(db, user, post_id)


async def _get_public_post(db: DB, post_id: uuid.UUID) -> Post:
    post = await db.get(Post, post_id)
    if not post or post.visibility != PostVisibility.PUBLIC or post.is_suppressed:
        raise PostNotFound()
    return post


@router.post(
    "/{post_id}/react",
    response_model=ImportanceView,
    summary="Like a public post (positive importance signal)",
)
async def react_like(
    post_id: uuid.UUID,
    _: CurrentUser,
    db: DB,
) -> ImportanceView:
    await _get_public_post(db, post_id)
    await leukocyte_service.apply_like(db, post_id, commit=True)
    normalized = await importance_service.get_normalized(db, post_id)
    return ImportanceView(post_id=post_id, normalized_importance=normalized)


@router.post(
    "/{post_id}/report",
    response_model=ReportAck,
    summary="Report a public post (negative importance + ethics alert)",
)
async def report_post(
    post_id: uuid.UUID,
    payload: ReportRequest,
    _: CurrentUser,
    db: DB,
) -> ReportAck:
    await _get_public_post(db, post_id)
    alert = await leukocyte_service.apply_report(db, post_id, reason=payload.reason, commit=True)
    normalized = await importance_service.get_normalized(db, post_id)
    return ReportAck(post_id=post_id, alert_id=alert.id, normalized_importance=normalized)


@router.post(
    "/{post_id}/debate-topic",
    response_model=DebateTopicCreated,
    summary="이 글을 토론 화제로 시작 (글을 토론 씨앗으로 승격)",
)
async def start_debate_from_post(
    post_id: uuid.UUID,
    payload: DebateTopicRequest,
    _: CurrentUser,
    db: DB,
) -> DebateTopicCreated:
    # Only public, non-suppressed posts can seed a debate (404 otherwise).
    post = await _get_public_post(db, post_id)
    result = await argument_service.promote_post_to_topic(
        db, post=post, topic_name=payload.topic_name, commit=True
    )
    if result is None:
        # No topic name and the post has no existing tag to use.
        raise ValidationError("화제 이름이 필요합니다.")
    return DebateTopicCreated(
        tag_id=result.tag_id,
        topic_name=result.topic_name,
        seeded_units=result.seeded_units,
    )
