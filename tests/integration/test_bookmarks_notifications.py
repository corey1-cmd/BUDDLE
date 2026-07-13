"""Integration tests: bookmarks (저장), notifications (알림), feed search, trending.

Covers the SNS-basics layer added on top of the plaza:
  - bookmark toggle idempotency + private reading list
  - like/comment -> notification to the post owner (never to yourself)
  - unread badge count, mark-read scoping (can't touch another user's rows)
  - server-side feed text search (?q=) incl. wildcard escaping
  - user-facing trending tags
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


async def _public_post(client, headers, persona_id, text) -> str:  # type: ignore[no-untyped-def]
    r = await client.post(
        "/v1/posts",
        json={"persona_id": persona_id, "content_raw": text, "visibility": "public"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ── bookmarks ────────────────────────────────────────────────────────────


async def test_bookmark_toggle_idempotent(client, signup_and_login):  # type: ignore[no-untyped-def]
    info_a, persona_a = await _make_user_with_persona(client, signup_and_login)
    info_b = await signup_and_login()
    ha, hb = await _h(info_a), await _h(info_b)
    post_id = await _public_post(client, ha, persona_a, "저장해두고 싶은 글")

    r = await client.put(f"/v1/plaza/posts/{post_id}/bookmark", headers=hb)
    assert r.status_code == 200
    assert r.json() == {"bookmarked": True, "newly_created": True}

    # Second save is a no-op, not an error and not a duplicate.
    r = await client.put(f"/v1/plaza/posts/{post_id}/bookmark", headers=hb)
    assert r.json() == {"bookmarked": True, "newly_created": False}

    r = await client.delete(f"/v1/plaza/posts/{post_id}/bookmark", headers=hb)
    assert r.json() == {"bookmarked": False, "removed": True}
    r = await client.delete(f"/v1/plaza/posts/{post_id}/bookmark", headers=hb)
    assert r.json() == {"bookmarked": False, "removed": False}


async def test_bookmark_list_is_private_reading_list(client, signup_and_login):  # type: ignore[no-untyped-def]
    info_a, persona_a = await _make_user_with_persona(client, signup_and_login)
    info_b = await signup_and_login()
    ha, hb = await _h(info_a), await _h(info_b)
    post_id = await _public_post(client, ha, persona_a, "북마크 목록 확인용 글")

    await client.put(f"/v1/plaza/posts/{post_id}/bookmark", headers=hb)

    r = await client.get("/v1/bookmarks", headers=hb)
    assert r.status_code == 200
    ids = [it["id"] for it in r.json()]
    assert post_id in ids
    # Items carry the feed shape (renderable by the same card component).
    assert "content_transformed" in r.json()[0]
    assert "tags" in r.json()[0]

    # The list is mine only — the author (who saved nothing) sees an empty list.
    r = await client.get("/v1/bookmarks", headers=ha)
    assert r.json() == []

    # Unsave -> drops out.
    await client.delete(f"/v1/plaza/posts/{post_id}/bookmark", headers=hb)
    r = await client.get("/v1/bookmarks", headers=hb)
    assert post_id not in [it["id"] for it in r.json()]


async def test_bookmark_unknown_post_404(client, signup_and_login):  # type: ignore[no-untyped-def]
    info = await signup_and_login()
    h = await _h(info)
    r = await client.put("/v1/plaza/posts/00000000-0000-0000-0000-000000000000/bookmark", headers=h)
    assert r.status_code == 404


# ── notifications ────────────────────────────────────────────────────────


async def test_like_and_comment_notify_post_owner(client, signup_and_login):  # type: ignore[no-untyped-def]
    info_a, persona_a = await _make_user_with_persona(client, signup_and_login)
    info_b = await signup_and_login()
    ha, hb = await _h(info_a), await _h(info_b)
    post_id = await _public_post(client, ha, persona_a, "반응을 받아볼 글입니다")

    await client.put(f"/v1/plaza/posts/{post_id}/like", headers=hb)
    r = await client.post(
        f"/v1/plaza/posts/{post_id}/comments",
        json={"kind": "question", "content": "이 생각은 어디서 나왔나요?"},
        headers=hb,
    )
    assert r.status_code == 201, r.text

    # Owner sees exactly two unread events (like + comment), newest first.
    r = await client.get("/v1/notifications/unread-count", headers=ha)
    assert r.json()["count"] == 2
    r = await client.get("/v1/notifications", headers=ha)
    rows = r.json()
    kinds = {n["kind"] for n in rows}
    assert kinds == {"like", "comment"}
    comment_notif = next(n for n in rows if n["kind"] == "comment")
    assert "어디서 나왔나요" in comment_notif["preview"]
    assert comment_notif["post_id"] == post_id
    assert all(n["read_at"] is None for n in rows)

    # A repeated like must not duplicate the notification.
    await client.put(f"/v1/plaza/posts/{post_id}/like", headers=hb)
    r = await client.get("/v1/notifications/unread-count", headers=ha)
    assert r.json()["count"] == 2


async def test_self_actions_do_not_notify(client, signup_and_login):  # type: ignore[no-untyped-def]
    info_a, persona_a = await _make_user_with_persona(client, signup_and_login)
    ha = await _h(info_a)
    post_id = await _public_post(client, ha, persona_a, "혼자 반응해보는 글")

    await client.put(f"/v1/plaza/posts/{post_id}/like", headers=ha)
    await client.post(
        f"/v1/plaza/posts/{post_id}/comments",
        json={"kind": "empathize", "content": "스스로 덧붙이는 말"},
        headers=ha,
    )
    r = await client.get("/v1/notifications/unread-count", headers=ha)
    assert r.json()["count"] == 0


async def test_mark_read_is_user_scoped(client, signup_and_login):  # type: ignore[no-untyped-def]
    info_a, persona_a = await _make_user_with_persona(client, signup_and_login)
    info_b = await signup_and_login()
    ha, hb = await _h(info_a), await _h(info_b)
    post_id = await _public_post(client, ha, persona_a, "읽음 처리 스코프 확인")

    await client.put(f"/v1/plaza/posts/{post_id}/like", headers=hb)
    notif_id = (await client.get("/v1/notifications", headers=ha)).json()[0]["id"]

    # Another user cannot mark my notification read.
    r = await client.post(f"/v1/notifications/{notif_id}/read", headers=hb)
    assert r.json() == {"updated": 0}

    # I can; a second mark is an idempotent no-op.
    r = await client.post(f"/v1/notifications/{notif_id}/read", headers=ha)
    assert r.json() == {"updated": 1}
    r = await client.post(f"/v1/notifications/{notif_id}/read", headers=ha)
    assert r.json() == {"updated": 0}


async def test_read_all_and_unread_filter(client, signup_and_login):  # type: ignore[no-untyped-def]
    info_a, persona_a = await _make_user_with_persona(client, signup_and_login)
    info_b = await signup_and_login()
    ha, hb = await _h(info_a), await _h(info_b)
    p1 = await _public_post(client, ha, persona_a, "읽음 일괄 처리 첫 글")
    p2 = await _public_post(client, ha, persona_a, "읽음 일괄 처리 둘째 글")
    await client.put(f"/v1/plaza/posts/{p1}/like", headers=hb)
    await client.put(f"/v1/plaza/posts/{p2}/like", headers=hb)

    r = await client.get("/v1/notifications?unread_only=true", headers=ha)
    assert len(r.json()) == 2

    r = await client.post("/v1/notifications/read-all", headers=ha)
    assert r.json()["updated"] == 2
    r = await client.get("/v1/notifications/unread-count", headers=ha)
    assert r.json()["count"] == 0
    # History stays (unread filter empties, full list doesn't).
    assert (await client.get("/v1/notifications?unread_only=true", headers=ha)).json() == []
    assert len((await client.get("/v1/notifications", headers=ha)).json()) == 2


# ── feed search ──────────────────────────────────────────────────────────


async def test_feed_search_server_side(client, signup_and_login):  # type: ignore[no-untyped-def]
    info, persona_id = await _make_user_with_persona(client, signup_and_login)
    h = await _h(info)
    post_id = await _public_post(client, h, persona_id, "쿼리로만 찾을 수 있는 유일무이글자열")

    r = await client.get("/v1/feed?q=유일무이글자열", headers=h)
    assert r.status_code == 200
    assert any(it["id"] == post_id for it in r.json()["items"])

    r = await client.get("/v1/feed?q=절대없는검색어zzz", headers=h)
    assert r.json()["items"] == []


async def test_feed_search_escapes_wildcards(client, signup_and_login):  # type: ignore[no-untyped-def]
    """A literal % in q must not become a match-everything wildcard."""
    info, persona_id = await _make_user_with_persona(client, signup_and_login)
    h = await _h(info)
    await _public_post(client, h, persona_id, "와일드카드 이스케이프 확인용 글")

    r = await client.get("/v1/feed?q=%25%25%25", headers=h)  # q=%%%
    assert r.status_code == 200
    assert r.json()["items"] == []


# ── trending tags ────────────────────────────────────────────────────────


async def test_trending_tags_counts_public_posts(client, signup_and_login):  # type: ignore[no-untyped-def]
    info, persona_id = await _make_user_with_persona(client, signup_and_login)
    h = await _h(info)
    r = await client.post(
        "/v1/posts",
        json={
            "persona_id": persona_id,
            "content_raw": "트렌딩 화제 집계 확인 산책 산책",
            "visibility": "public",
        },
        headers=h,
    )
    tags = [t["name"] for t in r.json()["tags"]]
    assert tags

    r = await client.get("/v1/tags/trending?days=7&limit=10", headers=h)
    assert r.status_code == 200
    trend = r.json()
    assert trend, "the fresh post's tags should trend inside the window"
    by_name = {t["name"]: t for t in trend}
    assert any(name in by_name for name in tags)
    for t in trend:
        assert t["post_count"] >= 1
        assert set(t) == {"id", "name", "post_count"}


async def test_trending_requires_auth(client):  # type: ignore[no-untyped-def]
    r = await client.get("/v1/tags/trending")
    assert r.status_code == 401
