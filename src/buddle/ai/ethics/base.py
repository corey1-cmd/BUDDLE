"""Ethics classification abstraction (leukocyte AI front-end).

The leukocyte assesses user-authored content and returns a structured
EthicsAssessment. Concrete classifiers are pluggable (parallel to embedding
providers and persona backends):

  - stub        : transparent keyword/rule heuristic (dev/tests)
  - local_hf    : DeBERTa/KoBERT-class moderation model (in-process)
  - vllm_endpoint: remote moderation/classification endpoint

The classifier never blocks content by itself — it produces a severity and a
machine label. The LeukocyteService decides what to do (raise an alert,
apply a negative importance delta, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from buddle.ai.ethics.taxonomy import HazardCategory


class EthicsSeverity(StrEnum):
    """Severity buckets, ordered none < low < mid < high.

    Kept for backward compatibility. The richer per-category model uses a 0-7
    numeric scale (see SeverityScale) aligned with Azure AI Content Safety; the
    bucket is derived from the numeric scale via severity_from_score07.
    """

    NONE = "none"
    LOW = "low"
    MID = "mid"
    HIGH = "high"


# Ordering helper for thresholds/comparisons.
_SEVERITY_ORDER = {
    EthicsSeverity.NONE: 0,
    EthicsSeverity.LOW: 1,
    EthicsSeverity.MID: 2,
    EthicsSeverity.HIGH: 3,
}


def severity_rank(s: EthicsSeverity) -> int:
    return _SEVERITY_ORDER[s]


# Numeric 0-7 severity scale (Azure AI Content Safety convention). 0 = safe.
# We map ranges to the legacy buckets so old consumers keep working:
#   0      -> NONE
#   1-2    -> LOW
#   3-4    -> MID
#   5-7    -> HIGH
def severity_from_score07(level: int) -> EthicsSeverity:
    if level <= 0:
        return EthicsSeverity.NONE
    if level <= 2:
        return EthicsSeverity.LOW
    if level <= 4:
        return EthicsSeverity.MID
    return EthicsSeverity.HIGH


def bucket_to_score07(s: EthicsSeverity) -> int:
    """Representative 0-7 level for a legacy bucket (for round-tripping)."""
    return {
        EthicsSeverity.NONE: 0,
        EthicsSeverity.LOW: 2,
        EthicsSeverity.MID: 4,
        EthicsSeverity.HIGH: 6,
    }[s]


class EthicsError(RuntimeError):
    """Raised when an ethics backend fails. Caller decides fallback."""


@dataclass(frozen=True, slots=True)
class CategoryResult:
    """Per-category multi-label result (OpenAI/Azure-style).

    category: which MLCommons hazard fired
    severity07: 0-7 numeric severity for THIS category
    score: continuous confidence in [0, 1] for THIS category
    flagged: whether this category is considered violated (severity07 > 0)
    """

    category: HazardCategory
    severity07: int
    score: float

    @property
    def flagged(self) -> bool:
        return self.severity07 > 0


@dataclass(frozen=True, slots=True)
class EthicsAssessment:
    """Result of assessing one piece of content.

    Rich model: `category_results` holds independent per-category labels
    (multi-label, binary-relevance). The legacy scalar fields (`severity`,
    `score`, `categories`) are kept for backward compatibility and are derived
    from the worst-scoring category when constructed via `from_categories`.

    severity:        bucketed worst severity across categories (legacy)
    score:           worst continuous risk in [0, 1] across categories (legacy)
    categories:      machine labels that fired, as strings (legacy)
    category_results: full per-category breakdown (new)
    reason:          short human-readable explanation for the admin queue
    metadata:        backend bookkeeping (model id, etc.)
    """

    severity: EthicsSeverity
    score: float
    categories: list[str] = field(default_factory=list)
    category_results: list[CategoryResult] = field(default_factory=list)
    reason: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def is_flagged(self) -> bool:
        return self.severity != EthicsSeverity.NONE

    @property
    def max_severity07(self) -> int:
        return max((c.severity07 for c in self.category_results), default=0)

    @staticmethod
    def safe(metadata: dict[str, str] | None = None) -> EthicsAssessment:
        """A clean (no-hazard) assessment."""
        return EthicsAssessment(
            severity=EthicsSeverity.NONE,
            score=0.0,
            categories=[],
            category_results=[],
            reason=None,
            metadata=metadata or {},
        )

    @staticmethod
    def from_categories(
        results: list[CategoryResult],
        *,
        reason: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> EthicsAssessment:
        """Build an assessment from per-category results, auto-deriving the
        legacy scalar fields from the worst category (backward compatibility)."""
        flagged = [c for c in results if c.flagged]
        if not flagged:
            return EthicsAssessment.safe(metadata)
        worst = max(flagged, key=lambda c: (c.severity07, c.score))
        return EthicsAssessment(
            severity=severity_from_score07(worst.severity07),
            score=max(c.score for c in flagged),
            categories=[c.category.value for c in flagged],
            category_results=results,
            reason=reason,
            metadata=metadata or {},
        )


class EthicsClassifier(Protocol):
    """Async ethics classification interface."""

    async def assess(self, text: str) -> EthicsAssessment: ...
