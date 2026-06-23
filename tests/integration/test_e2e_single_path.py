"""End-to-end single happy path (Phase 2 acceptance test).

Exercises the core pipeline against a real Postgres + pgvector with stub AI
providers (deterministic, offline): signup -> pick persona model -> create a
location-enabled persona -> submit a rough thought that the persona/mediator
transforms into a public post -> owner reads it -> a second user discovers it
through the public feed (the mediation/distribution surface).

This validates that the generate -> mediate -> distribute path is wired
end-to-end through the API, DB, and AI adapter layer. With real models seeded
(GLM-4.6 via vLLM) the same path produces real multilingual output; here the
stub providers keep it deterministic and infra-free.

Run against any Postgres + pgvector:
    BUDDLE_TEST_DATABASE_URL=postgresql+asyncpg://USER:PW@HOST:5432/DB \\
        python -m pytest tests/integration/test_e2e_single_path.py -q
or with Docker (testcontainers) by simply running the suite.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_single_path_thought_to_public_feed(client, signup_and_login) -> None:  # type: ignore[no-untyped-def]
    # 1. A user signs up and logs in.
    user_a = await signup_and_login()
    auth_a = {"Authorization": f"Bearer {user_a['access_token']}"}

    # 2. Discover available persona models (seeded by migration 0002).
    r = await client.get("/v1/persona-models", headers=auth_a)
    assert r.status_code == 200, r.text
    models = r.json()
    assert isinstance(models, list) and models, "no persona models available"
    model_key = models[0]["template_key"]

    # 3. Create a location-enabled persona (exercises the proximity opt-in path).
    r = await client.post(
        "/v1/personas",
        headers=auth_a,
        json={
            "name": "버들",
            "model_key": model_key,
            "location_sharing": True,
            "location_lat": 36.4801,   # Sejong
            "location_lon": 127.2890,
        },
    )
    assert r.status_code == 201, r.text
    persona_id = r.json()["id"]

    # 4. Submit a rough thought -> persona/mediator transform -> public post.
    thought = "오늘 강가를 걸었는데 참 좋더라. 비슷한 사람과 닿고 싶다."
    r = await client.post(
        "/v1/posts",
        headers=auth_a,
        json={"persona_id": persona_id, "content_raw": thought, "visibility": "public"},
    )
    assert r.status_code == 201, r.text
    post = r.json()
    post_id = post["id"]
    # The raw thought is preserved for the owner; the transformed version is what
    # gets distributed. Stub transform is deterministic but non-empty.
    assert post["content_raw"] == thought
    assert isinstance(post["content_transformed"], str)
    assert post["content_transformed"].strip(), "transformed content should not be empty"
    assert post["visibility"] == "public"
    assert post["is_suppressed"] is False, "a benign thought must not be suppressed"

    # 5. Owner can read the post back (raw + transformed).
    r = await client.get(f"/v1/posts/{post_id}", headers=auth_a)
    assert r.status_code == 200, r.text
    fetched = r.json()
    assert fetched["id"] == post_id
    assert fetched["content_transformed"] == post["content_transformed"]

    # 6. A second user discovers the public post through the feed
    #    (the mediation/distribution surface — no raw content exposure).
    user_b = await signup_and_login()
    auth_b = {"Authorization": f"Bearer {user_b['access_token']}"}

    r = await client.get("/v1/feed", headers=auth_b, params={"limit": 50})
    assert r.status_code == 200, r.text
    feed = r.json()
    ids = {item["id"] for item in feed["items"]}
    assert post_id in ids, "public post should be discoverable in another user's feed"

    surfaced = next(item for item in feed["items"] if item["id"] == post_id)
    # Feed exposes the transformed (mediated) content, never the raw thought.
    assert surfaced["content_transformed"] == post["content_transformed"]
    assert "content_raw" not in surfaced, "feed must not leak raw thoughts"
    assert isinstance(surfaced["importance"], (int, float))
