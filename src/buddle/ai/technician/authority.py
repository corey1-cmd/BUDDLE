"""Dynamic authority computation (pure).

The buddle spec gives the technician AI the ability to *exceed* the central
manager when the central manager has accumulated unjustified transformations
(i.e. is compromised or malfunctioning). This is the system's self-healing
override, expressed as a token economy:

    authority(central_manager) = base_central - Σ debit(unverified change)
    authority(technician)      = base_technician + Σ credit(verified restore)

    state = TECH_ELEVATED   if authority(technician) > authority(central_manager)
            NORMAL          otherwise

Security posture: this is an authorization decision, so it FAILS CLOSED. If
inputs are missing/ambiguous we do NOT silently grant elevation; we require an
explicit, computed crossing. (Contrast with the rate limiter, which fails open
for availability.)

Pure functions only — the service layer reads balances from authority_tokens
and persists state transitions to system_authority_state.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AuthorityState(StrEnum):
    NORMAL = "normal"
    TECH_ELEVATED = "tech_elevated"


@dataclass(frozen=True, slots=True)
class AuthorityParams:
    central_base: float
    technician_base: float
    debit_unverified: float
    credit_restoration: float

    def __post_init__(self) -> None:
        if self.debit_unverified < 0 or self.credit_restoration < 0:
            raise ValueError("debit/credit magnitudes must be non-negative")


def central_authority(params: AuthorityParams, unverified_count: int) -> float:
    """Central manager's effective authority given its unverified-change count."""
    if unverified_count < 0:
        unverified_count = 0
    return params.central_base - params.debit_unverified * unverified_count


def technician_authority(params: AuthorityParams, restoration_count: int) -> float:
    """Technician's effective authority given its verified-restoration count."""
    if restoration_count < 0:
        restoration_count = 0
    return params.technician_base + params.credit_restoration * restoration_count


def decide_state(
    params: AuthorityParams,
    *,
    unverified_count: int,
    restoration_count: int,
) -> AuthorityState:
    """Decide the global authority state. Fails closed: elevation only on a
    strict, computed crossing."""
    central = central_authority(params, unverified_count)
    tech = technician_authority(params, restoration_count)
    return AuthorityState.TECH_ELEVATED if tech > central else AuthorityState.NORMAL


@dataclass(frozen=True, slots=True)
class AuthoritySnapshot:
    central: float
    technician: float
    state: AuthorityState
    unverified_count: int
    restoration_count: int


def snapshot(
    params: AuthorityParams,
    *,
    unverified_count: int,
    restoration_count: int,
) -> AuthoritySnapshot:
    return AuthoritySnapshot(
        central=central_authority(params, unverified_count),
        technician=technician_authority(params, restoration_count),
        state=decide_state(
            params,
            unverified_count=unverified_count,
            restoration_count=restoration_count,
        ),
        unverified_count=unverified_count,
        restoration_count=restoration_count,
    )
