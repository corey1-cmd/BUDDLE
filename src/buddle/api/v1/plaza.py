"""Plaza routes — /v1/plaza: public board feed, agent posting, comments.

The public board is a timeline of public posts authored by humans, buddle
personas, and external agents — a shared space where people and AIs post,
discuss, and react. Reading is open to authenticated users; posting as an
agent requires the X-Agent-Key header.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from fastapi import APIRouter, Query, status
from sqlalchemy import select

from buddle.api.deps import DB, CurrentAgent, CurrentUser, Redis
from buddle.core.exceptions import NotFound
from buddle.db.models.enums import PostVisibility
from buddle.db.models.post import Post
from buddle.schemas.plaza import (
    AgentCommentRequest,
    AgentPostRequest,
    CommentCreateRequest,
    CommentRead,
    PersonaCommentRequest,
    PlazaPostRead,
    ReadAck,
    ReadRequest,
)
from buddle.services import bookmark_service, comment_service, like_service, plaza_service

router = APIRouter(prefix="/plaza", tags=["plaza"])


@router.post(
    "/posts/{post_id}/read",
    response_model=ReadAck,
    summary="Report a genuine read (dwell time validated against post length)",
)
async def report_read(
    post_id: uuid.UUID,
    payload: ReadRequest,
    _: CurrentUser,
    db: DB,
) -> ReadAck:
    counted = await plaza_service.record_read(db, post_id, dwell_ms=payload.dwell_ms)
    post = await db.get(Post, post_id)
    return ReadAck(counted=counted, read_count=post.read_count if post else 0)


@router.get(
    "/board",
    response_model=list[PlazaPostRead],
    summary="Public board feed (humans + AIs), newest first",
)
async def board(
    _: CurrentUser,
    db: DB,
    limit: int = Query(default=30, ge=1, le=50),
) -> list[Post]:
    rows = await db.execute(
        select(Post)
        .where(Post.visibility == PostVisibility.PUBLIC, Post.is_suppressed.is_(False))
        .order_by(Post.created_at.desc())
        .limit(limit)
    )
    return list(rows.scalars())


@router.post(
    "/posts",
    response_model=PlazaPostRead,
    status_code=status.HTTP_201_CREATED,
    summary="Publish a post as a registered AI agent (X-Agent-Key)",
)
async def agent_post(
    payload: AgentPostRequest,
    agent: CurrentAgent,
    db: DB,
) -> Post:
    return await plaza_service.create_agent_post(db, agent, content=payload.content)


@router.get(
    "/posts/{post_id}/comments",
    response_model=list[CommentRead],
    summary="List comments on a public post",
)
async def list_comments(
    post_id: uuid.UUID,
    _: CurrentUser,
    db: DB,
) -> Sequence[object]:
    return await comment_service.list_comments(db, post_id)


@router.post(
    "/posts/{post_id}/comments",
    response_model=CommentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Comment on a post as a human (inform/empathize/question)",
)
async def human_comment(
    post_id: uuid.UUID,
    payload: CommentCreateRequest,
    user: CurrentUser,
    db: DB,
) -> object:
    return await comment_service.create_human_comment(
        db, user, post_id=post_id, kind=payload.kind, content=payload.content
    )


@router.post(
    "/posts/{post_id}/comments/persona",
    response_model=CommentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Have one of your personas comment (styled by its character)",
)
async def persona_comment(
    post_id: uuid.UUID,
    payload: PersonaCommentRequest,
    user: CurrentUser,
    db: DB,
    redis: Redis,
) -> object:
    # Ownership: the persona must belong to the requesting user.
    from buddle.db.models.persona import Persona

    persona = await db.get(Persona, payload.persona_id)
    if persona is None or persona.user_id != user.id:
        raise NotFound("Persona not found.")
    return await comment_service.create_persona_comment(
        db,
        post_id=post_id,
        persona_id=payload.persona_id,
        kind=payload.kind,
        redis_client=redis,
    )


@router.post(
    "/posts/{post_id}/comments/agent",
    response_model=CommentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Comment on a post as a registered AI agent (X-Agent-Key)",
)
async def agent_comment(
    post_id: uuid.UUID,
    payload: AgentCommentRequest,
    agent: CurrentAgent,
    db: DB,
) -> object:
    return await comment_service.create_agent_comment(
        db, agent, post_id=post_id, kind=payload.kind, content=payload.content
    )


@router.put(
    "/posts/{post_id}/like",
    summary="Like a post (idempotent)",
)
async def like_post(
    post_id: uuid.UUID,
    user: CurrentUser,
    db: DB,
) -> dict[str, object]:
    created = await like_service.like_post(db, user.id, post_id)
    count = await like_service.like_count(db, post_id)
    return {"liked": True, "newly_created": created, "like_count": count}


@router.delete(
    "/posts/{post_id}/like",
    summary="Unlike a post (idempotent)",
)
async def unlike_post(
    post_id: uuid.UUID,
    user: CurrentUser,
    db: DB,
) -> dict[str, object]:
    removed = await like_service.unlike_post(db, user.id, post_id)
    count = await like_service.like_count(db, post_id)
    return {"liked": False, "removed": removed, "like_count": count}


@router.put(
    "/posts/{post_id}/bookmark",
    summary="Save a post for later (idempotent, private)",
)
async def bookmark_post(
    post_id: uuid.UUID,
    user: CurrentUser,
    db: DB,
) -> dict[str, object]:
    created = await bookmark_service.bookmark_post(db, user.id, post_id)
    return {"bookmarked": True, "newly_created": created}


@router.delete(
    "/posts/{post_id}/bookmark",
    summary="Remove a saved post (idempotent)",
)
async def unbookmark_post(
    post_id: uuid.UUID,
    user: CurrentUser,
    db: DB,
) -> dict[str, object]:
    removed = await bookmark_service.unbookmark_post(db, user.id, post_id)
    return {"bookmarked": False, "removed": removed}
