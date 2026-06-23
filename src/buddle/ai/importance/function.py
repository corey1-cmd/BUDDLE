"""Pure importance math — additive accumulation + bounded normalization.

Design rationale (from the buddle system spec):

  raw_importance(c)        = Σ contribution_i          # ADDITIVE, signed
  normalized_importance(c) = I_max * tanh(raw / kappa) # squashed to (-I_max, I_max)

Why additive, not multiplicative:
  A multiplicative scheme lets a single large signal blow up the score and
  dominate the feed (the classic "rage/sensation" runaway of engagement
  algorithms). Additive accumulation makes the score proportional to the *sum*
  of evidence, and the tanh ceiling guarantees no single piece of content can
  ever capture the system: as raw -> ±∞, normalized -> ±I_max asymptotically.

Properties we rely on (and test):
  - normalized(0)          == 0
  - sign(normalized)       == sign(raw)
  - |normalized|           <  I_max          (strict, for finite raw)
  - monotonic increasing in raw
  - diminishing returns: equal raw increments yield smaller normalized gains
    as |raw| grows (the saturation that prevents runaway)

Everything here is pure: no DB, no I/O. The service layer feeds it the summed
raw value and persists results.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ImportanceParams:
    """Tunable parameters for the normalization curve.

    i_max:  asymptotic bound on |normalized|. 1.0 keeps it in (-1, 1).
    kappa:  horizontal scale. Larger kappa -> slower saturation -> more raw
            evidence needed to approach the ceiling. Pick relative to the
            typical magnitude of summed contributions.
    """

    i_max: float = 1.0
    kappa: float = 50.0

    def __post_init__(self) -> None:
        if self.i_max <= 0:
            raise ValueError("i_max must be positive")
        if self.kappa <= 0:
            raise ValueError("kappa must be positive")


def normalize(raw: float, params: ImportanceParams) -> float:
    """Map a raw additive score to a bounded normalized importance.

    normalized = i_max * tanh(raw / kappa)
    """
    return params.i_max * math.tanh(raw / params.kappa)


def distribution_multiplier(normalized: float, params: ImportanceParams) -> float:
    """Map normalized importance in [-i_max, i_max] to a non-negative
    distribution weight in [0, 1].

        multiplier = (normalized / i_max + 1) / 2

    -i_max -> 0.0 (fully suppressed), 0 -> 0.5 (neutral, e.g. brand-new post),
    +i_max -> 1.0 (maximally boosted).

    Used so the mediator can de-prioritize negative-importance (unethical or
    reported) content in private distribution without ever multiplying by a
    negative number.
    """
    ratio = normalized / params.i_max
    # numerical guard against tiny overshoot from float tanh
    ratio = max(-1.0, min(1.0, ratio))
    return (ratio + 1.0) / 2.0


def feed_score(
    normalized: float,
    age_seconds: float,
    *,
    recency_half_life_seconds: float,
    w_importance: float,
    w_recency: float,
) -> float:
    """Blend normalized importance with a recency decay for feed ranking.

    recency_factor = 0.5 ** (age / half_life)   -> 1.0 fresh, ->0 as it ages
    importance_factor = (normalized / i-implied 1) mapped to [0, 1] via the
        same midpoint transform as distribution_multiplier, so negative
        importance still ranks below neutral.

    score = w_recency * recency_factor + w_importance * importance_factor

    Note: normalized is expected already in [-1, 1] (i_max == 1 convention for
    feed). Callers using a different i_max should pre-divide.
    """
    recency_factor = 0.5 ** (age_seconds / recency_half_life_seconds)
    importance_factor = max(-1.0, min(1.0, normalized)) * 0.5 + 0.5
    return float(w_recency * recency_factor + w_importance * importance_factor)
