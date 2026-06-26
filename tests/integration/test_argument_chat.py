"""Argument-chat service tests — contracts + DB-backed access/retrieval/notes.

DB tests verify the access gate (public-only, author opt-out → forbidden),
that retrieval grounds the context in the post's own units, and that context
notes persist and read back.
"""

from __future__ import annotations

import inspect
import uuid

# ── contracts (no DB) ──────────────────────────────────────────────────────


def test_context_note_model_columns():
    from buddle.db.models.post_context_note import PostContextNote

    cols = set(PostContextNote.__table__.columns.keys())
    assert {"post_id", "kind", "content", "source_session_id"} <= cols


def test_persona_has_argument_opt_out():
    from buddle.db.models.persona import Persona

    assert "argument_ai_opt_out" in Persona.__table__.columns


def test_service_signatures():
    from buddle.services import argument_chat_service as a

    assert {"post_id", "mode"} <= set(inspect.signature(a.check_access).parameters)
    assert {"post", "mode", "query_text"} <= set(inspect.signature(a.build_context).parameters)


def test_ws_route_and_notes_route_registered():
    from buddle.api.v1.argument_chat_ws import router as ws_router
    from buddle.main import app

    from tests.integration._routes import registered_paths, router_paths

    # WebSocket routes aren't in OpenAPI; check the source router declares it.
    assert "/ws/argument/{post_id}" in router_paths(ws_router)
    # The notes route is a normal HTTP route.
    assert "/v1/posts/{post_id}/context-notes" in registered_paths(app)


def test_migration_0021_chains_after_0020():
    from pathlib import Path

    src = Path("migrations/versions/20260612_1500_0021_argument_ai.py").read_text(encoding="utf-8")
    assert 'revision: str = "0021"' in src
    assert 'down_revision: str | None = "0020"' in src


# ── DB-backed flows ────────────────────────────────────────────────────────


async def _make_user_persona(db, opt_out=False):  # type: ignore[no-untyped-def]
    from buddle.db.models.persona import Persona
    from buddle.db.models.user import User

    suffix = uuid.uuid4().hex[:8]
    user = User(email=f"arg_{suffix}@test.local", password_hash="x" * 32)
    db.add(user)
    await db.flush()
    persona = Persona(
        user_id=user.id, name=f"버들-{suffix}", model_key="friend", argument_ai_opt_out=opt_out
    )
    db.add(persona)
    await db.commit()
    return user.id, persona.id


async def _make_post(db, persona_id, content, public=True):  # type: ignore[no-untyped-def]
    from buddle.db.models.enums import AuthorKind, PostVisibility
    from buddle.db.models.post import Post

    post = Post(
        source_persona_id=persona_id,
        author_kind=AuthorKind.PERSONA_AI,
        content_raw=content,
        content_transformed=content,
        visibility=PostVisibility.PUBLIC if public else PostVisibility.PRIVATE,
        source_language="ko",
    )
    db.add(post)
    await db.commit()
    return post.id


async def test_access_allows_public_claim(db_session):  # type: ignore[no-untyped-def]
    from buddle.ai.argument import ChatMode
    from buddle.services import argument_chat_service as a

    _uid, pid = await _make_user_persona(db_session)
    post_id = await _make_post(db_session, pid, "재개발은 필요하다.")
    res = await a.check_access(db_session, post_id=post_id, mode=ChatMode.CLAIM)
    assert res.allowed


async def test_access_denies_private_post(db_session):  # type: ignore[no-untyped-def]
    from buddle.ai.argument import ChatMode
    from buddle.services import argument_chat_service as a

    _uid, pid = await _make_user_persona(db_session)
    post_id = await _make_post(db_session, pid, "비공개 글", public=False)
    res = await a.check_access(db_session, post_id=post_id, mode=ChatMode.CLAIM)
    assert not res.allowed and res.reason == "not_public"


async def test_access_denies_author_optout(db_session):  # type: ignore[no-untyped-def]
    from buddle.ai.argument import ChatMode
    from buddle.services import argument_chat_service as a

    _uid, pid = await _make_user_persona(db_session, opt_out=True)
    post_id = await _make_post(db_session, pid, "공개 글이지만 인물 AI 거부")
    # CLAIM mode is still fine (it's about the post, not the person)...
    claim = await a.check_access(db_session, post_id=post_id, mode=ChatMode.CLAIM)
    assert claim.allowed
    # ...but AUTHOR mode (reconstructing the person) is forbidden.
    author = await a.check_access(db_session, post_id=post_id, mode=ChatMode.AUTHOR)
    assert not author.allowed and author.reason == "opted_out"


async def test_build_context_grounds_in_post_units(db_session):  # type: ignore[no-untyped-def]
    from buddle.ai.argument import ChatMode, has_grounding
    from buddle.services import argument_chat_service as a
    from buddle.services import argument_service

    _uid, pid = await _make_user_persona(db_session)
    content = "재개발은 반드시 필요하다. 왜냐하면 노후 주택이 위험하기 때문이다."
    post_id = await _make_post(db_session, pid, content)
    # Seed argument units under a topic.
    from buddle.db.models.tag import Tag

    tag = Tag(name=f"재개발_{uuid.uuid4().hex[:6]}")
    db_session.add(tag)
    await db_session.commit()
    await argument_service.extract_and_store(
        db_session, post_id=post_id, content=content, tag_ids=[tag.id]
    )

    from buddle.db.models.post import Post

    post = await db_session.get(Post, post_id)
    ctx = await a.build_context(
        db_session, post=post, mode=ChatMode.CLAIM, query_text="왜 필요한가"
    )
    assert has_grounding(ctx)
    assert ctx.mode == ChatMode.CLAIM


async def test_context_note_save_and_list(db_session):  # type: ignore[no-untyped-def]
    from buddle.db.models.enums import ContextNoteKind
    from buddle.services import argument_chat_service as a

    _uid, pid = await _make_user_persona(db_session)
    post_id = await _make_post(db_session, pid, "어떤 주장")
    note = await a.add_context_note(
        db_session, post_id=post_id, content="추가 근거: 통계 자료", kind=ContextNoteKind.EVIDENCE
    )
    assert note.id is not None
    notes = await a.list_context_notes(db_session, post_id=post_id)
    assert len(notes) == 1
    assert notes[0].content == "추가 근거: 통계 자료"
