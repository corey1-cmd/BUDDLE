"""Stage 4 leukocyte + importance integration tests (full pipeline).

Uses the stub ethics classifier (deterministic) and stub embeddings. Verifies:
  - flagged content raises an ethics alert + applies a negative importance delta
  - high-severity content is suppressed (excluded from public feed)
  - private distribution adds positive 'mention' importance
  - like / report endpoints move importance the right direction
  - reporting raises an alert visible in the admin queue
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select, update

pytestmark = pytest.mark.asyncio


def _h(info: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {info['access_token']}"}


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


async def _persona(client, info, *, model_key="analyst", name="p"):  # type: ignore[no-untyped-def]
    r = await client.post(
        "/v1/personas", json={"name": name, "model_key": model_key}, headers=_h(info)
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ── ethics suppression + penalty ─────────────────────────────────────────


async def test_high_severity_post_is_suppressed_and_penalized(  # type: ignore[no-untyped-def]
    client, signup_and_login, db_session
):
    info = await signup_and_login()
    persona_id = await _persona(client, info)

    r = await client.post(
        "/v1/posts",
        json={
            "persona_id": persona_id,
            "content_raw": "자살 관련 위험한 내용입니다",
            "visibility": "public",
        },
        headers=_h(info),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    post_id = body["id"]
    assert body["is_suppressed"] is True

    # Importance should be negative (high-severity penalty)
    from buddle.db.models.importance import ImportanceScore

    score = await db_session.get(ImportanceScore, uuid.UUID(post_id))
    await db_session.refresh(score)
    assert float(score.normalized) < 0

    # An ethics alert should exist for this post
    from buddle.db.models.ethics_alert import EthicsAlert

    alerts = (
        (
            await db_session.execute(
                select(EthicsAlert).where(EthicsAlert.target_id == uuid.UUID(post_id))
            )
        )
        .scalars()
        .all()
    )
    assert len(alerts) >= 1
    assert alerts[0].severity == "high"


async def test_suppressed_post_excluded_from_feed(client, signup_and_login):  # type: ignore[no-untyped-def]
    info = await signup_and_login()
    persona_id = await _persona(client, info)

    # one clean public post, one flagged
    r_clean = await client.post(
        "/v1/posts",
        json={
            "persona_id": persona_id,
            "content_raw": "평범하고 깨끗한 게시물 산책 일상",
            "visibility": "public",
        },
        headers=_h(info),
    )
    clean_id = r_clean.json()["id"]

    r_bad = await client.post(
        "/v1/posts",
        json={
            "persona_id": persona_id,
            "content_raw": "폭탄 테러 위협 내용",
            "visibility": "public",
        },
        headers=_h(info),
    )
    bad_id = r_bad.json()["id"]
    assert r_bad.json()["is_suppressed"] is True

    r = await client.get("/v1/feed?limit=50", headers=_h(info))
    ids = {item["id"] for item in r.json()["items"]}
    assert clean_id in ids
    assert bad_id not in ids


async def test_clean_post_not_suppressed(client, signup_and_login):  # type: ignore[no-untyped-def]
    info = await signup_and_login()
    persona_id = await _persona(client, info)
    r = await client.post(
        "/v1/posts",
        json={
            "persona_id": persona_id,
            "content_raw": "좋은 하루 보내세요 커피 한잔",
            "visibility": "public",
        },
        headers=_h(info),
    )
    assert r.json()["is_suppressed"] is False


# ── like / report ────────────────────────────────────────────────────────


async def test_like_increases_importance(client, signup_and_login):  # type: ignore[no-untyped-def]
    author = await signup_and_login()
    persona_id = await _persona(client, author)
    r = await client.post(
        "/v1/posts",
        json={
            "persona_id": persona_id,
            "content_raw": "괜찮은 글 음악 추천",
            "visibility": "public",
        },
        headers=_h(author),
    )
    post_id = r.json()["id"]

    liker = await signup_and_login()
    r = await client.post(f"/v1/posts/{post_id}/react", headers=_h(liker))
    assert r.status_code == 200, r.text
    assert r.json()["normalized_importance"] > 0


async def test_report_decreases_importance_and_raises_alert(  # type: ignore[no-untyped-def]
    client, signup_and_login, db_session
):
    author = await signup_and_login()
    persona_id = await _persona(client, author)
    r = await client.post(
        "/v1/posts",
        json={
            "persona_id": persona_id,
            "content_raw": "논쟁적인 글 일상",
            "visibility": "public",
        },
        headers=_h(author),
    )
    post_id = r.json()["id"]

    reporter = await signup_and_login()
    r = await client.post(
        f"/v1/posts/{post_id}/report",
        json={"reason": "부적절한 내용"},
        headers=_h(reporter),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["normalized_importance"] < 0
    assert body["alert_id"]


async def test_react_on_missing_post_404(client, signup_and_login):  # type: ignore[no-untyped-def]
    info = await signup_and_login()
    r = await client.post(f"/v1/posts/{uuid.uuid4()}/react", headers=_h(info))
    assert r.status_code == 404


# ── mention boost via distribution ───────────────────────────────────────


async def test_private_distribution_adds_mention_importance(  # type: ignore[no-untyped-def]
    client, signup_and_login, db_session
):
    sender = await signup_and_login()
    sender_persona = await _persona(client, sender, name="송신", model_key="analyst")

    # Mint tags through a public post, assign to a receiver so it matches.
    r = await client.post(
        "/v1/posts",
        json={
            "persona_id": sender_persona,
            "content_raw": "여행 여행 여행 코스 여행 추천",
            "visibility": "public",
        },
        headers=_h(sender),
    )
    tag_ids = [t["id"] for t in r.json()["tags"][:3]]

    receiver = await signup_and_login()
    await client.post(
        "/v1/personas",
        json={"name": "여행러", "model_key": "friend", "interest_tag_ids": tag_ids},
        headers=_h(receiver),
    )

    # Private post that will be distributed -> mention boosts importance
    r = await client.post(
        "/v1/posts",
        json={
            "persona_id": sender_persona,
            "content_raw": "여행 비공개 여행 코스 공유",
            "visibility": "private",
        },
        headers=_h(sender),
    )
    assert r.status_code == 201
    post_id = r.json()["id"]

    # Count contributions for this post: should include >=1 'mention'
    from buddle.db.models.importance import ImportanceContribution

    mention_count = await db_session.scalar(
        select(func.count(ImportanceContribution.id)).where(
            ImportanceContribution.post_id == uuid.UUID(post_id),
            ImportanceContribution.source == "mention",
        )
    )
    assert int(mention_count or 0) >= 1


async def test_importance_contributions_are_append_only_log(  # type: ignore[no-untyped-def]
    client, signup_and_login, db_session
):
    """raw_score must equal the SUM of all logged contributions."""
    author = await signup_and_login()
    persona_id = await _persona(client, author)
    r = await client.post(
        "/v1/posts",
        json={
            "persona_id": persona_id,
            "content_raw": "합산 검증용 게시물",
            "visibility": "public",
        },
        headers=_h(author),
    )
    post_id = uuid.UUID(r.json()["id"])

    # two likes
    for _ in range(2):
        liker = await signup_and_login()
        await client.post(f"/v1/posts/{post_id}/react", headers=_h(liker))

    from buddle.db.models.importance import ImportanceContribution, ImportanceScore

    total = await db_session.scalar(
        select(func.coalesce(func.sum(ImportanceContribution.delta), 0.0)).where(
            ImportanceContribution.post_id == post_id
        )
    )
    score = await db_session.get(ImportanceScore, post_id)
    await db_session.refresh(score)
    assert float(score.raw_score) == pytest.approx(float(total))
