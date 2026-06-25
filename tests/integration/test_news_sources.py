"""Admin news-source configuration endpoints (where the pipeline searches).

The source store is Redis-backed (fakeredis in tests), so these exercise the
real /v1/admin/news/sources CRUD + validation (SSRF/kind) end to end.
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.asyncio


async def _make_admin(client, signup_and_login, db_session):  # type: ignore[no-untyped-def]
    from sqlalchemy import update

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
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_news_sources_crud_and_validation(client, signup_and_login, db_session):  # type: ignore[no-untyped-def]
    h = await _make_admin(client, signup_and_login, db_session)

    # defaults seeded on first read
    r = await client.get("/v1/admin/news/sources", headers=h)
    assert r.status_code == 200
    ids = {s["id"] for s in r.json()}
    assert {"hackernews", "devto", "techmeme"} <= ids

    # add a valid public RSS source
    r = await client.post(
        "/v1/admin/news/sources",
        headers=h,
        json={"name": "New Yorker", "kind": "rss",
              "url": "https://www.newyorker.com/feed/everything", "limit": 8},
    )
    assert r.status_code == 200, r.text
    assert r.json()["id"] == "new-yorker"

    r = await client.get("/v1/admin/news/sources", headers=h)
    assert any(s["id"] == "new-yorker" for s in r.json())

    # SSRF / bad-kind rejected with 400
    r = await client.post(
        "/v1/admin/news/sources",
        headers=h,
        json={"name": "evil", "kind": "rss", "url": "http://127.0.0.1/feed"},
    )
    assert r.status_code == 400
    r = await client.post(
        "/v1/admin/news/sources", headers=h, json={"name": "x", "kind": "bogus"}
    )
    assert r.status_code in (400, 422)

    # toggle + delete
    r = await client.patch(
        "/v1/admin/news/sources/techmeme", headers=h, json={"enabled": False}
    )
    assert r.status_code == 200 and r.json()["enabled"] is False

    r = await client.delete("/v1/admin/news/sources/new-yorker", headers=h)
    assert r.status_code == 200
    r = await client.delete("/v1/admin/news/sources/missing-xyz", headers=h)
    assert r.status_code == 404


async def test_news_sources_require_admin(client, signup_and_login):  # type: ignore[no-untyped-def]
    info = await signup_and_login()
    h = {"Authorization": f"Bearer {info['access_token']}"}
    r = await client.get("/v1/admin/news/sources", headers=h)
    assert r.status_code == 403
