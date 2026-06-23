"""User profile — pure layer (OCEAN trait signals + bounded updates).

Theoretical grounding:

  * Coordinate system — the Five-Factor Model / OCEAN (McCrae & Costa 1987;
    Goldberg 1990 lexical hypothesis): openness, conscientiousness,
    extraversion, agreeableness, neuroticism. The de-facto standard axes for
    describing personality, which is why the matching layer (80/10/10) can use
    them as a stable similarity space.

  * Epistemics — text-inferred traits correlate with self-report only at
    r ≈ 0.3–0.4 (Mairesse et al. 2007 JAIR; Schwartz et al. 2013 PLOS ONE;
    Park et al. 2015 JPSP). So every estimate here is a SOFT SIGNAL with an
    explicit confidence, never a diagnosis. The API exposes confidence so the
    UI can say "추정"; the matching layer must gate on it.

  * State vs trait — traits are the *mean of a density distribution* of
    states (Fleeson 2001), not any single utterance. Hence the EWMA with a
    small learning rate: one message can move a trait by at most η.

  * Sovereignty by design — these functions are pure; the service layer
    enforces 열람·수정·삭제·거부 (PIPA 제37조의2; 사업계획서 §10-1): user
    edits freeze automatic updates, opt-out stops observation entirely, and
    profiles are used for connection only, never exclusion (백혈구 게이트).

Rule-based, deterministic, zero LLM calls — the stub-grade estimator. A
guided-JSON LLM estimator can replace `estimate_trait_signals` behind the
same dataclass when real models are wired (stub→real philosophy).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, fields

# Fleeson guard: a single observation moves a trait by at most ETA.
ETA: float = 0.1
# Evidence count at which confidence reaches ~0.63 (1 - 1/e).
_CONFIDENCE_SCALE: float = 30.0
# Marker-present signal strength: clearly above the 0.5 prior, never extreme.
_SIGNAL_BASE: float = 0.65
_SIGNAL_PER_EXTRA: float = 0.05
_SIGNAL_CAP: float = 0.85


@dataclass(frozen=True, slots=True)
class TraitSignals:
    """Per-trait observation for one text; None = no evidence this turn."""

    o: float | None = None
    c: float | None = None
    e: float | None = None
    a: float | None = None
    n: float | None = None

    def any(self) -> bool:
        return any(getattr(self, f.name) is not None for f in fields(self))


_TRAIT_LEXICON: dict[str, re.Pattern[str]] = {
    # Openness: curiosity, aesthetics, ideas, novelty.
    "o": re.compile(
        r"(새로운|상상|예술|궁금|호기심|아이디어|철학|시집|음악|여행|배우고|창의|영감"
        r"|curio|novel|imagin|creativ|art\b)",
        re.IGNORECASE,
    ),
    # Conscientiousness: planning, order, goals, diligence.
    "c": re.compile(
        r"(계획|정리|목표|꾸준|일정|마감|체계|준비|규칙|루틴|미리"
        r"|plan|organi[sz]|goal|routine|deadline)",
        re.IGNORECASE,
    ),
    # Extraversion: social energy, gatherings, enthusiasm.
    "e": re.compile(
        r"(사람들|모임|파티|함께 놀|신나|만나자|수다|활발|어울리"
        r"|party|hang out|meet up|outgoing)",
        re.IGNORECASE,
    ),
    # Agreeableness: gratitude, helping, empathy, kindness.
    "a": re.compile(
        r"(고마워|고맙|감사|도와|배려|공감|친절|챙겨|위로"
        r"|thank|help|kind|empath)",
        re.IGNORECASE,
    ),
    # Neuroticism: anxiety, stress, fear, irritability.
    "n": re.compile(
        r"(불안|걱정|초조|스트레스|짜증|우울|두렵|무섭|힘들|예민"
        r"|anxio|worr|stress|afraid|nervous)",
        re.IGNORECASE,
    ),
}


def estimate_trait_signals(text: str) -> TraitSignals:
    """Lexicon-based trait observation in [0, 1] per trait, or None.

    Deterministic. Marker presence yields a moderate positive signal
    (base 0.65, +0.05 per extra distinct match, cap 0.85) — deliberately never
    extreme, because the literature ceiling for text inference is modest.
    Absence of markers yields None (no evidence), NOT a low score.
    """
    if not text or not text.strip():
        return TraitSignals()

    values: dict[str, float | None] = {}
    for trait, pattern in _TRAIT_LEXICON.items():
        matches = pattern.findall(text)
        if matches:
            signal = _SIGNAL_BASE + _SIGNAL_PER_EXTRA * (len(matches) - 1)
            values[trait] = round(min(_SIGNAL_CAP, signal), 4)
        else:
            values[trait] = None
    return TraitSignals(**values)


def ewma_update(current: float, observed: float, *, eta: float = ETA) -> float:
    """Bounded trait update: new = (1-η)·current + η·observed, clamped [0,1].

    With η = 0.1 a single message shifts a trait by at most 0.1·|obs−cur| —
    the Fleeson density-distribution view made operational.
    """
    cur = min(1.0, max(0.0, current))
    obs = min(1.0, max(0.0, observed))
    return round((1.0 - eta) * cur + eta * obs, 4)


def confidence_from_evidence(evidence_count: int) -> float:
    """Saturating confidence: 1 − exp(−n/30) ∈ [0, 1).

    ~0.28 at 10 observations, ~0.63 at 30, ~0.96 at 100 — the matching layer
    should multiply profile similarity by this so thin profiles barely count.
    """
    n = max(0, evidence_count)
    return round(1.0 - math.exp(-n / _CONFIDENCE_SCALE), 4)


def centroid_update(
    current: list[float] | None, observed: list[float], *, eta: float = ETA
) -> list[float]:
    """Interest-embedding centroid via the same bounded EWMA, per dimension.

    First observation initializes the centroid. Inputs are the post content
    embeddings the mediator already computed — zero extra embedding calls.
    """
    if current is None or len(current) != len(observed):
        return [float(v) for v in observed]
    return [(1.0 - eta) * float(c) + eta * float(o) for c, o in zip(current, observed, strict=True)]
