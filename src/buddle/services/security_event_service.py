"""Security audit log service.

Records security-relevant events into the existing `security_events` table so
the human admin / central manager can spot trends: brute force (login_failed
spikes), credential stuffing (account_locked), token theft (refresh_reuse),
and tampering attempts (ssrf_blocked).

Design:
  - Best-effort: a logging failure must never break the request it describes,
    so record() swallows and logs its own errors.
  - No secrets: only identifiers (email/ip/user_id) and outcomes go in detail.
  - Uses its own short-lived DB session so it can record even when the caller's
    transaction is being rolled back (e.g. on a failed login).
"""

from __future__ import annotations

import uuid
from typing import Any

from buddle.core.logging import get_logger
from buddle.db.models.security_event import SecurityEvent
from buddle.db.session import AsyncSessionLocal

log = get_logger(__name__)

# Event type constants (kept short; stored in a String(32) column).
LOGIN_SUCCEEDED = "login_ok"
LOGIN_FAILED = "login_failed"
ACCOUNT_LOCKED = "account_locked"
REFRESH_REUSE = "refresh_reuse"
LOGOUT = "logout"
SSRF_BLOCKED = "ssrf_blocked"
AUTHORITY_CHANGED = "authority_changed"
INTEGRITY_FAILED = "integrity_failed"


async def record(
    event_type: str,
    *,
    severity: str = "info",
    user_id: uuid.UUID | str | None = None,
    email: str | None = None,
    ip: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Append a security event. Best-effort; never raises to the caller."""
    detail: dict[str, Any] = {}
    if user_id is not None:
        detail["user_id"] = str(user_id)
    if email is not None:
        # store normalized; emails here are for ops triage, not authn
        detail["email"] = email.strip().lower()
    if ip is not None:
        detail["ip"] = ip
    if extra:
        detail.update(extra)

    try:
        async with AsyncSessionLocal() as db:
            db.add(
                SecurityEvent(
                    event_type=event_type[:32],
                    severity=severity[:16],
                    detail=detail or None,
                )
            )
            await db.commit()
    except Exception as e:  # never let audit logging break the flow
        log.warning("security_event.record_failed", event_type=event_type, error=str(e))
