"""Long-term memory scoring — pure functions (no I/O, no LLM).

Theoretical grounding (each maps to one term of the score):

  * Retrieval composition — Park et al. 2023, "Generative Agents" (UIST):
        score = w_r·recency + w_i·importance + w_s·relevance
    Relevance carries the largest weight (what the user is talking about NOW
    should dominate which memories surface), with recency and importance as
    equal secondary signals.

  * Recency — Ebbinghaus (1885) forgetting curve: retention decays roughly
    exponentially with time since last access. We use the Generative-Agents
    convention of a per-hour exponential decay on *last access* (not creation),
    so a memory that keeps being used keeps being fresh.

  * Reinforcement — Anderson & Schooler (1991), the ACT-R rational analysis of
    memory: each retrieval raises an item's base-level activation, and items
    retrieved often are forgotten more slowly. Full ACT-R sums a power-law over
    every access timestamp; storing all timestamps is overkill here, so we use
    the standard practical approximation: a log-strength multiplier that slows
    the exponential decay. Documented as an approximation on purpose.

  * The two-store framing (this LTM next to the 20-turn prompt window) is
    Atkinson & Shiffrin (1968): STM = dialogue window, LTM = this table,
    rehearsal (re-access) = transfer/strengthening.

All functions are deterministic and unit-testable without a database.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

# Park et al. 2023 weights — relevance dominant, recency/importance secondary.
W_RECENCY: float = 0.25
W_IMPORTANCE: float = 0.25
W_RELEVANCE: float = 0.50

# Ebbinghaus-style exponential decay per hour since last access (Generative
# Agents uses 0.995 as well). Half-life ≈ 138 hours ≈ 5.8 days at strength 1.
DECAY_PER_HOUR: float = 0.995

# How strongly repeated retrievals slow forgetting (ACT-R approximation).
_STRENGTH_DAMPING: float = 0.35


def _as_utc(dt: datetime) -> datetime:
    """Normalize naive datetimes to UTC (DB columns are timezone-aware, but be
    defensive for unit tests / external callers)."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def recency_weight(last_accessed_at: datetime, *, now: datetime, strength: float) -> float:
    """Exponential forgetting with strength-slowed decay, in [0, 1].

    decay exponent = hours / (1 + λ·ln(strength)); a memory recalled many
    times (high strength) decays as if less time had passed — the practical
    ACT-R base-level approximation.
    """
    hours = max(0.0, (_as_utc(now) - _as_utc(last_accessed_at)).total_seconds() / 3600.0)
    damp = 1.0 + _STRENGTH_DAMPING * math.log(max(1.0, strength))
    return math.pow(DECAY_PER_HOUR, hours / damp)


def memory_score(
    *,
    cosine_sim: float,
    importance: float,
    strength: float,
    last_accessed_at: datetime,
    now: datetime,
) -> float:
    """Composite retrieval score in [0, 1] (Generative-Agents composition).

    cosine_sim and importance are expected in [0, 1]; out-of-range inputs are
    clamped so a misbehaving provider cannot push scores outside bounds.
    """
    rel = min(1.0, max(0.0, cosine_sim))
    imp = min(1.0, max(0.0, importance))
    rec = recency_weight(last_accessed_at, now=now, strength=strength)
    return round(W_RECENCY * rec + W_IMPORTANCE * imp + W_RELEVANCE * rel, 6)


def cosine_from_pgvector_distance(distance: float) -> float:
    """pgvector's `<=>` cosine distance (in [0, 2]) -> similarity in [0, 1].

    Same mapping the mediator uses (1 - d/2), kept here so the memory layer
    and the matching layer score similarity identically.
    """
    return max(0.0, 1.0 - float(distance) / 2.0)
