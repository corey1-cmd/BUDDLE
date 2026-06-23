"""Knowledge reorganization space — pure core (Layer B, stage 1).

Selective reference infrastructure: extract atomic thought units from posts,
decide which are worth retaining (selection gate), and relate topics to one
another (association edges). All pure + deterministic; the service layer wires
these to embeddings, the DB, and the supervising AIs.
"""

from __future__ import annotations

from buddle.ai.knowledge.edges import (
    CO_OCCUR_WEIGHT,
    DECAY,
    EMB_PROX_WEIGHT,
    apply_delta,
    decayed,
    edge_delta,
    is_dead,
    normalize_pair,
    proximity_from_distance,
)
from buddle.ai.knowledge.extraction import (
    DEFAULT_MAX_UNITS,
    RawUnit,
    extract_units,
)
from buddle.ai.knowledge.selection import (
    REDUNDANCY_SIM,
    RETENTION_THRESHOLD,
    SelectionSignals,
    SelectionWeights,
    novelty_from_similarity,
    redundancy_from_count,
    retention_score,
    should_retain,
)
from buddle.ai.knowledge.synthesis import (
    BUNDLE_MIN_UNITS,
    FRESHNESS_FLOOR,
    SIM_GROUP_THRESHOLD,
    SynthesisPlan,
    UnitView,
    fallback_summary,
    plan_synthesis,
    should_synthesize,
)
from buddle.ai.knowledge.synthesizer import (
    LlmSynthesizer,
    StubSynthesizer,
    SynthesisError,
    Synthesizer,
    get_synthesizer,
)

__all__ = [
    "BUNDLE_MIN_UNITS",
    "CO_OCCUR_WEIGHT",
    "DECAY",
    "DEFAULT_MAX_UNITS",
    "EMB_PROX_WEIGHT",
    "FRESHNESS_FLOOR",
    "REDUNDANCY_SIM",
    "RETENTION_THRESHOLD",
    "SIM_GROUP_THRESHOLD",
    "LlmSynthesizer",
    "RawUnit",
    "SelectionSignals",
    "SelectionWeights",
    "StubSynthesizer",
    "SynthesisError",
    "SynthesisPlan",
    "Synthesizer",
    "UnitView",
    "apply_delta",
    "decayed",
    "edge_delta",
    "extract_units",
    "fallback_summary",
    "get_synthesizer",
    "is_dead",
    "normalize_pair",
    "novelty_from_similarity",
    "plan_synthesis",
    "proximity_from_distance",
    "redundancy_from_count",
    "retention_score",
    "should_retain",
    "should_synthesize",
]
