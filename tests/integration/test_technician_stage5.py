"""Stage 5 technician integration tests (DB-backed).

Verifies the integrity chain end-to-end through the service + DB, including
detection of an in-database tamper, and the dynamic-authority state machine
(NORMAL -> TECH_ELEVATED) driven by unverified vs verified transformations.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, update

from buddle.db.models.enums import AIRole, TransformationTypeEnum
from buddle.db.models.transformation_log import TransformationLog
from buddle.services import technician_service

pytestmark = pytest.mark.asyncio


async def _record(db, *, magnitude, verified=False, source=AIRole.MEDIATOR):  # type: ignore[no-untyped-def]
    return await technician_service.record_transformation(
        db,
        source_ai=source,
        target_data_id=uuid.uuid4(),
        target_data_type="post",
        magnitude=magnitude,
        transformation_type=TransformationTypeEnum.WEIGHT_UPDATE,
        verified=verified,
        commit=True,
    )


async def test_chain_records_get_sequential_hashes(db_session):  # type: ignore[no-untyped-def]
    t1 = await _record(db_session, magnitude=1.0, verified=True)
    t2 = await _record(db_session, magnitude=2.0, verified=True)

    assert t1.sequence is not None and t2.sequence is not None
    assert t2.sequence == t1.sequence + 1
    # t2 chains onto t1
    assert t2.prev_hash == t1.entry_hash
    assert len(t1.entry_hash) == 64


async def test_chain_verifies_clean(db_session):  # type: ignore[no-untyped-def]
    for m in (1.0, 2.0, 3.0):
        await _record(db_session, magnitude=m, verified=True)

    result = await technician_service.verify_integrity_chain(db_session)
    assert result.ok, result.detail
    assert result.checked >= 3


async def test_in_db_tamper_is_detected(db_session):  # type: ignore[no-untyped-def]
    targets = []
    for m in (1.0, 2.0, 3.0):
        t = await _record(db_session, magnitude=m, verified=True)
        targets.append(t)

    # Simulate an attacker editing a row's magnitude directly in the DB,
    # WITHOUT recomputing the hash chain.
    victim = targets[1]
    await db_session.execute(
        update(TransformationLog).where(TransformationLog.id == victim.id).values(magnitude=999.0)
    )
    await db_session.commit()

    result = await technician_service.verify_integrity_chain(db_session)
    assert not result.ok
    assert result.first_invalid_sequence == victim.sequence


async def test_authority_normal_then_elevated(db_session):  # type: ignore[no-untyped-def]
    # Baseline recompute -> NORMAL
    comp = await technician_service.recompute_authority(db_session)
    assert comp.snapshot.state.value == "normal"

    # Create many high-magnitude UNVERIFIED transformations to debit the
    # central manager below the technician. Default config:
    #   central_base=100, debit=10, high_magnitude_threshold=5
    #   technician_base=0, credit=10
    # Need central < technician. With 0 restorations technician=0, so we need
    # central < 0 -> >10 unverified high-magnitude changes.
    for _ in range(12):
        await _record(db_session, magnitude=10.0, verified=False)

    comp = await technician_service.recompute_authority(db_session)
    assert comp.snapshot.unverified_count >= 12
    assert comp.snapshot.central < 0
    assert comp.snapshot.state.value == "tech_elevated"
    assert comp.state_changed is True

    # Verifying transformations (restorations) credits the technician but also
    # REMOVES them from the unverified count, so the system heals back toward
    # NORMAL as the technician asserts control.
    rows = list(
        (
            await db_session.execute(
                select(TransformationLog).where(TransformationLog.verified.is_(False))
            )
        ).scalars()
    )
    for t in rows:
        await technician_service.verify_transformation(db_session, t.id)

    final = await technician_service.recompute_authority(db_session)
    assert final.snapshot.unverified_count == 0
    assert final.snapshot.state.value == "normal"


async def test_low_magnitude_unverified_does_not_debit(db_session):  # type: ignore[no-untyped-def]
    # magnitude below threshold (5) shouldn't count as suspicious
    for _ in range(20):
        await _record(db_session, magnitude=1.0, verified=False)

    comp = await technician_service.recompute_authority(db_session)
    assert comp.snapshot.unverified_count == 0
    assert comp.snapshot.state.value == "normal"


async def test_verify_missing_transformation_404(db_session):  # type: ignore[no-untyped-def]
    from buddle.core.exceptions import NotFound

    with pytest.raises(NotFound):
        await technician_service.verify_transformation(db_session, uuid.uuid4())


async def test_distribution_records_transformation(  # type: ignore[no-untyped-def]
    client, signup_and_login, db_session
):
    """A private post that gets distributed should append a MEDIATOR INJECT
    transformation to the chain."""
    sender = await signup_and_login()
    sh = {"Authorization": f"Bearer {sender['access_token']}"}
    r = await client.post("/v1/personas", json={"name": "송신", "model_key": "analyst"}, headers=sh)
    sender_persona = r.json()["id"]

    r = await client.post(
        "/v1/posts",
        json={
            "persona_id": sender_persona,
            "content_raw": "여행 여행 여행 코스 추천 정보",
            "visibility": "public",
        },
        headers=sh,
    )
    tag_ids = [t["id"] for t in r.json()["tags"][:3]]

    receiver = await signup_and_login()
    rh = {"Authorization": f"Bearer {receiver['access_token']}"}
    await client.post(
        "/v1/personas",
        json={"name": "여행러", "model_key": "friend", "interest_tag_ids": tag_ids},
        headers=rh,
    )

    r = await client.post(
        "/v1/posts",
        json={
            "persona_id": sender_persona,
            "content_raw": "여행 비공개 여행 코스",
            "visibility": "private",
        },
        headers=sh,
    )
    assert r.status_code == 201

    # An INJECT transformation by the mediator should now exist
    rows = list(
        (
            await db_session.execute(
                select(TransformationLog).where(
                    TransformationLog.source_ai == AIRole.MEDIATOR,
                    TransformationLog.transformation_type == TransformationTypeEnum.INJECT,
                )
            )
        ).scalars()
    )
    assert len(rows) >= 1

    # And the chain must still verify
    result = await technician_service.verify_integrity_chain(db_session)
    assert result.ok, result.detail
