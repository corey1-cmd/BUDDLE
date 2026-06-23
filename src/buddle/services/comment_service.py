"""Comment service — replies on public-plaza posts.

Comments come in three kinds (per spec): inform (provide info), empathize
(react/support), question (ask, styled by persona character). Like posts, a
comment's content passes the leukocyte ethics gate before it is shown; a
high-severity comment is stored but suppressed.

Author paths mirror posts: human, persona_ai (styled question/empathy), and
external_ai (e.g. a Q&A agent answering). All converge on _persist_comment.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from buddle.ai.personas import PersonaService
from buddle.core.exceptions import Forbidden, NotFound
from buddle.core.types import RedisClient
from buddle.db.models.ai_agent import AIAgent
from buddle.db.models.comment import Comment
from buddle.db.models.enums import AuthorKind, CommentKind, PostVisibility
from buddle.db.models.persona import Persona
from buddle.db.models.post import Post
from buddle.db.models.user import User
from buddle.services.leukocyte_service import assess_post


async def _public_post_or_404(db: AsyncSession, post_id: uuid.UUID) -> Post:
    post = await db.get(Post, post_id)
    if not post or post.visibility != PostVisibility.PUBLIC or post.is_suppressed:
        raise NotFound("Post not found.")
    return post


async def _persist_comment(db: AsyncSession, comment: Comment) -> Comment:
    """Add a comment, run the ethics gate, commit. Suppresses if severe."""
    db.add(comment)
    await db.flush()
    # Reuse the leukocyte assessment on the comment content. We pass the
    # comment id as the audit target; assess_post is content-generic.
    leuko = await assess_post(db, comment.id, comment.content, commit=False)
    if leuko.should_suppress:
        comment.is_suppressed = True
    await db.commit()
    await db.refresh(comment)
    return comment


async def create_human_comment(
    db: AsyncSession,
    user: User,
    *,
    post_id: uuid.UUID,
    kind: CommentKind,
    content: str,
) -> Comment:
    await _public_post_or_404(db, post_id)
    return await _persist_comment(
        db,
        Comment(
            post_id=post_id,
            kind=kind,
            author_kind=AuthorKind.HUMAN,
            author_user_id=user.id,
            content=content,
        ),
    )


async def create_agent_comment(
    db: AsyncSession,
    agent: AIAgent,
    *,
    post_id: uuid.UUID,
    kind: CommentKind,
    content: str,
) -> Comment:
    if not agent.is_active:
        raise Forbidden("Agent is inactive.")
    await _public_post_or_404(db, post_id)
    return await _persist_comment(
        db,
        Comment(
            post_id=post_id,
            kind=kind,
            author_kind=AuthorKind.EXTERNAL_AI,
            author_label=agent.name,
            agent_id=agent.id,
            content=content,
        ),
    )


# Persona-styled question prompts: the persona model rephrases a question in
# its own character (the spec's "question style varies by persona personality").
_KIND_PROMPTS: dict[CommentKind, str] = {
    CommentKind.QUESTION: "다음 글에 대해 너의 성격이 드러나는 호기심 어린 질문을 한 문장으로 남겨줘",
    CommentKind.EMPATHIZE: "다음 글에 대해 따뜻하게 공감하는 한두 문장을 남겨줘",
    CommentKind.INFORM: "다음 글에 도움이 될 정보를 간결하게 한두 문장으로 덧붙여줘",
}


async def create_persona_comment(
    db: AsyncSession,
    *,
    post_id: uuid.UUID,
    persona_id: uuid.UUID,
    kind: CommentKind,
    redis_client: RedisClient | None = None,
) -> Comment:
    """A buddle persona comments on a post, styled by its character + kind."""
    post = await _public_post_or_404(db, post_id)
    persona = await db.get(Persona, persona_id)
    if persona is None:
        raise NotFound("Persona not found.")

    instruction = _KIND_PROMPTS.get(kind, _KIND_PROMPTS[CommentKind.EMPATHIZE])
    persona_ai = PersonaService(db, redis_client)
    result = await persona_ai.interpret(
        persona_name=persona.name,
        model_key=persona.model_key,
        content_raw=f"{instruction}:\n\n{post.content_transformed}",
    )

    return await _persist_comment(
        db,
        Comment(
            post_id=post_id,
            kind=kind,
            author_kind=AuthorKind.PERSONA_AI,
            author_label=persona.name,
            source_persona_id=persona.id,
            content=result.content_transformed,
        ),
    )


async def list_comments(db: AsyncSession, post_id: uuid.UUID, *, limit: int = 50) -> list[Comment]:
    """List non-suppressed comments on a post, oldest first."""
    limit = max(1, min(limit, 200))
    rows = await db.execute(
        select(Comment)
        .where(Comment.post_id == post_id, Comment.is_suppressed.is_(False))
        .order_by(Comment.created_at.asc())
        .limit(limit)
    )
    return list(rows.scalars())
