"""Ethics classifiers + factory.

get_ethics_classifier() returns the configured classifier (cached). The
LeukocyteService goes through this.
"""

from __future__ import annotations

from functools import lru_cache

from buddle.ai.ethics.base import (
    CategoryResult,
    EthicsAssessment,
    EthicsClassifier,
    EthicsError,
    EthicsSeverity,
    bucket_to_score07,
    severity_from_score07,
    severity_rank,
)
from buddle.ai.ethics.llama_guard import LlamaGuardEthicsClassifier
from buddle.ai.ethics.stub import StubEthicsClassifier
from buddle.ai.ethics.taxonomy import (
    HazardCategory,
    HazardGroup,
    english_name,
    group_of,
    korean_description,
)
from buddle.config import get_settings
from buddle.core.logging import get_logger

log = get_logger(__name__)


@lru_cache(maxsize=1)
def get_ethics_classifier() -> EthicsClassifier:
    settings = get_settings()
    kind = settings.ethics_provider

    if kind == "stub":
        return StubEthicsClassifier()

    if kind == "local_hf":
        from buddle.ai.ethics.local_hf import LocalHfEthicsClassifier

        return LocalHfEthicsClassifier({"model_id": settings.ethics_model_id})

    if kind == "vllm_endpoint":
        from buddle.ai.ethics.vllm_endpoint import VllmEthicsClassifier

        return VllmEthicsClassifier({"endpoint_url": settings.ethics_endpoint_url})

    if kind == "llama_guard":
        from buddle.ai.ethics.llama_guard import LlamaGuardEthicsClassifier

        return LlamaGuardEthicsClassifier(
            {
                "endpoint_url": settings.ethics_endpoint_url,
                "model": settings.ethics_model_id or "llama-guard3:8b",
            }
        )

    raise EthicsError(f"Unknown ethics_provider: {kind!r}")


__all__ = [
    "CategoryResult",
    "EthicsAssessment",
    "EthicsClassifier",
    "EthicsError",
    "EthicsSeverity",
    "HazardCategory",
    "HazardGroup",
    "LlamaGuardEthicsClassifier",
    "StubEthicsClassifier",
    "bucket_to_score07",
    "english_name",
    "get_ethics_classifier",
    "group_of",
    "korean_description",
    "severity_from_score07",
    "severity_rank",
]
