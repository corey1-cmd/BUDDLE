"""User profiling — pure layer.

OCEAN (Five-Factor Model) soft estimation for the 80/10/10 matching's
profile-10% and for mediator tone adaptation. Connection-only profiling:
사용자 주권(열람·수정·삭제·거부)은 services/profile_service + /v1/me/profile
이 강제하고, 배제 목적 사용 금지는 백혈구 게이트가 검열한다(§10-1).
"""

from buddle.ai.profile.signals import (
    ETA,
    TraitSignals,
    centroid_update,
    confidence_from_evidence,
    estimate_trait_signals,
    ewma_update,
)

__all__ = [
    "ETA",
    "TraitSignals",
    "centroid_update",
    "confidence_from_evidence",
    "estimate_trait_signals",
    "ewma_update",
]
