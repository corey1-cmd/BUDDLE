"""Persona long-term memory (LTM) — pure layer.

Persists the EKB Retention stage and serves the EKB Search stage:

    Stage A Retention (cognition.information)  ──>  extraction → PersonaMemory
    PersonaMemory  ──>  scoring → recall        ──>  Stage B Search (decision)

Atkinson & Shiffrin (1968) two-store framing: the 20-turn prompt window is
STM; this is LTM. Retrieval scoring follows Park et al. 2023 (Generative
Agents) with Ebbinghaus decay and an ACT-R-style reinforcement approximation
(see `scoring`). DB access lives in `buddle.services.memory_service`.
"""

from buddle.ai.memory.extraction import (
    MAX_CANDIDATES_PER_TURN,
    MIN_IMPORTANCE,
    MemoryCandidate,
    extract_candidates,
)
from buddle.ai.memory.scoring import (
    DECAY_PER_HOUR,
    W_IMPORTANCE,
    W_RECENCY,
    W_RELEVANCE,
    cosine_from_pgvector_distance,
    memory_score,
    recency_weight,
)

__all__ = [
    "DECAY_PER_HOUR",
    "MAX_CANDIDATES_PER_TURN",
    "MIN_IMPORTANCE",
    "W_IMPORTANCE",
    "W_RECENCY",
    "W_RELEVANCE",
    "MemoryCandidate",
    "cosine_from_pgvector_distance",
    "extract_candidates",
    "memory_score",
    "recency_weight",
]
