"""Language affect perception + response guidance (evidence-based, bias-safe)."""

from buddle.ai.affect.guidance import build_affect_guidance
from buddle.ai.affect.perception import (
    PerceivedAffect,
    ResponsePosture,
    Valence,
    perceive,
)

__all__ = [
    "PerceivedAffect",
    "ResponsePosture",
    "Valence",
    "build_affect_guidance",
    "perceive",
]
