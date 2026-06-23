"""Selection gate — pure scoring that decides RETAIN vs LET-PASS.

Not every post belongs in the reorganization space. Each candidate unit gets a
retention_score; below threshold it is "let pass" (skipped — it still flows
through the normal plaza, just isn't stored here). This keeps the space a
curated reference, not a dump.

    retention = w_read·genuine_read + w_imp·importance(+) + w_nov·novelty
                + w_fit·topic_fit − w_red·redundancy

Signals (where each comes from — see design doc):
  genuine_read  ai/plaza/cadence.is_genuine_read(dwell, len)
  importance    ImportanceScore.normalized [-1,1]   (only positive part counts)
  novelty       1 - max cosine-similarity vs recent stored units  [0,1]
  topic_fit     proximity to existing topics/edges                [0,1]
  redundancy    share of near-duplicate existing units            [0,1]

All weights + threshold are config-tunable and are what the central manager's
autotune adjusts based on the observed retention RATE.
"""

from __future__ import annotations

from dataclasses import dataclass

# Default weights (config-overridable; central autotune target).
W_READ = 0.20
W_IMP = 0.25
W_NOV = 0.30
W_FIT = 0.15
W_RED = 0.40
RETENTION_THRESHOLD = 0.45

# Cosine similarity at/above which two units count as near-duplicates.
REDUNDANCY_SIM = 0.92


@dataclass(frozen=True, slots=True)
class SelectionSignals:
    genuine_read: bool
    importance: float       # ImportanceScore.normalized, [-1, 1]
    novelty: float          # [0, 1]
    topic_fit: float        # [0, 1]
    redundancy: float       # [0, 1]


@dataclass(frozen=True, slots=True)
class SelectionWeights:
    w_read: float = W_READ
    w_imp: float = W_IMP
    w_nov: float = W_NOV
    w_fit: float = W_FIT
    w_red: float = W_RED
    threshold: float = RETENTION_THRESHOLD

    @staticmethod
    def default() -> SelectionWeights:
        return SelectionWeights()


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def retention_score(s: SelectionSignals, w: SelectionWeights | None = None) -> float:
    """Compute the retention score in [0, +). Higher = more worth storing.

    importance contributes only its positive part (a negative/again-flagged
    importance shouldn't *raise* retention). novelty/topic_fit/redundancy are
    clamped to [0,1] defensively. redundancy subtracts (dedup pressure).
    """
    w = w or SelectionWeights.default()
    positive = (
        w.w_read * (1.0 if s.genuine_read else 0.0)
        + w.w_imp * max(0.0, s.importance)
        + w.w_nov * _clamp01(s.novelty)
        + w.w_fit * _clamp01(s.topic_fit)
    )
    return max(0.0, positive - w.w_red * _clamp01(s.redundancy))


def should_retain(s: SelectionSignals, w: SelectionWeights | None = None) -> bool:
    """True = store as a KnowledgeUnit; False = let the post pass (skip)."""
    w = w or SelectionWeights.default()
    return retention_score(s, w) >= w.threshold


def novelty_from_similarity(max_similarity: float) -> float:
    """Map the highest cosine similarity to existing units -> novelty [0,1].

    max_similarity in [-1, 1] (cosine). novelty = 1 - clamp01(sim): identical
    content (sim≈1) -> novelty≈0; nothing alike (sim≤0) -> novelty 1.
    """
    return 1.0 - _clamp01(max_similarity)


def redundancy_from_count(near_duplicates: int, *, saturation: int = 3) -> float:
    """Map count of near-duplicate existing units -> redundancy [0,1].

    0 dupes -> 0; saturates to 1 at `saturation` dupes. So a thought already
    said many times gets strongly penalized, but one prior mention only mildly.
    """
    if near_duplicates <= 0:
        return 0.0
    return _clamp01(near_duplicates / max(1, saturation))
