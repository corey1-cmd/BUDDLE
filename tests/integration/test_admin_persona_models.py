"""Integration tests: admin endpoints, especially the persona model registry.

This is the critical test: validates that a newly-trained persona model can
be registered at runtime and adopted by an end user, without code changes or
migrations.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import update

pytestmark = pytest.mark.asyncio


async def _make_admin(  # type: ignore[no-untyped-def]
    client, signup_and_login, db_session
) -> dict[str, str]:
    """Sign up a user, flip is_admin=true in DB, then re-login for a fresh token."""
    info = await signup_and_login()
    import uuid as _uuid

    from buddle.db.models.user import User

    await db_session.execute(
        update(User).where(User.id == _uuid.UUID(info["user_id"])).values(is_admin=True)
    )
    await db_session.commit()

    # Re-login so the user record (and downstream checks) reflect admin status.
    r = await client.post(
        "/v1/auth/login",
        json={"email": info["email"], "password": info["password"]},
    )
    assert r.status_code == 200
    return {**info, "access_token": r.json()["access_token"]}


async def _h(info: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {info['access_token']}"}


async def test_non_admin_blocked_403(client, signup_and_login):  # type: ignore[no-untyped-def]
    info = await signup_and_login()
    r = await client.get("/v1/admin/stats", headers=await _h(info))
    assert r.status_code == 403


async def test_admin_stats(client, signup_and_login, db_session):  # type: ignore[no-untyped-def]
    admin = await _make_admin(client, signup_and_login, db_session)
    r = await client.get("/v1/admin/stats", headers=await _h(admin))
    assert r.status_code == 200, r.text
    stats = r.json()
    # 4 baseline models from migration 0002
    assert stats["persona_models_active"] >= 4
    assert stats["users_total"] >= 1


async def test_admin_authority_snapshot(  # type: ignore[no-untyped-def]
    client, signup_and_login, db_session
):
    admin = await _make_admin(client, signup_and_login, db_session)
    r = await client.get("/v1/admin/authority", headers=await _h(admin))
    assert r.status_code == 200
    body = r.json()
    assert body["state"]["state"] == "normal"


async def test_register_new_persona_model_then_user_can_adopt(  # type: ignore[no-untyped-def]
    client, signup_and_login, db_session
):
    """End-to-end: train a model offline -> admin registers it -> user adopts it.

    Validates the central goal of Stage 1 part 4: persona models are a
    runtime-managed registry, not hardcoded.
    """
    admin = await _make_admin(client, signup_and_login, db_session)
    ah = await _h(admin)

    # 1. Admin registers a new model — backend_kind=vllm_endpoint, status=draft
    new_model: dict[str, Any] = {
        "template_key": "qwen3-poet-v2",
        "display_name": "시인 v2",
        "description": "더 시적인 페르소나",
        "version": "0.2.0",
        "backend_kind": "vllm_endpoint",
        "backend_config": {
            "endpoint_url": "https://10.0.0.1/v1",
            "model": "qwen3-7b-instruct",
            "lora_adapter": "hf://buddle/poet-v2",
        },
        "system_prompt": "당신은 시인 v2 페르소나입니다.",
        "status": "draft",
        "is_default": False,
    }
    r = await client.post("/v1/admin/persona-models", json=new_model, headers=ah)
    assert r.status_code == 201, r.text
    model_id = r.json()["id"]

    # 2. User should NOT see draft model in public list
    user = await signup_and_login()
    uh = await _h(user)
    r = await client.get("/v1/persona-models", headers=uh)
    keys = [m["template_key"] for m in r.json()]
    assert "qwen3-poet-v2" not in keys

    # 3. Trying to create a persona on the draft model -> 404
    r = await client.post(
        "/v1/personas",
        json={"name": "early adopter", "model_key": "qwen3-poet-v2"},
        headers=uh,
    )
    assert r.status_code == 404

    # 4. Admin flips status -> active
    r = await client.patch(
        f"/v1/admin/persona-models/{model_id}",
        json={"status": "active"},
        headers=ah,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "active"

    # 5. Public list now includes it
    r = await client.get("/v1/persona-models", headers=uh)
    keys = [m["template_key"] for m in r.json()]
    assert "qwen3-poet-v2" in keys

    # 6. User can create a persona with it
    r = await client.post(
        "/v1/personas",
        json={"name": "내 시인 v2", "model_key": "qwen3-poet-v2"},
        headers=uh,
    )
    assert r.status_code == 201, r.text
    persona_id = r.json()["id"]

    # 7. Admin tries to hard-delete -> blocked (in use)
    r = await client.delete(f"/v1/admin/persona-models/{model_id}", headers=ah)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "CONFLICT"

    # 8. Admin retires it instead
    r = await client.patch(
        f"/v1/admin/persona-models/{model_id}",
        json={"status": "retired"},
        headers=ah,
    )
    assert r.status_code == 200

    # 9. Existing persona still works (post creation through retired model)
    r = await client.post(
        "/v1/posts",
        json={
            "persona_id": persona_id,
            "content_raw": "시인 v2로 쓰는 글",
            "visibility": "public",
        },
        headers=uh,
    )
    assert r.status_code == 201, r.text
    assert r.json()["content_transformed"].startswith("[시인 v2] ")

    # 10. But new personas can't adopt the retired model
    r = await client.post(
        "/v1/personas",
        json={"name": "late comer", "model_key": "qwen3-poet-v2"},
        headers=uh,
    )
    assert r.status_code == 404


async def test_mediator_policy_get_and_patch(  # type: ignore[no-untyped-def]
    client, signup_and_login, db_session
):
    admin = await _make_admin(client, signup_and_login, db_session)
    ah = await _h(admin)

    r = await client.get("/v1/admin/policy/mediator", headers=ah)
    assert r.status_code == 200
    body = r.json()
    assert body["alpha"] + body["beta"] + body["gamma"] == pytest.approx(1.0, abs=0.01)

    r = await client.patch(
        "/v1/admin/policy/mediator",
        json={"alpha": 0.6, "beta": 0.3, "gamma": 0.1},
        headers=ah,
    )
    assert r.status_code == 200
    # alpha is stored in a 32-bit float column, so it round-trips as ~0.6.
    assert r.json()["alpha"] == pytest.approx(0.6, abs=1e-6)
