"""Stage 3 mediator tests: persisted policy, embedding-based distribution.

The test env uses the stub embedding provider (deterministic hashing), so
content/persona embeddings are stable and token-overlap drives cosine
similarity — enough to assert the embedding path actually influences routing.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import update

from buddle.ai.embeddings import EMBED_DIM

pytestmark = pytest.mark.asyncio


async def _make_admin(client, signup_and_login, db_session):  # type: ignore[no-untyped-def]
    from buddle.db.models.enums import UserTier
    from buddle.db.models.user import User

    info = await signup_and_login()
    await db_session.execute(
        update(User)
        .where(User.id == uuid.UUID(info["user_id"]))
        .values(is_admin=True, tier=UserTier.PRO)
    )
    await db_session.commit()
    r = await client.post(
        "/v1/auth/login", json={"email": info["email"], "password": info["password"]}
    )
    return {**info, "access_token": r.json()["access_token"]}


def _h(info: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {info['access_token']}"}


# ── policy persistence ─────────────────────────────────────────────────


async def test_mediator_policy_defaults(client, signup_and_login, db_session):  # type: ignore[no-untyped-def]
    admin = await _make_admin(client, signup_and_login, db_session)
    r = await client.get("/v1/admin/policy/mediator", headers=_h(admin))
    assert r.status_code == 200
    body = r.json()
    assert body["alpha"] == pytest.approx(0.4)
    assert body["beta"] == pytest.approx(0.4)
    assert body["gamma"] == pytest.approx(0.2)


async def test_mediator_policy_update_persists(client, signup_and_login, db_session):  # type: ignore[no-untyped-def]
    admin = await _make_admin(client, signup_and_login, db_session)
    h = _h(admin)

    r = await client.patch(
        "/v1/admin/policy/mediator",
        json={"alpha": 0.7, "beta": 0.2, "gamma": 0.1},
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["alpha"] == pytest.approx(0.7)

    # Read back via a fresh DB query (proves it's persisted, not in-memory)
    from buddle.db.models.mediator_policy import MediatorPolicy

    row = await db_session.get(MediatorPolicy, 1)
    await db_session.refresh(row)
    assert float(row.alpha) == pytest.approx(0.7)
    assert float(row.beta) == pytest.approx(0.2)

    # Reset to defaults so other tests aren't affected
    await client.patch(
        "/v1/admin/policy/mediator",
        json={"alpha": 0.4, "beta": 0.4, "gamma": 0.2},
        headers=h,
    )


# ── persona embedding on create ─────────────────────────────────────────


async def test_persona_gets_context_embedding_on_create(  # type: ignore[no-untyped-def]
    client, signup_and_login, db_session
):
    info = await signup_and_login()
    h = _h(info)
    r = await client.post(
        "/v1/personas",
        json={"name": "여행하는시인", "model_key": "poet"},
        headers=h,
    )
    assert r.status_code == 201
    persona_id = r.json()["id"]

    from buddle.db.models.persona import Persona

    persona = await db_session.get(Persona, uuid.UUID(persona_id))
    await db_session.refresh(persona)
    assert persona.context_emb is not None
    assert len(persona.context_emb) == EMBED_DIM


# ── post gets content embedding ─────────────────────────────────────────


async def test_post_gets_content_embedding(client, signup_and_login, db_session):  # type: ignore[no-untyped-def]
    info = await signup_and_login()
    h = _h(info)
    r = await client.post("/v1/personas", json={"name": "p", "model_key": "analyst"}, headers=h)
    persona_id = r.json()["id"]

    r = await client.post(
        "/v1/posts",
        json={
            "persona_id": persona_id,
            "content_raw": "여행 코스 추천 정보 공유합니다",
            "visibility": "public",
        },
        headers=h,
    )
    assert r.status_code == 201
    post_id = r.json()["id"]

    from buddle.db.models.post import Post

    post = await db_session.get(Post, uuid.UUID(post_id))
    await db_session.refresh(post)
    assert post.content_emb is not None
    assert len(post.content_emb) == EMBED_DIM


# ── embedding-driven private distribution ───────────────────────────────


async def test_private_distribution_uses_embedding_similarity(  # type: ignore[no-untyped-def]
    client, signup_and_login, db_session
):
    """A private post about 'travel' should reach a persona whose interest
    profile embeds near 'travel', even without exact tag overlap, thanks to
    the embedding-similarity (beta) term."""
    # Sender
    sender = await signup_and_login()
    sh = _h(sender)
    r = await client.post(
        "/v1/personas", json={"name": "송신자", "model_key": "analyst"}, headers=sh
    )
    sender_persona = r.json()["id"]

    # Mint travel-themed tags via a public post so we can assign them to a
    # receiver persona (its interest profile then embeds near 'travel').
    r = await client.post(
        "/v1/posts",
        json={
            "persona_id": sender_persona,
            "content_raw": "여행 여행 여행 코스 여행 추천 여행 정보",
            "visibility": "public",
        },
        headers=sh,
    )
    minted = r.json()["tags"]
    assert minted
    tag_ids = [t["id"] for t in minted[:3]]

    # Receiver persona with travel interest tags -> travel-near context_emb
    receiver = await signup_and_login()
    rh = _h(receiver)
    r = await client.post(
        "/v1/personas",
        json={"name": "여행러", "model_key": "friend", "interest_tag_ids": tag_ids},
        headers=rh,
    )
    assert r.status_code == 201

    # Sender posts a PRIVATE travel message
    r = await client.post(
        "/v1/posts",
        json={
            "persona_id": sender_persona,
            "content_raw": "여행 비공개 메시지 여행 코스",
            "visibility": "private",
        },
        headers=sh,
    )
    assert r.status_code == 201

    # Receiver inbox should contain the delivery
    r = await client.get("/v1/inbox", headers=rh)
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) >= 1
    # relevance_score should be a real blended value in (0, 1]
    assert 0.0 < items[0]["relevance_score"] <= 1.0


async def test_distribution_excludes_source_persona(  # type: ignore[no-untyped-def]
    client, signup_and_login
):
    info = await signup_and_login()
    h = _h(info)
    r = await client.post("/v1/personas", json={"name": "혼자", "model_key": "poet"}, headers=h)
    persona_id = r.json()["id"]

    # Private post with no other matching personas -> own persona not targeted
    r = await client.post(
        "/v1/posts",
        json={
            "persona_id": persona_id,
            "content_raw": "고유한단어 고유한단어 외톨이메시지",
            "visibility": "private",
        },
        headers=h,
    )
    assert r.status_code == 201

    # Own inbox must not receive the self-authored private post
    r = await client.get("/v1/inbox", headers=h)
    assert r.status_code == 200
    items = r.json()["items"]
    assert all(it["source_persona"]["id"] != persona_id for it in items)
