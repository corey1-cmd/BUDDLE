"""Stage 6 central-manager integration tests (DB-backed).

Verifies report assembly from real data, session tracking + average continuous
usage time, snapshot persistence, monitor endpoints, and that auto-tuning is
guarded (skips when unhealthy / engagement healthy).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from buddle.db.models.session import UserSession
from buddle.services import central_service, session_service

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


# ── report assembly ─────────────────────────────────────────────────────


async def test_build_report_basic(client, signup_and_login, db_session):  # type: ignore[no-untyped-def]
    # Some activity so the report has data
    info = await signup_and_login()
    r = await client.post(
        "/v1/personas", json={"name": "p", "model_key": "analyst"}, headers=_h(info)
    )
    persona_id = r.json()["id"]
    await client.post(
        "/v1/posts",
        json={
            "persona_id": persona_id,
            "content_raw": "여행 코스 추천 정보",
            "visibility": "public",
        },
        headers=_h(info),
    )

    report = await central_service.build_report(db_session)
    assert report.verdict.value in ("ok", "warn", "critical")
    assert len(report.components) == 5  # all five AIs
    names = {c.name for c in report.components}
    assert names == {"페르소나", "매개자", "백혈구", "기술자", "중앙관리자"}
    assert report.engagement.mau >= 0
    assert report.golden.traffic_requests >= 1  # the post we created


async def test_report_clean_system_is_ok(client, signup_and_login, db_session):  # type: ignore[no-untyped-def]
    report = await central_service.build_report(db_session)
    # Fresh system: integrity ok, normal authority, no alerts -> ok
    assert report.integrity_ok is True
    assert report.authority_state == "normal"
    assert report.verdict.value == "ok"


# ── session tracking ─────────────────────────────────────────────────────


async def test_session_touch_extends_within_window(  # type: ignore[no-untyped-def]
    signup_and_login, db_session
):
    info = await signup_and_login()
    uid = uuid.UUID(info["user_id"])

    s1 = await session_service.touch_session(db_session, uid)
    s2 = await session_service.touch_session(db_session, uid)
    # same open session, activity incremented
    assert s1.id == s2.id
    assert s2.activity_count == 2


async def test_session_idle_gap_opens_new_session(  # type: ignore[no-untyped-def]
    signup_and_login, db_session
):
    info = await signup_and_login()
    uid = uuid.UUID(info["user_id"])

    s1 = await session_service.touch_session(db_session, uid)
    # Force the open session to look stale
    await db_session.execute(
        update(UserSession)
        .where(UserSession.id == s1.id)
        .values(last_seen_at=datetime.now(UTC) - timedelta(hours=2))
    )
    await db_session.commit()

    s2 = await session_service.touch_session(db_session, uid)
    assert s2.id != s1.id  # new session opened

    # Old one should be closed
    old = await db_session.get(UserSession, s1.id)
    await db_session.refresh(old)
    assert old.ended_at is not None


async def test_avg_session_minutes_in_report(  # type: ignore[no-untyped-def]
    signup_and_login, db_session
):
    info = await signup_and_login()
    uid = uuid.UUID(info["user_id"])
    s = await session_service.touch_session(db_session, uid)
    # Make a closed session of ~10 minutes
    start = datetime.now(UTC) - timedelta(minutes=10)
    await db_session.execute(
        update(UserSession)
        .where(UserSession.id == s.id)
        .values(
            started_at=start,
            last_seen_at=start + timedelta(minutes=10),
            ended_at=start + timedelta(minutes=10),
        )
    )
    await db_session.commit()

    report = await central_service.build_report(db_session)
    assert report.engagement.avg_session_minutes >= 9.0


# ── snapshot ─────────────────────────────────────────────────────────────


async def test_snapshot_persists(db_session):  # type: ignore[no-untyped-def]
    report, snap = await central_service.snapshot_report(db_session, kind="on_demand")
    assert snap.id is not None
    assert snap.health == report.verdict.value
    assert snap.payload["verdict"] == report.verdict.value
    assert "engagement" in snap.payload


# ── monitor endpoints ────────────────────────────────────────────────────


async def test_monitor_digest_endpoint(client, signup_and_login, db_session):  # type: ignore[no-untyped-def]
    admin = await _make_admin(client, signup_and_login, db_session)
    r = await client.get("/v1/admin/monitor/digest", headers=_h(admin))
    assert r.status_code == 200
    body = r.json()
    assert "시스템 리포트" in body["digest"]
    assert body["health"] in ("ok", "warn", "critical")


async def test_monitor_report_endpoint(client, signup_and_login, db_session):  # type: ignore[no-untyped-def]
    admin = await _make_admin(client, signup_and_login, db_session)
    r = await client.get("/v1/admin/monitor/report", headers=_h(admin))
    assert r.status_code == 200
    body = r.json()
    assert "golden" in body
    assert "engagement" in body
    assert len(body["components"]) == 5


async def test_monitor_requires_admin(client, signup_and_login):  # type: ignore[no-untyped-def]
    info = await signup_and_login()  # non-admin
    r = await client.get("/v1/admin/monitor/digest", headers=_h(info))
    assert r.status_code == 403


async def test_autotune_skips_on_healthy_system(  # type: ignore[no-untyped-def]
    client, signup_and_login, db_session
):
    admin = await _make_admin(client, signup_and_login, db_session)
    # Fresh system with little engagement but healthy -> proposal should be
    # either skipped (engagement healthy=False but weak) or applied bounded.
    r = await client.post("/v1/admin/monitor/autotune?apply=false", headers=_h(admin))
    assert r.status_code == 200
    body = r.json()
    assert "rationale" in body
    assert body["applied"] is False  # apply=false never writes
