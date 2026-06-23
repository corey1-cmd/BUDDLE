"""Argument-chat service — retrieval (I/O) + note persistence for the RAG AI.

Builds the ChatContext for a turn (the pure prompt-assembly lives in
ai/argument/retrieval), enforces the access rules (public posts only, author
opt-out → forbidden), and saves useful conversation output back onto the post.

Retrieval by mode:
  CLAIM  — the post's own argument units + nearest units from the same topic.
  AUTHOR — the author's public posts' units, ranked by cosine to the query,
           plus (if the author opted in) a short profile summary.

All retrieval excludes suppressed and non-public posts at the source.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from buddle.ai.argument import ChatContext, ChatMode, RetrievedUnit
from buddle.ai.embeddings import EmbeddingError, get_embedding_provider
from buddle.config import get_settings
from buddle.core.logging import get_logger
from buddle.db.models.argument_unit import ArgumentUnit
from buddle.db.models.enums import ContextNoteKind, PostVisibility
from buddle.db.models.persona import Persona
from buddle.db.models.post import Post
from buddle.db.models.post_context_note import PostContextNote

log = get_logger(__name__)

_RETRIEVE_K = 8
_POST_EXCERPT_CHARS = 240


@dataclass(frozen=True, slots=True)
class AccessResult:
    """Whether an argument-AI chat is allowed for a post, and why not."""

    allowed: bool
    reason: str = ""  # "not_found" | "not_public" | "opted_out"
    post: Post | None = None


async def check_access(db: AsyncSession, *, post_id: uuid.UUID, mode: ChatMode) -> AccessResult:
    """Gate an argument-AI chat: public post; for AUTHOR, author not opted out."""
    post = (await db.execute(select(Post).where(Post.id == post_id))).scalar_one_or_none()
    if post is None:
        return AccessResult(allowed=False, reason="not_found")
    if post.visibility != PostVisibility.PUBLIC or post.is_suppressed:
        return AccessResult(allowed=False, reason="not_public", post=post)

    if mode == ChatMode.AUTHOR and post.source_persona_id is not None:
        persona = (
            await db.execute(select(Persona).where(Persona.id == post.source_persona_id))
        ).scalar_one_or_none()
        if persona is not None and persona.argument_ai_opt_out:
            return AccessResult(allowed=False, reason="opted_out", post=post)

    return AccessResult(allowed=True, post=post)


async def _embed_or_none(text: str) -> list[float] | None:
    try:
        provider = get_embedding_provider()
        return await provider.embed_one(text)
    except EmbeddingError as e:
        log.warning("argument_chat.embed_failed", error=str(e))
        return None


def _to_units(rows: list[ArgumentUnit]) -> tuple[RetrievedUnit, ...]:
    return tuple(RetrievedUnit(text=r.text, kind=r.kind.value, stance=r.stance.value) for r in rows)


async def build_context(
    db: AsyncSession, *, post: Post, mode: ChatMode, query_text: str
) -> ChatContext:
    """Retrieve evidence and assemble the ChatContext for one turn."""
    excerpt = (post.content_transformed or "")[:_POST_EXCERPT_CHARS]
    query_emb = await _embed_or_none(query_text) if query_text else None

    if mode == ChatMode.CLAIM:
        units = await _retrieve_claim_units(db, post=post, query_emb=query_emb)
        return ChatContext(mode=mode, post_excerpt=excerpt, units=units)

    units = await _retrieve_author_units(db, post=post, query_emb=query_emb)
    summary = await _author_profile_summary(db, post=post)
    return ChatContext(mode=mode, post_excerpt=excerpt, units=units, author_profile_summary=summary)


async def _retrieve_claim_units(
    db: AsyncSession, *, post: Post, query_emb: list[float] | None
) -> tuple[RetrievedUnit, ...]:
    """The post's own units, plus nearest units from the same topic."""
    own = list(
        (
            await db.execute(
                select(ArgumentUnit)
                .where(ArgumentUnit.post_id == post.id)
                .order_by(ArgumentUnit.created_at.asc())
                .limit(_RETRIEVE_K)
            )
        )
        .scalars()
        .all()
    )
    if len(own) >= _RETRIEVE_K or query_emb is None or not own:
        return _to_units(own[:_RETRIEVE_K])

    # Top up with nearest claims from the same topics (excluding this post).
    topic_ids = list({u.topic_tag_id for u in own})
    remaining = _RETRIEVE_K - len(own)
    neighbors = list(
        (
            await db.execute(
                select(ArgumentUnit)
                .where(
                    ArgumentUnit.topic_tag_id.in_(topic_ids),
                    ArgumentUnit.post_id != post.id,
                    ArgumentUnit.emb.is_not(None),
                )
                .order_by(ArgumentUnit.emb.cosine_distance(query_emb))
                .limit(remaining)
            )
        )
        .scalars()
        .all()
    )
    return _to_units(own + neighbors)


async def _retrieve_author_units(
    db: AsyncSession, *, post: Post, query_emb: list[float] | None
) -> tuple[RetrievedUnit, ...]:
    """The author's public posts' units, ranked by cosine to the query."""
    if post.source_persona_id is None:
        # No persona author → fall back to the post's own units.
        return await _retrieve_claim_units(db, post=post, query_emb=query_emb)

    # Public, non-suppressed posts by the same persona.
    author_post_ids = select(Post.id).where(
        Post.source_persona_id == post.source_persona_id,
        Post.visibility == PostVisibility.PUBLIC,
        Post.is_suppressed.is_(False),
    )
    stmt = select(ArgumentUnit).where(ArgumentUnit.post_id.in_(author_post_ids))
    if query_emb is not None:
        stmt = stmt.where(ArgumentUnit.emb.is_not(None)).order_by(
            ArgumentUnit.emb.cosine_distance(query_emb)
        )
    else:
        stmt = stmt.order_by(ArgumentUnit.created_at.desc())
    rows = list((await db.execute(stmt.limit(_RETRIEVE_K))).scalars().all())
    return _to_units(rows)


async def _author_profile_summary(db: AsyncSession, *, post: Post) -> str:
    """A short, opt-in public personality summary for AUTHOR mode.

    Uses the central OCEAN profile only when the author has NOT opted out of
    profiling; otherwise returns empty (the AI then leans on public text only).
    """
    if post.source_persona_id is None:
        return ""
    persona = (
        await db.execute(select(Persona).where(Persona.id == post.source_persona_id))
    ).scalar_one_or_none()
    if persona is None:
        return ""
    from buddle.db.models.user_profile import UserProfile

    profile = (
        await db.execute(select(UserProfile).where(UserProfile.user_id == persona.user_id))
    ).scalar_one_or_none()
    if profile is None or profile.profile_opt_out or profile.confidence < 0.2:
        return ""
    # Translate the dominant traits into a brief, non-clinical phrase.
    traits: list[str] = []
    if profile.o >= 0.6:
        traits.append("새로운 관점에 열려 있는")
    if profile.c >= 0.6:
        traits.append("체계적이고 신중한")
    if profile.e >= 0.6:
        traits.append("적극적으로 의견을 나누는")
    if profile.a >= 0.6:
        traits.append("공감적이고 배려하는")
    if not traits:
        return ""
    return ", ".join(traits) + " 편입니다 (공개 동의된 추정)."


async def add_context_note(
    db: AsyncSession,
    *,
    post_id: uuid.UUID,
    content: str,
    kind: ContextNoteKind = ContextNoteKind.CONTEXT,
    source_session_id: uuid.UUID | None = None,
    commit: bool = True,
) -> PostContextNote:
    """Save a useful conversation output back onto the post."""
    note = PostContextNote(
        post_id=post_id,
        kind=kind,
        content=content[:2000],
        source_session_id=source_session_id,
    )
    db.add(note)
    if commit:
        await db.commit()
        await db.refresh(note)
    return note


async def list_context_notes(
    db: AsyncSession, *, post_id: uuid.UUID, limit: int = 20
) -> list[PostContextNote]:
    """Notes shown in the feed detail as '이 글의 부가 맥락'."""
    if not get_settings().argument_enabled:
        return []
    return list(
        (
            await db.execute(
                select(PostContextNote)
                .where(PostContextNote.post_id == post_id)
                .order_by(PostContextNote.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
