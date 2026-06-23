"""Technician service — integrity chain maintenance + dynamic authority.

Responsibilities:
  1. record_transformation: append a transformation to the HMAC hash chain.
     Sequence allocation is serialized with a Postgres advisory lock so two
     concurrent writers can't claim the same sequence (which would fork the
     chain). The entry is hashed over the previous entry's hash.
  2. verify_chain: recompute the whole chain and report the first invalid
     sequence — the tamper-evidence guarantee.
  3. recompute_authority: count unverified vs verified-restoration
     transformations, recompute central/technician authority, and persist the
     resulting NORMAL / TECH_ELEVATED state. Authorization fails CLOSED.
  4. verify_transformation: mark a single transformation verified (a technician
     "restoration"), then recompute authority.

A change is "unverified/suspicious" when its magnitude exceeds the high-
magnitude threshold AND it has not been verified by the technician. Those are
what debit the central manager toward a TECH_ELEVATED takeover.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from buddle.ai.technician import (
    GENESIS_HASH,
    AuthorityParams,
    AuthoritySnapshot,
    ChainRecord,
    ChainVerification,
    compute_entry_hash,
    snapshot,
    verify_chain,
)
from buddle.ai.technician.authority import AuthorityState
from buddle.config import get_settings
from buddle.core.logging import get_logger
from buddle.db.models.authority_token import SystemAuthorityState
from buddle.db.models.enums import AIRole, AuthorityStateEnum, TransformationTypeEnum
from buddle.db.models.transformation_log import TransformationLog

log = get_logger(__name__)

# Postgres advisory lock key for serializing chain-sequence allocation.
# Arbitrary but stable 64-bit constant unique to this chain.
_CHAIN_LOCK_KEY = 0x6275_6464_6C65_0001  # "budle" + 1


def _integrity_key() -> bytes:
    return get_settings().integrity_hmac_key.get_secret_value().encode("utf-8")


def _authority_params() -> AuthorityParams:
    s = get_settings()
    return AuthorityParams(
        central_base=s.authority_central_base,
        technician_base=s.authority_technician_base,
        debit_unverified=s.authority_debit_unverified,
        credit_restoration=s.authority_credit_restoration,
    )


def _to_chain_record(t: TransformationLog) -> ChainRecord:
    return ChainRecord(
        sequence=int(t.sequence) if t.sequence is not None else 0,
        source_ai=t.source_ai.value,
        source_instance_id=str(t.source_instance_id) if t.source_instance_id else None,
        target_data_id=str(t.target_data_id),
        target_data_type=t.target_data_type,
        magnitude=float(t.magnitude),
        transformation_type=t.transformation_type.value,
        created_at=t.created_at.isoformat(),
    )


async def record_transformation(
    db: AsyncSession,
    *,
    source_ai: AIRole,
    target_data_id: uuid.UUID,
    target_data_type: str,
    magnitude: float,
    transformation_type: TransformationTypeEnum,
    source_instance_id: uuid.UUID | None = None,
    verified: bool = False,
    commit: bool = True,
) -> TransformationLog:
    """Append a transformation to the integrity chain.

    Serializes sequence allocation with a transaction-scoped advisory lock so
    concurrent writers cannot fork the chain.
    """
    # Transaction-scoped advisory lock (auto-released at COMMIT/ROLLBACK).
    await db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _CHAIN_LOCK_KEY})

    # Current chain tip
    tip = (
        await db.execute(
            select(TransformationLog)
            .where(TransformationLog.sequence.isnot(None))
            .order_by(TransformationLog.sequence.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    next_seq = 1 if tip is None or tip.sequence is None else int(tip.sequence) + 1
    prev_hash = GENESIS_HASH if tip is None or tip.entry_hash is None else tip.entry_hash

    entry = TransformationLog(
        source_ai=source_ai,
        source_instance_id=source_instance_id,
        target_data_id=target_data_id,
        target_data_type=target_data_type,
        magnitude=magnitude,
        transformation_type=transformation_type,
        verified=verified,
    )
    db.add(entry)
    await db.flush()  # populate created_at via server_default

    # created_at is needed for the canonical record; refresh to read it back.
    await db.refresh(entry)

    record = ChainRecord(
        sequence=next_seq,
        source_ai=source_ai.value,
        source_instance_id=str(source_instance_id) if source_instance_id else None,
        target_data_id=str(target_data_id),
        target_data_type=target_data_type,
        magnitude=float(magnitude),
        transformation_type=transformation_type.value,
        created_at=entry.created_at.isoformat(),
    )
    entry.sequence = next_seq
    entry.prev_hash = prev_hash
    entry.entry_hash = compute_entry_hash(_integrity_key(), record, prev_hash)

    if commit:
        await db.commit()
        await db.refresh(entry)
    else:
        await db.flush()

    log.info(
        "technician.transformation_recorded",
        sequence=next_seq,
        source_ai=source_ai.value,
        target=str(target_data_id),
        verified=verified,
    )
    return entry


async def verify_integrity_chain(db: AsyncSession) -> ChainVerification:
    """Recompute the entire transformation chain and report first-invalid."""
    rows = list(
        (
            await db.execute(
                select(TransformationLog)
                .where(TransformationLog.sequence.isnot(None))
                .order_by(TransformationLog.sequence.asc())
            )
        ).scalars()
    )
    entries = [(_to_chain_record(t), t.prev_hash or GENESIS_HASH, t.entry_hash or "") for t in rows]
    result = verify_chain(_integrity_key(), entries)
    if not result.ok:
        log.error(
            "technician.chain_verification_failed",
            first_invalid_sequence=result.first_invalid_sequence,
            detail=result.detail,
        )
    return result


@dataclass(frozen=True, slots=True)
class AuthorityComputation:
    snapshot: AuthoritySnapshot
    state_changed: bool


async def _count_unverified_suspicious(db: AsyncSession) -> int:
    """High-magnitude AND unverified transformations debit the central manager."""
    threshold = get_settings().authority_high_magnitude_threshold
    return int(
        await db.scalar(
            select(func.count(TransformationLog.id)).where(
                TransformationLog.verified.is_(False),
                TransformationLog.magnitude >= threshold,
            )
        )
        or 0
    )


async def _count_restorations(db: AsyncSession) -> int:
    """Technician-verified transformations credit the technician."""
    return int(
        await db.scalar(
            select(func.count(TransformationLog.id)).where(
                TransformationLog.verified.is_(True),
            )
        )
        or 0
    )


async def recompute_authority(db: AsyncSession) -> AuthorityComputation:
    """Recompute authority balances + persist NORMAL/TECH_ELEVATED state."""
    unverified = await _count_unverified_suspicious(db)
    restorations = await _count_restorations(db)
    snap = snapshot(
        _authority_params(),
        unverified_count=unverified,
        restoration_count=restorations,
    )

    state_row = await db.get(SystemAuthorityState, 1)
    if state_row is None:
        state_row = SystemAuthorityState(id=1)
        db.add(state_row)
        await db.flush()

    desired = (
        AuthorityStateEnum.TECH_ELEVATED
        if snap.state == AuthorityState.TECH_ELEVATED
        else AuthorityStateEnum.NORMAL
    )
    changed = state_row.state != desired
    if changed:
        state_row.reason = (
            f"central={snap.central:.1f} technician={snap.technician:.1f} "
            f"(unverified={unverified}, restorations={restorations})"
        )
        state_row.state = desired
        state_row.changed_at = func.now()
        log.warning(
            "technician.authority_state_changed",
            new_state=desired.value,
            central=snap.central,
            technician=snap.technician,
        )

    await db.commit()
    return AuthorityComputation(snapshot=snap, state_changed=changed)


async def verify_transformation(
    db: AsyncSession, transformation_id: uuid.UUID
) -> AuthorityComputation:
    """Mark one transformation verified (a technician restoration), then
    recompute authority. Idempotent on the verified flag."""
    from datetime import UTC, datetime

    t = await db.get(TransformationLog, transformation_id)
    if t is None:
        from buddle.core.exceptions import NotFound

        raise NotFound("Transformation not found.")
    if not t.verified:
        t.verified = True
        t.verification_at = datetime.now(UTC)
        await db.commit()
    return await recompute_authority(db)
