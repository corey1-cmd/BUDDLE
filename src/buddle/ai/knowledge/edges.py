"""Topic association edges — pure weight math (co-occurrence + embedding).

Builds a weighted topic graph that lets the space relate conversation themes
to one another (so a persona discussing topic X can also draw on closely
related topics). Two signals raise an edge between topics A and B:

  - co-occurrence: A and B appear together on the same post
  - embedding proximity: representative units of A and B are close in vector
    space (proximity = 1 - cosine_distance)

Edges decay over time (per standby tick) so stale associations fade. Pure;
the service layer supplies the actual co-occurrence facts and embeddings.
"""

from __future__ import annotations

CO_OCCUR_WEIGHT = 1.0  # both topics on one post
EMB_PROX_WEIGHT = 0.5  # representative embeddings close
DECAY = 0.98  # multiplied per standby tick
EDGE_MIN_WEIGHT = 0.05  # below this an edge is considered dead (prunable)


def edge_delta(*, co_occurred: bool, emb_proximity: float) -> float:
    """Weight to ADD to an A–B edge from one observation.

    emb_proximity is clamped to [0,1]. A co-occurrence alone adds CO_OCCUR_WEIGHT;
    proximity adds up to EMB_PROX_WEIGHT; both can combine.
    """
    prox = max(0.0, min(1.0, emb_proximity))
    return (CO_OCCUR_WEIGHT if co_occurred else 0.0) + EMB_PROX_WEIGHT * prox


def apply_delta(current: float, delta: float) -> float:
    """Accumulate an edge weight (non-negative)."""
    return max(0.0, current + delta)


def decayed(weight: float, ticks: int = 1, *, decay: float = DECAY) -> float:
    """Apply time decay over `ticks` standby cycles."""
    if ticks <= 0:
        return weight
    return weight * (decay**ticks)


def is_dead(weight: float, *, floor: float = EDGE_MIN_WEIGHT) -> bool:
    """Whether an edge has decayed below the keep threshold (prunable)."""
    return weight < floor


def proximity_from_distance(cosine_distance: float) -> float:
    """Convert a pgvector cosine_distance [0,2] to proximity [0,1].

    distance 0 (identical) -> 1.0; distance 1 (orthogonal) -> 0.0; clamped.
    """
    return max(0.0, min(1.0, 1.0 - cosine_distance))


def normalize_pair(topic_a: str, topic_b: str) -> tuple[str, str]:
    """Canonical (sorted) ordering so an edge is stored once regardless of
    which direction it was observed from."""
    return (topic_a, topic_b) if topic_a <= topic_b else (topic_b, topic_a)
