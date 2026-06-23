"""Integration tests: auth flow."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_health(client):  # type: ignore[no-untyped-def]
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_signup_password_mismatch_422(client):  # type: ignore[no-untyped-def]
    r = await client.post(
        "/v1/auth/signup",
        json={
            "email": "mismatch@buddle.test",
            "password": "Password123!",
            "password_confirm": "Different456!",
        },
    )
    assert r.status_code == 422


async def test_signup_duplicate_email_409(client):  # type: ignore[no-untyped-def]
    email = "dup@buddle.test"
    body = {"email": email, "password": "Hunter22!", "password_confirm": "Hunter22!"}

    r1 = await client.post("/v1/auth/signup", json=body)
    assert r1.status_code == 201

    r2 = await client.post("/v1/auth/signup", json=body)
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "EMAIL_ALREADY_EXISTS"


async def test_login_wrong_password_401(client, signup_and_login):  # type: ignore[no-untyped-def]
    info = await signup_and_login()
    r = await client.post(
        "/v1/auth/login",
        json={"email": info["email"], "password": "WrongPass!"},
    )
    assert r.status_code == 401


async def test_refresh_issues_new_access(client, signup_and_login):  # type: ignore[no-untyped-def]
    info = await signup_and_login()
    r = await client.post("/v1/auth/refresh", json={"refresh_token": info["refresh_token"]})
    assert r.status_code == 200, r.text
    new_access = r.json()["access_token"]
    assert new_access and new_access != info["access_token"]


async def test_logout_revokes_refresh(client, signup_and_login):  # type: ignore[no-untyped-def]
    info = await signup_and_login()
    headers = {"Authorization": f"Bearer {info['access_token']}"}

    r = await client.post(
        "/v1/auth/logout",
        json={"refresh_token": info["refresh_token"]},
        headers=headers,
    )
    assert r.status_code == 204

    # Refresh should now fail
    r2 = await client.post("/v1/auth/refresh", json={"refresh_token": info["refresh_token"]})
    assert r2.status_code == 401


async def test_me_requires_auth(client):  # type: ignore[no-untyped-def]
    r = await client.get("/v1/users/me")
    assert r.status_code == 401


async def test_me_returns_user(client, signup_and_login):  # type: ignore[no-untyped-def]
    info = await signup_and_login()
    r = await client.get(
        "/v1/users/me",
        headers={"Authorization": f"Bearer {info['access_token']}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == info["email"]
    assert body["tier"] == "free"
    assert body["persona_quota"] == 3
