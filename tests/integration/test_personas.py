"""Integration tests: persona CRUD + quota + registry validation."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _h(info: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {info['access_token']}"}


async def test_list_active_persona_models(client, signup_and_login):  # type: ignore[no-untyped-def]
    info = await signup_and_login()
    r = await client.get("/v1/persona-models", headers=await _h(info))
    assert r.status_code == 200, r.text
    models = r.json()
    keys = {m["template_key"] for m in models}
    assert {"poet", "analyst", "friend", "critic"}.issubset(keys)
    for m in models:
        assert m["backend_kind"] == "stub"


async def test_create_persona_happy_path(client, signup_and_login):  # type: ignore[no-untyped-def]
    info = await signup_and_login()
    h = await _h(info)

    r = await client.post(
        "/v1/personas",
        json={"name": "내 시인", "model_key": "poet"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "내 시인"
    assert body["model_key"] == "poet"
    assert body["is_active"] is True
    assert body["interest_tags"] == []
    # location_sharing is exposed on detail (default false) so the nearby
    # screen can render on/off without guessing.
    assert body["location_sharing"] is False


async def test_persona_detail_exposes_location_sharing(client, signup_and_login):  # type: ignore[no-untyped-def]
    """Creating with sharing on, then GET detail, must report it true — this is
    the contract the nearby screen's on/off view depends on."""
    info = await signup_and_login()
    h = await _h(info)

    r = await client.post(
        "/v1/personas",
        json={
            "name": "산책러",
            "model_key": "friend",
            "location_sharing": True,
            "location_lat": 36.4801,
            "location_lon": 127.2890,
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert r.json()["location_sharing"] is True

    d = await client.get(f"/v1/personas/{pid}", headers=h)
    assert d.status_code == 200, d.text
    assert d.json()["location_sharing"] is True


async def test_create_persona_unknown_model_404(client, signup_and_login):  # type: ignore[no-untyped-def]
    info = await signup_and_login()
    r = await client.post(
        "/v1/personas",
        json={"name": "유령", "model_key": "does-not-exist"},
        headers=await _h(info),
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"


async def test_persona_quota_enforced(client, signup_and_login):  # type: ignore[no-untyped-def]
    info = await signup_and_login()
    h = await _h(info)

    # FREE tier quota = 3 (from .env / settings)
    for i in range(3):
        r = await client.post(
            "/v1/personas",
            json={"name": f"p{i}", "model_key": "friend"},
            headers=h,
        )
        assert r.status_code == 201, r.text

    # 4th should fail with 402
    r = await client.post(
        "/v1/personas",
        json={"name": "over", "model_key": "friend"},
        headers=h,
    )
    assert r.status_code == 402
    assert r.json()["error"]["code"] == "QUOTA_EXCEEDED"


async def test_list_then_soft_delete_then_recreate(client, signup_and_login):  # type: ignore[no-untyped-def]
    info = await signup_and_login()
    h = await _h(info)

    r = await client.post(
        "/v1/personas",
        json={"name": "임시", "model_key": "analyst"},
        headers=h,
    )
    assert r.status_code == 201
    persona_id = r.json()["id"]

    # Soft delete
    r = await client.delete(f"/v1/personas/{persona_id}", headers=h)
    assert r.status_code == 204

    # GET still returns it but inactive
    r = await client.get(f"/v1/personas/{persona_id}", headers=h)
    assert r.status_code == 200
    assert r.json()["is_active"] is False

    # Quota frees up — can create a new one
    r = await client.post(
        "/v1/personas",
        json={"name": "후속", "model_key": "analyst"},
        headers=h,
    )
    assert r.status_code == 201


async def test_update_persona_swap_model(client, signup_and_login):  # type: ignore[no-untyped-def]
    info = await signup_and_login()
    h = await _h(info)

    r = await client.post("/v1/personas", json={"name": "테스트", "model_key": "poet"}, headers=h)
    persona_id = r.json()["id"]

    r = await client.patch(
        f"/v1/personas/{persona_id}",
        json={"model_key": "critic"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["model_key"] == "critic"


async def test_quota_info_endpoint(client, signup_and_login):  # type: ignore[no-untyped-def]
    info = await signup_and_login()
    h = await _h(info)

    r = await client.get("/v1/personas/quota", headers=h)
    assert r.status_code == 200
    q = r.json()
    assert q["limit"] == 3
    assert q["current"] == 0
    assert q["remaining"] == 3

    await client.post("/v1/personas", json={"name": "x", "model_key": "friend"}, headers=h)

    r = await client.get("/v1/personas/quota", headers=h)
    q = r.json()
    assert q["current"] == 1
    assert q["remaining"] == 2
