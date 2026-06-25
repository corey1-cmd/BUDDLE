"""Knowledge space wiring: user post -> tagged units -> pool -> fetch_context.

Verifies the gap-fixes that connect a user's writings to dialogue (the
'글 -> 백혈구·매개자 -> 지식공간 -> 대화' loop):
  - consider_post now tags units with the post's topics (topic_tags was always "")
  - build_pool forms the conversation-pool sub-layer (previously never called)
  - fetch_context (the dialogue read path) retrieves the user's own units by topic

Uses db_session + direct ORM inserts only — no FastAPI routes, no signup. All
buddle imports are deferred INTO the test bodies so the DB engine binds to the
testcontainer URL (set by the postgres_url fixture) rather than the .env URL at
collection time — matching the lazy-import convention used by the other tests.
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="session")
def event_loop_policy():
    # asyncpg needs the Selector loop on Windows (the default Proactor loop
    # breaks connection teardown: "'NoneType' object has no attribute 'send'").
    # No-op on POSIX where this policy is unavailable.
    import asyncio
    import sys

    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.get_event_loop_policy()


_TAG = "인공지능"
_CONTENT = "인공지능은 빠르게 발전하고 있다. 모델은 점점 더 똑똑해진다. 사회적 영향도 점점 커진다."


async def _seed_post(db):  # type: ignore[no-untyped-def]
    from buddle.db.models.enums import AuthorKind, PostVisibility
    from buddle.db.models.importance import ImportanceScore
    from buddle.db.models.persona import Persona
    from buddle.db.models.post import Post
    from buddle.db.models.tag import PostTag, Tag
    from buddle.db.models.user import User

    user = User(email=f"k-{uuid.uuid4().hex[:10]}@buddle.app", password_hash="x")
    db.add(user)
    await db.flush()
    persona = Persona(user_id=user.id, name="테스트", model_key="analyst")
    db.add(persona)
    await db.flush()
    post = Post(
        source_persona_id=persona.id,
        author_kind=AuthorKind.PERSONA_AI,
        content_raw=_CONTENT,
        content_transformed=_CONTENT,
        visibility=PostVisibility.PUBLIC,
        source_language="ko",
    )
    db.add(post)
    await db.flush()
    tag = Tag(name=_TAG)
    db.add(tag)
    await db.flush()
    db.add(PostTag(post_id=post.id, tag_id=tag.id))
    # Positive importance so the cold-start selection gate retains the units.
    db.add(ImportanceScore(post_id=post.id, raw_score=2.0, normalized=0.8))
    await db.commit()
    return persona, post


async def test_post_units_are_tagged_pooled_and_fetchable(db_session):  # type: ignore[no-untyped-def]
    from sqlalchemy import select

    from buddle.db.models.knowledge_unit import KnowledgeUnit
    from buddle.services import knowledge_service

    persona, post = await _seed_post(db_session)

    # 1) consider_post retains units AND tags them with the post's topic.
    res = await knowledge_service.consider_post(db_session, post.id)
    assert res.retained >= 1, f"expected retained units, got {res}"

    units = list(
        (
            await db_session.execute(
                select(KnowledgeUnit).where(KnowledgeUnit.source_post_id == post.id)
            )
        ).scalars()
    )
    assert units, "no knowledge units stored"
    assert all(_TAG in u.topic_tags for u in units), [u.topic_tags for u in units]

    # 2) build_pool forms the conversation-pool sub-layer for the topic.
    pool_id = await knowledge_service.build_pool(db_session, _TAG)
    assert pool_id is not None

    # 3) fetch_context (the dialogue read path) returns the user's own units.
    bundle = await knowledge_service.fetch_context(
        db_session, persona.id, topic=_TAG, requesting_persona_id=persona.id, limit=8
    )
    assert bundle.items, "fetch_context returned nothing for the topic"
    assert any(i.gist for i in bundle.items)


async def test_fetch_context_empty_topic_returns_no_items(db_session):  # type: ignore[no-untyped-def]
    from buddle.services import knowledge_service

    persona, post = await _seed_post(db_session)
    await knowledge_service.consider_post(db_session, post.id)
    bundle = await knowledge_service.fetch_context(
        db_session, persona.id, topic="존재하지않는토픽xyz", requesting_persona_id=persona.id
    )
    assert bundle.items == []
