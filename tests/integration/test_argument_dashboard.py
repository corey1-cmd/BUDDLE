"""Argument service + debate dashboard tests — contracts + DB-backed flows.

DB tests run the full path: posts with argumentative content get units
extracted and stored under their topic tags, and the dashboard aggregates them
into conversation axes with stance splits and counts.
"""

from __future__ import annotations

import inspect
import uuid

# ── contracts (no DB) ──────────────────────────────────────────────────────


def test_argument_model_columns():
    from buddle.db.models.argument_unit import ArgumentUnit

    cols = set(ArgumentUnit.__table__.columns.keys())
    assert {
        "post_id",
        "topic_tag_id",
        "kind",
        "stance",
        "text",
        "emb",
        "parent_unit_id",
    } <= cols
    # claims may lack an embedding (non-claims / embed failure) → nullable.
    assert ArgumentUnit.__table__.columns["emb"].nullable


def test_enums_values():
    from buddle.db.models.enums import ArgumentKindEnum, ArgumentStanceEnum

    assert {k.value for k in ArgumentKindEnum} == {"claim", "ground", "rebuttal", "question"}
    assert {s.value for s in ArgumentStanceEnum} == {"pro", "con", "neutral"}


def test_service_signatures():
    from buddle.services import argument_service as a

    es = set(inspect.signature(a.extract_and_store).parameters)
    assert {"post_id", "content", "tag_ids"} <= es
    bd = set(inspect.signature(a.build_dashboard).parameters)
    assert "topic_tag_id" in bd


def test_dashboard_route_registered_get_only():
    from buddle.main import app

    methods: set[str] = set()
    for r in app.routes:
        if getattr(r, "path", "") == "/v1/topics/{tag_id}/debate":
            methods |= set(getattr(r, "methods", set()))
    assert "GET" in methods
    assert not ({"POST", "PUT", "PATCH", "DELETE"} & methods)


def test_migration_0020_chains_after_0019():
    from pathlib import Path

    src = Path("migrations/versions/20260612_1400_0020_argument_units.py").read_text(
        encoding="utf-8"
    )
    assert 'revision: str = "0020"' in src
    assert 'down_revision: str | None = "0019"' in src


# ── DB-backed flows ────────────────────────────────────────────────────────


async def _make_tag(db, name: str):  # type: ignore[no-untyped-def]
    from buddle.db.models.tag import Tag

    tag = Tag(name=name)
    db.add(tag)
    await db.commit()
    return tag.id


async def _make_post(db, content: str):  # type: ignore[no-untyped-def]
    from buddle.db.models.enums import AuthorKind, PostVisibility
    from buddle.db.models.post import Post

    post = Post(
        author_kind=AuthorKind.HUMAN,
        content_raw=content,
        content_transformed=content,
        visibility=PostVisibility.PUBLIC,
        source_language="ko",
    )
    db.add(post)
    await db.commit()
    return post.id


async def test_extract_and_store_writes_units(db_session):  # type: ignore[no-untyped-def]
    from sqlalchemy import select

    from buddle.db.models.argument_unit import ArgumentUnit
    from buddle.db.models.enums import ArgumentKindEnum
    from buddle.services import argument_service as a

    tag_id = await _make_tag(db_session, f"재개발_{uuid.uuid4().hex[:6]}")
    post_id = await _make_post(
        db_session,
        "재개발은 반드시 필요하다. 왜냐하면 노후 주택이 위험하기 때문이다. 하지만 대책이 없다.",
    )

    written = await a.extract_and_store(
        db_session,
        post_id=post_id,
        content="재개발은 반드시 필요하다. "
        "왜냐하면 노후 주택이 위험하기 때문이다. 하지만 대책이 없다.",
        tag_ids=[tag_id],
    )
    assert written >= 3

    rows = (
        (await db_session.execute(select(ArgumentUnit).where(ArgumentUnit.topic_tag_id == tag_id)))
        .scalars()
        .all()
    )
    kinds = {r.kind for r in rows}
    assert ArgumentKindEnum.CLAIM in kinds
    assert ArgumentKindEnum.REBUTTAL in kinds


async def test_no_tags_means_no_extraction(db_session):  # type: ignore[no-untyped-def]
    from buddle.services import argument_service as a

    post_id = await _make_post(db_session, "주장이 있다. 왜냐하면 근거가 있다.")
    written = await a.extract_and_store(
        db_session, post_id=post_id, content="주장이 있다.", tag_ids=[]
    )
    assert written == 0  # an argument needs a topic to argue under


async def test_dashboard_aggregates_into_axes(db_session):  # type: ignore[no-untyped-def]
    from buddle.services import argument_service as a

    tag_id = await _make_tag(db_session, f"교통_{uuid.uuid4().hex[:6]}")

    # Two posts arguing the same topic from different angles.
    p1 = await _make_post(db_session, "대중교통을 늘려야 한다. 왜냐하면 혼잡하기 때문이다.")
    await a.extract_and_store(
        db_session,
        post_id=p1,
        content="대중교통을 늘려야 한다. 왜냐하면 혼잡하기 때문이다.",
        tag_ids=[tag_id],
    )
    p2 = await _make_post(db_session, "주차장을 확충해야 한다. 하지만 예산이 부족하다.")
    await a.extract_and_store(
        db_session,
        post_id=p2,
        content="주차장을 확충해야 한다. 하지만 예산이 부족하다.",
        tag_ids=[tag_id],
    )

    view = await a.build_dashboard(db_session, topic_tag_id=tag_id)
    assert view.total_claims >= 2
    assert len(view.axes) >= 1
    # Every axis has a representative claim and a coherent stance split.
    for axis in view.axes:
        assert axis.representative_claim
        assert axis.pro + axis.con + axis.neutral == axis.claim_count


async def test_dashboard_empty_topic_has_no_axes(db_session):  # type: ignore[no-untyped-def]
    from buddle.services import argument_service as a

    tag_id = await _make_tag(db_session, f"빈화제_{uuid.uuid4().hex[:6]}")
    view = await a.build_dashboard(db_session, topic_tag_id=tag_id)
    assert view.total_claims == 0
    assert view.axes == []


# ── promote post to debate topic (글을 토론 씨앗으로) ──────────────────────────


def test_promote_route_registered():
    from buddle.main import app

    methods: set[str] = set()
    for r in app.routes:
        if getattr(r, "path", "") == "/v1/posts/{post_id}/debate-topic":
            methods |= set(getattr(r, "methods", set()))
    assert "POST" in methods


def test_promote_service_signature():
    import inspect

    from buddle.services import argument_service as a

    assert hasattr(a, "promote_post_to_topic")
    params = set(inspect.signature(a.promote_post_to_topic).parameters)
    assert {"post", "topic_name"} <= params


async def test_promote_creates_tag_and_seeds_units(db_session):  # type: ignore[no-untyped-def]
    import uuid as _uuid

    from sqlalchemy import func, select

    from buddle.db.models.argument_unit import ArgumentUnit
    from buddle.db.models.post import Post
    from buddle.db.models.tag import PostTag, Tag
    from buddle.services import argument_service as a

    post_id = await _make_post(
        db_session, "재개발은 반드시 필요하다. 왜냐하면 노후 주택이 위험하기 때문이다."
    )
    post = await db_session.get(Post, post_id)
    topic = f"재개발_{_uuid.uuid4().hex[:6]}"

    result = await a.promote_post_to_topic(db_session, post=post, topic_name=topic)
    assert result is not None
    assert result.topic_name == topic
    assert result.seeded_units >= 1

    # Tag created and linked.
    tag = (await db_session.execute(select(Tag).where(Tag.name == topic))).scalar_one()
    link = (
        await db_session.execute(
            select(PostTag).where(PostTag.post_id == post_id, PostTag.tag_id == tag.id)
        )
    ).scalar_one_or_none()
    assert link is not None
    # Units seeded under the tag.
    count = (
        await db_session.execute(
            select(func.count(ArgumentUnit.id)).where(ArgumentUnit.topic_tag_id == tag.id)
        )
    ).scalar_one()
    assert int(count) >= 1


async def test_promote_is_idempotent(db_session):  # type: ignore[no-untyped-def]
    import uuid as _uuid

    from sqlalchemy import func, select

    from buddle.db.models.argument_unit import ArgumentUnit
    from buddle.db.models.post import Post
    from buddle.services import argument_service as a

    post_id = await _make_post(db_session, "교육이 중요하다. 왜냐하면 미래이기 때문이다.")
    post = await db_session.get(Post, post_id)
    topic = f"교육_{_uuid.uuid4().hex[:6]}"

    r1 = await a.promote_post_to_topic(db_session, post=post, topic_name=topic)
    assert r1 is not None and r1.seeded_units >= 1
    tag_id = r1.tag_id
    count1 = (
        await db_session.execute(
            select(func.count(ArgumentUnit.id)).where(ArgumentUnit.topic_tag_id == tag_id)
        )
    ).scalar_one()

    # Promoting again must NOT duplicate units (idempotent seeding).
    r2 = await a.promote_post_to_topic(db_session, post=post, topic_name=topic)
    assert r2 is not None
    assert r2.tag_id == tag_id
    assert r2.seeded_units == 0  # already seeded
    count2 = (
        await db_session.execute(
            select(func.count(ArgumentUnit.id)).where(ArgumentUnit.topic_tag_id == tag_id)
        )
    ).scalar_one()
    assert int(count1) == int(count2)


async def test_promote_without_name_uses_first_tag(db_session):  # type: ignore[no-untyped-def]
    import uuid as _uuid

    from buddle.db.models.post import Post
    from buddle.services import argument_service as a

    # Seed a post WITH a tag via promote, then promote again with no name.
    post_id = await _make_post(db_session, "환경을 지켜야 한다. 왜냐하면 하나뿐이기 때문이다.")
    post = await db_session.get(Post, post_id)
    topic = f"환경_{_uuid.uuid4().hex[:6]}"
    await a.promote_post_to_topic(db_session, post=post, topic_name=topic)

    # No name → falls back to the post's existing first tag.
    result = await a.promote_post_to_topic(db_session, post=post, topic_name=None)
    assert result is not None
    assert result.topic_name == topic


async def test_promote_no_name_no_tag_returns_none(db_session):  # type: ignore[no-untyped-def]
    from buddle.db.models.post import Post
    from buddle.services import argument_service as a

    # A fresh post with no tags and no topic name → None (caller → 422).
    post_id = await _make_post(db_session, "태그 없는 글입니다.")
    post = await db_session.get(Post, post_id)
    result = await a.promote_post_to_topic(db_session, post=post, topic_name=None)
    assert result is None


# ── opposition geometry + stance contribution ──────────────────────────────


def test_opposition_routes_registered():
    from buddle.main import app

    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/v1/topics/{tag_id}/opposition" in paths
    assert "/v1/topics/{tag_id}/stance" in paths


def test_graph_route_registered():
    from buddle.main import app

    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/v1/topics/{tag_id}/graph" in paths


def test_opposition_service_signatures():
    import inspect

    from buddle.services import argument_service as a

    assert hasattr(a, "build_opposition")
    sc = set(inspect.signature(a.add_stance_contribution).parameters)
    assert {"topic_tag_id", "stance", "claim", "grounds"} <= sc


def test_argument_unit_post_id_nullable():
    from buddle.db.models.argument_unit import ArgumentUnit

    assert ArgumentUnit.__table__.columns["post_id"].nullable


def test_migration_0022_chains_after_0021():
    from pathlib import Path

    src = Path("migrations/versions/20260612_1600_0022_argument_units_post_nullable.py").read_text(
        encoding="utf-8"
    )
    assert 'revision: str = "0022"' in src
    assert 'down_revision: str | None = "0021"' in src


async def test_build_opposition_from_topic(db_session):  # type: ignore[no-untyped-def]
    import uuid as _uuid

    from buddle.ai.argument import OppositionType
    from buddle.db.models.tag import Tag
    from buddle.services import argument_service as a

    tag = Tag(name=f"대립_{_uuid.uuid4().hex[:6]}")
    db_session.add(tag)
    await db_session.commit()

    # Two posts taking opposite sides, with grounds (→ "strong").
    p1 = await _make_post(
        db_session, "재개발은 반드시 필요하다. 왜냐하면 노후 주택이 위험하기 때문이다."
    )
    await a.extract_and_store(
        db_session,
        post_id=p1,
        content="재개발은 반드시 필요하다. 왜냐하면 노후 주택이 위험하기 때문이다.",
        tag_ids=[tag.id],
    )
    p2 = await _make_post(db_session, "재개발에 반대한다. 왜냐하면 이주 대책이 없기 때문이다.")
    await a.extract_and_store(
        db_session,
        post_id=p2,
        content="재개발에 반대한다. 왜냐하면 이주 대책이 없기 때문이다.",
        tag_ids=[tag.id],
    )

    view = await a.build_opposition(db_session, topic_tag_id=tag.id)
    assert view.opposition_type in set(OppositionType)
    assert view.nodes  # geometry produced
    # coordinates normalized
    for n in view.nodes:
        assert 0.0 <= n.x <= 1.0 and 0.0 <= n.y <= 1.0


async def test_stance_contribution_adds_units(db_session):  # type: ignore[no-untyped-def]
    import uuid as _uuid

    from sqlalchemy import select

    from buddle.db.models.argument_unit import ArgumentUnit
    from buddle.db.models.enums import ArgumentKindEnum, ArgumentStanceEnum
    from buddle.db.models.tag import Tag
    from buddle.services import argument_service as a

    tag = Tag(name=f"기여_{_uuid.uuid4().hex[:6]}")
    db_session.add(tag)
    await db_session.commit()

    added = await a.add_stance_contribution(
        db_session,
        topic_tag_id=tag.id,
        stance="pro",
        claim="이 정책은 필요하다",
        grounds=["근거 하나", "근거 둘"],
    )
    assert added == 3  # 1 claim + 2 grounds

    rows = (
        (await db_session.execute(select(ArgumentUnit).where(ArgumentUnit.topic_tag_id == tag.id)))
        .scalars()
        .all()
    )
    claims = [r for r in rows if r.kind == ArgumentKindEnum.CLAIM]
    grounds = [r for r in rows if r.kind == ArgumentKindEnum.GROUND]
    assert len(claims) == 1 and len(grounds) == 2
    # the contributed units have no source post (tag-level).
    assert claims[0].post_id is None
    assert claims[0].stance == ArgumentStanceEnum.PRO
    # grounds reference the claim.
    assert all(g.parent_unit_id == claims[0].id for g in grounds)


# ── stance-by-name (채팅에서 "근거로 추가") ──────────────────────────────────


def test_by_name_route_registered_before_tag_id_route():
    """/by-name/stance must be registered ahead of /{tag_id}/stance, or a
    request to it would be swallowed by the tag_id path param first."""
    from buddle.main import app

    paths = [getattr(r, "path", "") for r in app.routes if "topics" in getattr(r, "path", "")]
    assert "/v1/topics/by-name/stance" in paths
    assert paths.index("/v1/topics/by-name/stance") < paths.index("/v1/topics/{tag_id}/stance")


def test_get_or_create_tag_signature():
    import inspect

    from buddle.services import argument_service as a

    assert hasattr(a, "get_or_create_tag")
    assert hasattr(a, "add_stance_contribution_by_name")
    sc = set(inspect.signature(a.add_stance_contribution_by_name).parameters)
    assert {"topic_name", "stance", "claim", "grounds"} <= sc


async def test_get_or_create_tag_is_idempotent(db_session):  # type: ignore[no-untyped-def]
    import uuid as _uuid

    from buddle.services import argument_service as a

    name = f"동네산책_{_uuid.uuid4().hex[:6]}"
    t1 = await a.get_or_create_tag(db_session, name)
    await db_session.commit()
    t2 = await a.get_or_create_tag(db_session, name)
    assert t1.id == t2.id


async def test_stance_by_name_creates_tag_when_missing(db_session):  # type: ignore[no-untyped-def]
    import uuid as _uuid

    from sqlalchemy import select

    from buddle.db.models.argument_unit import ArgumentUnit
    from buddle.db.models.tag import Tag
    from buddle.services import argument_service as a

    name = f"새화제_{_uuid.uuid4().hex[:6]}"
    # No tag exists yet for this name — this is exactly the chat scenario
    # (topic chip name with no debate started).
    tag_id, added = await a.add_stance_contribution_by_name(
        db_session,
        topic_name=name,
        stance="pro",
        claim="강가 코스가 산책하기 좋다",
        grounds=["사람이 적어서 한적하다"],
    )
    assert added == 2  # 1 claim + 1 ground

    tag = (await db_session.execute(select(Tag).where(Tag.id == tag_id))).scalar_one()
    assert tag.name == name

    rows = (
        (await db_session.execute(select(ArgumentUnit).where(ArgumentUnit.topic_tag_id == tag_id)))
        .scalars()
        .all()
    )
    assert len(rows) == 2


async def test_stance_by_name_reuses_existing_tag(db_session):  # type: ignore[no-untyped-def]
    import uuid as _uuid

    from buddle.db.models.tag import Tag
    from buddle.services import argument_service as a

    name = f"기존화제_{_uuid.uuid4().hex[:6]}"
    existing = Tag(name=name)
    db_session.add(existing)
    await db_session.commit()

    tag_id, _added = await a.add_stance_contribution_by_name(
        db_session, topic_name=name, stance="con", claim="동의하지 않는다", grounds=[]
    )
    assert tag_id == existing.id
