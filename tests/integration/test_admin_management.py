"""Integration tests: 슈퍼 관리자의 관리자 관리(부여/회수).

관리자 관리 3종(GET/POST/DELETE /v1/admin/admins)은 슈퍼 관리자(is_super_admin)
전용이다. 일반 관리자(is_admin)는 403. 슈퍼 관리자는 회수할 수 없다.
"""

from __future__ import annotations

import uuid as _uuid

import pytest
from sqlalchemy import update

from buddle.db.models.user import User

pytestmark = pytest.mark.asyncio


async def _make(  # type: ignore[no-untyped-def]
    client, signup_and_login, db_session, *, super_admin=False, admin=False
) -> dict[str, str]:
    info = await signup_and_login()
    values: dict[str, bool] = {}
    if admin or super_admin:
        values["is_admin"] = True
    if super_admin:
        values["is_super_admin"] = True
    if values:
        await db_session.execute(
            update(User).where(User.id == _uuid.UUID(info["user_id"])).values(**values)
        )
        await db_session.commit()
    r = await client.post(
        "/v1/auth/login", json={"email": info["email"], "password": info["password"]}
    )
    assert r.status_code == 200
    return {**info, "access_token": r.json()["access_token"]}


def _h(info: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {info['access_token']}"}


async def test_me_exposes_super_admin_flag(client, signup_and_login, db_session):  # type: ignore[no-untyped-def]
    sup = await _make(client, signup_and_login, db_session, super_admin=True)
    r = await client.get("/v1/users/me", headers=_h(sup))
    assert r.status_code == 200
    assert r.json()["is_super_admin"] is True


async def test_regular_admin_cannot_manage_admins(client, signup_and_login, db_session):  # type: ignore[no-untyped-def]
    adm = await _make(client, signup_and_login, db_session, admin=True)
    # 일반 관리자는 화면(stats)은 되지만 관리자 관리는 슈퍼 관리자 전용 → 403
    assert (await client.get("/v1/admin/stats", headers=_h(adm))).status_code == 200
    assert (await client.get("/v1/admin/admins", headers=_h(adm))).status_code == 403


async def test_super_admin_grants_and_revokes(client, signup_and_login, db_session):  # type: ignore[no-untyped-def]
    sup = await _make(client, signup_and_login, db_session, super_admin=True)
    target = await signup_and_login()

    r = await client.post(
        "/v1/admin/admins", json={"email": target["email"]}, headers=_h(sup)
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"].lower() == target["email"].lower()
    assert body["is_admin"] is True and body["is_super_admin"] is False

    r = await client.get("/v1/admin/admins", headers=_h(sup))
    emails = {a["email"].lower() for a in r.json()}
    assert target["email"].lower() in emails

    r = await client.delete(f"/v1/admin/admins/{target['user_id']}", headers=_h(sup))
    assert r.status_code == 200, r.text
    assert r.json()["is_admin"] is False


async def test_grant_unknown_email_is_404(client, signup_and_login, db_session):  # type: ignore[no-untyped-def]
    sup = await _make(client, signup_and_login, db_session, super_admin=True)
    r = await client.post(
        "/v1/admin/admins", json={"email": "nobody-unknown-xyz@example.com"}, headers=_h(sup)
    )
    assert r.status_code == 404


async def test_cannot_revoke_super_admin(client, signup_and_login, db_session):  # type: ignore[no-untyped-def]
    sup = await _make(client, signup_and_login, db_session, super_admin=True)
    r = await client.delete(f"/v1/admin/admins/{sup['user_id']}", headers=_h(sup))
    assert r.status_code == 400
