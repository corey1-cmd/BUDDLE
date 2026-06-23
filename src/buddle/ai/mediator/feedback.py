"""Mediator feedback loop — pure rules turning plaza reactions into small,
precise persona-dialogue adjustments.

Design intent (from the spec): connect plaza reactions (reads / likes /
reports / importance) back into the mediator algorithm so it can nudge a
persona's dialogue — but ONLY a little, and precisely. So this module is built
around guardrails, not aggressive learning:

  - Strong-signal gate: weak/noisy signals below a threshold are ignored.
  - Tiny step: each update moves affinity by at most MAX_STEP.
  - Hard clamp: affinity is bounded to [-AFFINITY_CAP, +AFFINITY_CAP] so a
    persona's behavior can drift only slightly, never transform.
  - Safety asymmetry: reports (a safety signal) pull DOWN faster than likes
    push up, and nothing here ever touches warmth or the safety gates.

The affinity is a per-(persona, topic) scalar in [-cap, +cap]. Positive means
"this persona's audience responds well to this topic" → the persona may be
slightly more proactive on it; negative (e.g. reports) → slightly more
reserved. It never changes WHAT is safe, only conversational emphasis.
"""

from __future__ import annotations

from dataclasses import dataclass


# Per-topic reaction tallies the mediator aggregates from the plaza.
@dataclass(frozen=True, slots=True)
class TopicReactions:
    topic: str
    reads: int = 0
    likes: int = 0
    reports: int = 0
    importance: float = 0.0  # summed normalized importance for the topic


# ── Guardrail constants ───────────────────────────────────────────────────
# Each update nudges affinity by at most this much.
MAX_STEP = 0.05
# Affinity is hard-clamped to this absolute bound (small => limited drift).
AFFINITY_CAP = 0.30
# Signals weaker than this (after weighting) are treated as noise and ignored.
SIGNAL_THRESHOLD = 0.5
# Reaction weights. Reports weigh most (safety) and pull down; likes/importance
# push up more gently. Reads are presence, not endorsement — tiny weight.
_W_LIKE = 1.0
_W_IMPORTANCE = 0.8
_W_REPORT = 3.0
_W_READ = 0.05
# Reports pull affinity down faster than likes push it up (safety asymmetry).
_DOWN_GAIN = 1.5


def raw_signal(r: TopicReactions) -> float:
    """Net endorsement signal for a topic (positive = liked, negative = reported)."""
    positive = _W_LIKE * r.likes + _W_IMPORTANCE * r.importance + _W_READ * r.reads
    negative = _W_REPORT * r.reports
    return positive - negative


def affinity_delta(r: TopicReactions) -> float:
    """The bounded, gated step to apply to a persona's topic affinity.

    Returns a value in [-MAX_STEP, +MAX_STEP], or 0 when the signal is too weak
    to act on (strong-signal gate). Negative signals are amplified slightly
    (safety asymmetry) but still clamped to the same tiny step.
    """
    signal = raw_signal(r)
    if abs(signal) < SIGNAL_THRESHOLD:
        return 0.0  # ignore noise — "small amount of precise feedback only"

    # Map the (unbounded) signal to a direction; the magnitude is intentionally
    # NOT proportional to signal size — we only ever take a tiny step, so a
    # viral post can't yank a persona around. Direction + fixed step, with
    # reports pulling down a bit faster (safety asymmetry). The final clamp is
    # applied by apply_affinity.
    if signal > 0:
        return MAX_STEP
    return -MAX_STEP * _DOWN_GAIN


def apply_affinity(current: float, r: TopicReactions) -> float:
    """Apply one bounded update to a current affinity value, clamped to cap."""
    updated = current + affinity_delta(r)
    return max(-AFFINITY_CAP, min(AFFINITY_CAP, updated))


def proactivity_adjustment(affinity: float) -> float:
    """Translate a topic affinity into a SMALL proactivity offset for dialogue.

    Bounded to roughly ±0.1 so the persona's base disposition still dominates —
    feedback only fine-tunes emphasis, per the spec. Only proactivity is
    touched; warmth/safety are never modified here.
    """
    # affinity in [-0.3, 0.3] -> offset in [-0.1, 0.1]
    return round(affinity / 3.0, 4)
