"""Tamper-evident integrity chain for transformation logs.

Design follows the established hash-chain audit-log pattern (Cossack Labs
Acra, Certificate Transparency, git): every transformation record is linked to
its predecessor via an HMAC-SHA256 over a *canonical* serialization of the
record concatenated with the previous entry's hash. Any altered byte in any
record breaks the chain from that point forward, and verification reports the
first invalid sequence.

Key properties:
  - HMAC (keyed) not bare hash: an attacker with DB write access still cannot
    forge a valid continuation without the integrity key (held separately from
    the JWT key, ideally in a distinct secret store).
  - Domain separation: the HMAC input is prefixed with a domain tag so chain
    hashes can never collide with hashes computed for any other purpose.
  - Canonical serialization: field order and formatting are fixed, so the same
    logical record always hashes identically (the genuinely hard part — the
    crypto is easy, serialization consistency is where chains break).
  - Genesis constant: the first entry links to a fixed genesis hash.

This module is pure (no DB, no I/O). The TechnicianService computes/persists
the sequence, prev_hash and entry_hash; verification recomputes them.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass

# Fixed genesis value for the first entry's prev_hash (64 hex chars = SHA-256).
GENESIS_HASH = "0" * 64

# Domain-separation tag mixed into every HMAC input.
_DOMAIN = b"buddle.transformation_log.v1"


@dataclass(frozen=True, slots=True)
class ChainRecord:
    """The canonical, hashable fields of a transformation record.

    Only fields that are part of the integrity guarantee belong here. Mutable
    bookkeeping (verified flag, verification_at) is intentionally excluded so
    that verifying a transformation doesn't invalidate its own chain hash.
    """

    sequence: int
    source_ai: str
    source_instance_id: str | None
    target_data_id: str
    target_data_type: str
    magnitude: float
    transformation_type: str
    created_at: str  # ISO-8601, UTC


def canonical_bytes(record: ChainRecord) -> bytes:
    """Deterministic serialization of a ChainRecord.

    Uses JSON with sorted keys, no whitespace, and explicit float formatting so
    the output is byte-identical across processes and languages.
    """
    payload = {
        "sequence": record.sequence,
        "source_ai": record.source_ai,
        "source_instance_id": record.source_instance_id,
        "target_data_id": record.target_data_id,
        "target_data_type": record.target_data_type,
        # repr-stable float: format with 6 decimals to avoid platform variance
        "magnitude": f"{record.magnitude:.6f}",
        "transformation_type": record.transformation_type,
        "created_at": record.created_at,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )


def compute_entry_hash(key: bytes, record: ChainRecord, prev_hash: str) -> str:
    """HMAC-SHA256(key, domain ‖ canonical(record) ‖ prev_hash) as hex."""
    mac = hmac.new(key, _DOMAIN, hashlib.sha256)
    mac.update(canonical_bytes(record))
    mac.update(prev_hash.encode("ascii"))
    return mac.hexdigest()


def verify_link(key: bytes, record: ChainRecord, prev_hash: str, expected_entry_hash: str) -> bool:
    """Constant-time check that a single record's stored hash is valid."""
    computed = compute_entry_hash(key, record, prev_hash)
    return hmac.compare_digest(computed, expected_entry_hash)


@dataclass(frozen=True, slots=True)
class ChainVerification:
    """Result of verifying a chain (or sub-chain)."""

    ok: bool
    checked: int
    first_invalid_sequence: int | None
    detail: str


def verify_chain(
    key: bytes,
    entries: list[tuple[ChainRecord, str, str]],
    *,
    start_prev_hash: str = GENESIS_HASH,
) -> ChainVerification:
    """Verify an ordered list of (record, prev_hash, entry_hash) tuples.

    Entries must be sorted by sequence ascending. Checks both that each entry's
    HMAC is correct AND that prev_hash actually chains to the previous entry's
    entry_hash (so reordering/deletion is detected, not just field edits).

    Reports the first invalid sequence (first-invalid reporting), which is what
    auditors need to localize tampering.
    """
    expected_prev = start_prev_hash
    checked = 0
    last_seq: int | None = None

    for record, stored_prev, stored_entry in entries:
        # 1. Monotonic, gap-free sequence within the provided window
        if last_seq is not None and record.sequence != last_seq + 1:
            return ChainVerification(
                ok=False,
                checked=checked,
                first_invalid_sequence=record.sequence,
                detail=(f"sequence gap/reorder: expected {last_seq + 1}, got {record.sequence}"),
            )

        # 2. Chain linkage: stored prev_hash must equal the running expectation
        if stored_prev != expected_prev:
            return ChainVerification(
                ok=False,
                checked=checked,
                first_invalid_sequence=record.sequence,
                detail="prev_hash does not chain to previous entry",
            )

        # 3. HMAC integrity of this record
        if not verify_link(key, record, stored_prev, stored_entry):
            return ChainVerification(
                ok=False,
                checked=checked,
                first_invalid_sequence=record.sequence,
                detail="entry_hash mismatch (record tampered or wrong key)",
            )

        expected_prev = stored_entry
        last_seq = record.sequence
        checked += 1

    return ChainVerification(
        ok=True,
        checked=checked,
        first_invalid_sequence=None,
        detail=f"verified {checked} entries",
    )
