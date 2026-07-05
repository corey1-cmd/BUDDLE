"""Account deletion — DELETE /v1/users/me (Google Play requirement).

Verifies: wrong password is rejected; correct password permanently removes the
account and its personas; the same email can sign up again afterward (the row
is truly gone, not just deactivated); public posts survive but de-identified.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.asyncio


async def _h(info: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {info['access_token']}"}


async def test_delete_requires_correct_password(client, signup_and_login):  # type: ignore[no-untyped-def]
    info = await signup_and_login()
    h = await _h(info)

    r = await client.request(
        "DELETE", "/v1/users/me", json={"password": "definitely-wrong"}, headers=h
    )
    assert r.status_code == 401

    # Account still works after a rejected delete.
    r = await client.get("/v1/users/me", headers=h)
    assert r.status_code == 200


async def test_delete_removes_account_and_personas(client, signup_and_login, db_session):  # type: ignore[no-untyped-def]
    from buddle.db.models.persona import Persona
    from buddle.db.models.user import User

    info = await signup_and_login()
    h = await _h(info)
    user_id = uuid.UUID(info["user_id"])

    r = await client.post("/v1/personas", json={"name": "p", "model_key": "poet"}, headers=h)
    assert r.status_code == 201
    persona_id = uuid.UUID(r.json()["id"])

    r = await client.request(
        "DELETE", "/v1/users/me", json={"password": info["password"]}, headers=h
    )
    assert r.status_code == 204

    # User row and persona are gone (cascade).
    assert (await db_session.execute(select(User).where(User.id == user_id))).scalar_one_or_none() is None
    assert (
        await db_session.execute(select(Persona).where(Persona.id == persona_id))
    ).scalar_one_or_none() is None

    # The access token no longer resolves to a user.
    r = await client.get("/v1/users/me", headers=h)
    assert r.status_code == 401


async def test_email_reusable_after_deletion(client, signup_and_login):  # type: ignore[no-untyped-def]
    info = await signup_and_login()
    h = await _h(info)
    email, password = info["email"], info["password"]

    r = await client.request("DELETE", "/v1/users/me", json={"password": password}, headers=h)
    assert r.status_code == 204

    # Same email can register again — proves the row was deleted, not just disabled.
    r = await client.post(
        "/v1/auth/signup",
        json={"email": email, "password": password, "password_confirm": password},
    )
    assert r.status_code in (200, 201), r.text


async def test_public_posts_survive_deidentified(client, signup_and_login, db_session):  # type: ignore[no-untyped-def]
    """A deleted user's public post remains but loses its author link (SET NULL)."""
    from buddle.db.models.post import Post

    info = await signup_and_login()
    h = await _h(info)
    r = await client.post("/v1/personas", json={"name": "p", "model_key": "poet"}, headers=h)
    persona_id = r.json()["id"]
    r = await client.post(
        "/v1/posts",
        json={"persona_id": persona_id, "content_raw": "공개 담론은 남는다", "visibility": "public"},
        headers=h,
    )
    post_id = uuid.UUID(r.json()["id"])

    await client.request("DELETE", "/v1/users/me", json={"password": info["password"]}, headers=h)

    post = (
        await db_session.execute(select(Post).where(Post.id == post_id))
    ).scalar_one_or_none()
    assert post is not None, "public post should survive account deletion"
    assert post.source_persona_id is None, "author link should be de-identified (SET NULL)"
