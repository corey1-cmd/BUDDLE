"""Integration tests: posts, feed, inbox.

These exercise the full pipeline through stub AIs:
  user input -> persona_stub -> mediator_stub -> tag + (page | distribute) -> feed/inbox
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _h(info: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {info['access_token']}"}


async def _make_user_with_persona(
    client, signup_and_login, *, model_key: str = "poet", persona_name: str = "p"
) -> tuple[dict[str, str], str]:  # type: ignore[no-untyped-def]
    info = await signup_and_login()
    h = await _h(info)
    r = await client.post(
        "/v1/personas",
        json={"name": persona_name, "model_key": model_key},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return info, r.json()["id"]


async def test_create_public_post_shows_in_feed(client, signup_and_login):  # type: ignore[no-untyped-def]
    info, persona_id = await _make_user_with_persona(client, signup_and_login)
    h = await _h(info)

    r = await client.post(
        "/v1/posts",
        json={
            "persona_id": persona_id,
            "content_raw": "오늘 하늘이 너무 파랗다 산책 가야지",
            "visibility": "public",
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    post = r.json()
    assert post["visibility"] == "public"
    assert post["content_transformed"].startswith("[시인] ")
    assert post["source_persona"]["id"] == persona_id
    # Tags should have been extracted by the mediator stub
    assert len(post["tags"]) > 0

    # Feed should contain this post
    r = await client.get("/v1/feed", headers=h)
    assert r.status_code == 200
    feed = r.json()
    assert any(item["id"] == post["id"] for item in feed["items"])


async def test_feed_tag_filter_server_side(client, signup_and_login):  # type: ignore[no-untyped-def]
    """?tag= filters server-side to posts carrying that exact tag, and an
    unknown tag yields none. This is the contract the feed screen relies on
    (client-side filtering of cursor pages would drop later-page matches)."""
    info, persona_id = await _make_user_with_persona(client, signup_and_login)
    h = await _h(info)

    r = await client.post(
        "/v1/posts",
        json={
            "persona_id": persona_id,
            "content_raw": "주말 러닝 크루 모집합니다 같이 달려요",
            "visibility": "public",
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    post = r.json()
    tags = [t["name"] for t in post["tags"]]
    assert tags, "mediator stub should have produced at least one tag"
    target = tags[0]

    # Filtering by a real tag returns the post.
    r = await client.get(f"/v1/feed?tag={target}", headers=h)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert any(it["id"] == post["id"] for it in items)
    # Every returned item actually carries the tag (server-side filter holds).
    for it in items:
        assert target in [t["name"] for t in it["tags"]]

    # Filtering by a tag that doesn't exist returns nothing.
    r = await client.get("/v1/feed?tag=__nonexistent_tag__", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["items"] == []


async def test_post_owner_can_read_with_raw(client, signup_and_login):  # type: ignore[no-untyped-def]
    info, persona_id = await _make_user_with_persona(client, signup_and_login)
    h = await _h(info)

    r = await client.post(
        "/v1/posts",
        json={
            "persona_id": persona_id,
            "content_raw": "비밀 메모",
            "visibility": "public",
        },
        headers=h,
    )
    post_id = r.json()["id"]

    r = await client.get(f"/v1/posts/{post_id}", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["content_raw"] == "비밀 메모"


async def test_other_user_cannot_read_owner_post(  # type: ignore[no-untyped-def]
    client, signup_and_login
):
    info_a, persona_a = await _make_user_with_persona(client, signup_and_login)
    info_b = await signup_and_login()
    ha, hb = await _h(info_a), await _h(info_b)

    r = await client.post(
        "/v1/posts",
        json={"persona_id": persona_a, "content_raw": "비밀", "visibility": "public"},
        headers=ha,
    )
    post_id = r.json()["id"]

    # User B asks for User A's post detail
    r = await client.get(f"/v1/posts/{post_id}", headers=hb)
    assert r.status_code == 404


async def test_private_post_distributes_to_matching_persona(  # type: ignore[no-untyped-def]
    client, signup_and_login
):
    # User A creates a persona + private post on topic 'travel'
    info_a, persona_a = await _make_user_with_persona(
        client, signup_and_login, model_key="analyst", persona_name="A"
    )
    ha = await _h(info_a)

    # User B creates a persona, then sets interest_tags to include words that
    # will overlap with A's post keywords. We need tag ids; easiest path is
    # to create a public post from A first to mint the tags, then assign
    # those tag ids to B's persona.
    r = await client.post(
        "/v1/posts",
        json={
            "persona_id": persona_a,
            "content_raw": "여행 좋아하는 사람 여행 추천 여행 코스 여행 정보",
            "visibility": "public",
        },
        headers=ha,
    )
    assert r.status_code == 201
    minted_tags = r.json()["tags"]
    assert minted_tags, "mediator stub should have produced tags"
    overlap_tag_ids = [t["id"] for t in minted_tags[:2]]

    info_b = await signup_and_login()
    hb = await _h(info_b)
    r = await client.post(
        "/v1/personas",
        json={
            "name": "여행러",
            "model_key": "friend",
            "interest_tag_ids": overlap_tag_ids,
        },
        headers=hb,
    )
    assert r.status_code == 201, r.text

    # Now A sends a PRIVATE post with the same theme
    r = await client.post(
        "/v1/posts",
        json={
            "persona_id": persona_a,
            "content_raw": "여행 비공개 메시지 여행",
            "visibility": "private",
        },
        headers=ha,
    )
    assert r.status_code == 201

    # B's inbox should have at least one delivery now
    r = await client.get("/v1/inbox", headers=hb)
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) >= 1, f"expected delivery in B's inbox, got: {items}"
    item = items[0]
    assert item["source_persona"]["id"] == persona_a
    assert item["seen_at"] is None

    # Mark seen
    r = await client.post(f"/v1/inbox/{item['distribution_id']}/seen", headers=hb)
    assert r.status_code == 204

    r = await client.get("/v1/inbox", headers=hb)
    assert r.json()["items"][0]["seen_at"] is not None


async def test_feed_pagination_cursor(client, signup_and_login):  # type: ignore[no-untyped-def]
    info, persona_id = await _make_user_with_persona(client, signup_and_login)
    h = await _h(info)

    for i in range(5):
        r = await client.post(
            "/v1/posts",
            json={
                "persona_id": persona_id,
                "content_raw": f"포스트 번호 {i} 페이지네이션 테스트",
                "visibility": "public",
            },
            headers=h,
        )
        assert r.status_code == 201

    # First page (limit=2)
    r = await client.get("/v1/feed?limit=2", headers=h)
    assert r.status_code == 200
    page1 = r.json()
    assert len(page1["items"]) == 2
    assert page1["next_cursor"] is not None

    # Second page
    r = await client.get(f"/v1/feed?limit=2&cursor={page1['next_cursor']}", headers=h)
    page2 = r.json()
    assert len(page2["items"]) == 2

    # Pages don't overlap
    ids1 = {it["id"] for it in page1["items"]}
    ids2 = {it["id"] for it in page2["items"]}
    assert ids1.isdisjoint(ids2)
