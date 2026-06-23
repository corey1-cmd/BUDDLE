"""Password hashing & verification via argon2id."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

# argon2id with conservative defaults. Bump time_cost/memory_cost as hardware allows.
_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=64 * 1024,  # 64 MiB
    parallelism=4,
)


def hash_password(plain: str) -> str:
    """Hash a plaintext password."""
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against an argon2 hash."""
    try:
        return _hasher.verify(hashed, plain)
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(hashed: str) -> bool:
    """Whether the hash should be regenerated with current parameters."""
    return _hasher.check_needs_rehash(hashed)


# A precomputed argon2 hash of a random throwaway password. verify_dummy()
# runs a real argon2 verification against it so that a login attempt for a
# NON-EXISTENT user costs the same time as one for an existing user — closing
# the timing side-channel that would otherwise reveal which emails are
# registered (user enumeration).
_DUMMY_HASH = _hasher.hash("x" * 24)


def verify_dummy() -> None:
    """Perform a throwaway verification to equalize timing. Result ignored."""
    import contextlib

    with contextlib.suppress(VerifyMismatchError, InvalidHashError):
        _hasher.verify(_DUMMY_HASH, "wrong-password")
