"""Pure technician-core tests: integrity hash chain + dynamic authority.

No DB. Locks in the tamper-evidence guarantees (detect edit / reorder / delete
/ wrong-key) and the authority crossing logic (fails closed, strict crossing).
"""

from __future__ import annotations

import dataclasses

import pytest

from buddle.ai.technician import (
    GENESIS_HASH,
    AuthorityParams,
    ChainRecord,
    central_authority,
    compute_entry_hash,
    decide_state,
    snapshot,
    technician_authority,
    verify_chain,
    verify_link,
)
from buddle.ai.technician.authority import AuthorityState

KEY = b"unit-test-integrity-key"


def _build_chain(n: int) -> list[tuple[ChainRecord, str, str]]:
    out: list[tuple[ChainRecord, str, str]] = []
    prev = GENESIS_HASH
    for i in range(1, n + 1):
        r = ChainRecord(
            sequence=i,
            source_ai="mediator",
            source_instance_id=None,
            target_data_id=f"post-{i}",
            target_data_type="post",
            magnitude=float(i),
            transformation_type="inject",
            created_at=f"2026-05-18T0{i}:00:00+00:00",
        )
        h = compute_entry_hash(KEY, r, prev)
        out.append((r, prev, h))
        prev = h
    return out


# ── integrity chain ──────────────────────────────────────────────────────


def test_valid_chain_verifies():
    chain = _build_chain(5)
    v = verify_chain(KEY, chain)
    assert v.ok
    assert v.checked == 5
    assert v.first_invalid_sequence is None


def test_single_record_link_roundtrip():
    chain = _build_chain(1)
    record, prev, entry = chain[0]
    assert verify_link(KEY, record, prev, entry)
    assert not verify_link(KEY, record, prev, "deadbeef" * 8)


def test_edit_detected_at_first_invalid():
    chain = _build_chain(5)
    tampered_record = dataclasses.replace(chain[2][0], magnitude=999.0)
    chain[2] = (tampered_record, chain[2][1], chain[2][2])
    v = verify_chain(KEY, chain)
    assert not v.ok
    assert v.first_invalid_sequence == 3


def test_reorder_detected():
    chain = _build_chain(4)
    chain[1], chain[2] = chain[2], chain[1]
    v = verify_chain(KEY, chain)
    assert not v.ok


def test_deletion_breaks_chain():
    chain = _build_chain(4)
    del chain[1]  # drop sequence 2
    v = verify_chain(KEY, chain)
    assert not v.ok
    assert v.first_invalid_sequence == 3


def test_wrong_key_fails_at_first_entry():
    chain = _build_chain(3)
    v = verify_chain(b"attacker-key", chain)
    assert not v.ok
    assert v.first_invalid_sequence == 1


def test_empty_chain_is_trivially_valid():
    v = verify_chain(KEY, [])
    assert v.ok
    assert v.checked == 0


def test_canonical_hash_is_stable_across_calls():
    chain = _build_chain(1)
    r, prev, _ = chain[0]
    h1 = compute_entry_hash(KEY, r, prev)
    h2 = compute_entry_hash(KEY, r, prev)
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


# ── dynamic authority ──────────────────────────────────────────────────────

P = AuthorityParams(
    central_base=100.0,
    technician_base=0.0,
    debit_unverified=10.0,
    credit_restoration=10.0,
)


def test_normal_state_when_no_events():
    assert decide_state(P, unverified_count=0, restoration_count=0) == AuthorityState.NORMAL


def test_central_authority_debited_by_unverified():
    assert central_authority(P, 0) == 100.0
    assert central_authority(P, 3) == 70.0


def test_technician_authority_credited_by_restoration():
    assert technician_authority(P, 0) == 0.0
    assert technician_authority(P, 4) == 40.0


def test_tech_elevated_when_technician_exceeds_central():
    # central: 100 - 11*10 = -10 ; technician: 1*10 = 10 -> elevated
    assert decide_state(P, unverified_count=11, restoration_count=1) == AuthorityState.TECH_ELEVATED


def test_equal_authority_stays_normal_strict_crossing():
    # central: 100 - 10*10 = 0 ; technician: 0 -> equal -> NOT elevated (strict >)
    assert decide_state(P, unverified_count=10, restoration_count=0) == AuthorityState.NORMAL


def test_negative_counts_clamped():
    # defensive: negative inputs treated as zero
    assert central_authority(P, -5) == 100.0
    assert technician_authority(P, -5) == 0.0


def test_snapshot_bundles_state():
    s = snapshot(P, unverified_count=12, restoration_count=2)
    assert s.central == 100.0 - 120.0
    assert s.technician == 20.0
    assert s.state == AuthorityState.TECH_ELEVATED
    assert s.unverified_count == 12
    assert s.restoration_count == 2


def test_authority_params_validation():
    with pytest.raises(ValueError):
        AuthorityParams(
            central_base=100.0,
            technician_base=0.0,
            debit_unverified=-1.0,
            credit_restoration=10.0,
        )
