"""Profile service tests — contracts (no DB) + DB-backed sovereignty flows.

The contract section includes the STRUCTURAL PRIVACY test: the schema must
not contain demographic / protected-attribute columns — connection-only
profiling enforced at the table level, not by policy prose.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

# ── contracts (no DB) ──────────────────────────────────────────────────────


def test_profile_model_columns_and_structural_privacy():
    from buddle.db.models.user_profile import UserProfile

    cols = set(UserProfile.__table__.columns.keys())
    assert {
        "user_id",
        "o",
        "c",
        "e",
        "a",
        "n",
        "confidence",
        "evidence_count",
        "interests_emb",
        "profile_opt_out",
        "is_user_edited",
    } <= cols
    # 연결 전용 프로파일링: 보호속성·인구통계 컬럼은 존재 자체가 금지.
    forbidden = {
        "gender",
        "sex",
        "age",
        "birth",
        "race",
        "ethnicity",
        "religion",
        "nationality",
        "disability",
        "orientation",
    }
    assert not any(any(f in col for f in forbidden) for col in cols)


def test_update_schema_rejects_out_of_range_traits():
    from buddle.schemas.profile import ProfileUpdate

    with pytest.raises(ValidationError):
        ProfileUpdate(o=1.5)
    with pytest.raises(ValidationError):
        ProfileUpdate(n=-0.1)


def test_sovereignty_routes_registered():
    from buddle.main import app

    methods_by_path: dict[str, set[str]] = {}
    for r in app.routes:
        if getattr(r, "path", "") == "/v1/me/profile":
            methods_by_path.setdefault(r.path, set()).update(getattr(r, "methods", set()))
    assert {"GET", "PATCH", "DELETE"} <= methods_by_path.get("/v1/me/profile", set())


def test_migration_0018_chains_after_0017():
    from pathlib import Path

    src = Path("migrations/versions/20260612_1100_0018_user_profiles.py").read_text(
        encoding="utf-8"
    )
    assert 'revision: str = "0018"' in src
    assert 'down_revision: str | None = "0017"' in src


# ── DB-backed sovereignty flows ────────────────────────────────────────────


async def _make_user(db) -> uuid.UUID:  # type: ignore[no-untyped-def]
    from buddle.db.models.user import User

    user = User(email=f"prof_{uuid.uuid4().hex[:10]}@test.local", password_hash="x" * 32)
    db.add(user)
    await db.commit()
    return user.id


async def test_observation_accumulates_evidence_and_confidence(db_session):  # type: ignore[no-untyped-def]
    from buddle.services import profile_service

    user_id = await _make_user(db_session)
    applied = await profile_service.observe_text(
        db_session, user_id=user_id, text="요즘 너무 불안하고 걱정이 많아"
    )
    assert applied
    profile = await profile_service.get_profile(db_session, user_id)
    assert profile is not None
    assert profile.evidence_count == 1
    assert profile.confidence > 0.0
    assert profile.n > 0.5  # nudged toward the anxiety signal, boundedly

    # Neutral text is not evidence: nothing advances.
    applied2 = await profile_service.observe_text(
        db_session, user_id=user_id, text="내일 점심에 김밥 먹을까 한다"
    )
    assert not applied2
    await db_session.refresh(profile)
    assert profile.evidence_count == 1


async def test_opt_out_stops_observation(db_session):  # type: ignore[no-untyped-def]
    from buddle.services import profile_service

    user_id = await _make_user(db_session)
    await profile_service.update_profile(db_session, user_id=user_id, profile_opt_out=True)
    applied = await profile_service.observe_text(
        db_session, user_id=user_id, text="불안하고 걱정돼"
    )
    assert not applied
    profile = await profile_service.get_profile(db_session, user_id)
    assert profile is not None and profile.evidence_count == 0


async def test_user_edit_freezes_automatic_updates(db_session):  # type: ignore[no-untyped-def]
    from buddle.services import profile_service

    user_id = await _make_user(db_session)
    edited = await profile_service.update_profile(db_session, user_id=user_id, traits={"e": 0.9})
    assert edited.is_user_edited and edited.confidence == 1.0 and abs(edited.e - 0.9) < 1e-6

    await profile_service.observe_text(
        db_session, user_id=user_id, text="요즘 모임도 파티도 다 싫고 불안해"
    )
    profile = await profile_service.get_profile(db_session, user_id)
    assert profile is not None
    assert abs(profile.e - 0.9) < 1e-6  # 사용자의 말이 최종 — frozen


async def test_delete_then_read_returns_neutral(db_session):  # type: ignore[no-untyped-def]
    from buddle.services import profile_service

    user_id = await _make_user(db_session)
    await profile_service.observe_text(db_session, user_id=user_id, text="새로운 게 궁금해")
    assert await profile_service.delete_profile(db_session, user_id)
    assert await profile_service.get_profile(db_session, user_id) is None
    # Idempotent: deleting again is still fine.
    assert not await profile_service.delete_profile(db_session, user_id)


async def test_interest_centroid_updates_from_embedding(db_session):  # type: ignore[no-untyped-def]
    from buddle.ai.embeddings.base import EMBED_DIM
    from buddle.services import profile_service

    user_id = await _make_user(db_session)
    emb = [0.0] * EMBED_DIM
    emb[0] = 1.0
    assert await profile_service.observe_interest_embedding(
        db_session, user_id=user_id, embedding=emb
    )
    profile = await profile_service.get_profile(db_session, user_id)
    assert profile is not None and profile.interests_emb is not None
    assert abs(float(profile.interests_emb[0]) - 1.0) < 1e-6
