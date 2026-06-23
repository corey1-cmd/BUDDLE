"""Technician AI — integrity (hash chain) + dynamic authority (pure cores)."""

from buddle.ai.technician.authority import (
    AuthorityParams,
    AuthoritySnapshot,
    AuthorityState,
    central_authority,
    decide_state,
    snapshot,
    technician_authority,
)
from buddle.ai.technician.integrity import (
    GENESIS_HASH,
    ChainRecord,
    ChainVerification,
    canonical_bytes,
    compute_entry_hash,
    verify_chain,
    verify_link,
)

__all__ = [
    "GENESIS_HASH",
    "AuthorityParams",
    "AuthoritySnapshot",
    "AuthorityState",
    "ChainRecord",
    "ChainVerification",
    "canonical_bytes",
    "central_authority",
    "compute_entry_hash",
    "decide_state",
    "snapshot",
    "technician_authority",
    "verify_chain",
    "verify_link",
]
