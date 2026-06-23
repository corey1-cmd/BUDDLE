"""Relationship dynamics — pure layer (no I/O, no LLM).

Two validated, quantifiable theories drive every number here:

  * Stages — Social Penetration Theory (Altman & Taylor 1973). Relationships
    deepen through self-disclosure that expands in *breadth* (range of topics)
    and *depth* (intimacy per topic), passing through five stages. SPT is an
    objective theory (experiment-derived), which is why we can map it to
    integer levels and a "Current Level + 1" disclosure target.

  * Score dynamics — Gottman's emotional bank account and the 5:1 "magic
    ratio" (Gottman & Levenson). Stable relationships keep positive:negative
    ≥ 5:1, the asymmetry coming from *negativity bias* (negatives weigh far
    more). So positives are small frequent deposits ("small things often"),
    negatives are heavy withdrawals (~5x), and a self-disclosure by the user
    is an extra deposit because it advances SPT breadth/depth. The reciprocity
    norm (a disclosure invites a disclosure) adds a small bonus when the user
    answers the persona's opening.

All functions are deterministic and unit-testable without a database. The DB
layer (services/conversation_service) persists the running score; this module
only computes deltas and level mappings.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from buddle.ai.affect.perception import Valence

# Base step size for one turn's deposit/withdrawal. Small on purpose:
# relationships move "small things often", not in leaps.
_BASE = 1.2
# Gottman negativity-bias multiplier: a negative turn withdraws ~5x a positive.
_NEGATIVITY_WEIGHT = 5.0
# SPT self-disclosure deposit (user revealed feeling/value/personal fact).
_DISCLOSURE_BONUS = 0.6
# Reciprocity-norm deposit (user answered the persona's opening question).
_RECIPROCITY_BONUS = 0.3
# Per-turn clamp so no single message swings the bond (SPT: later stages slow).
_MAX_ABS_DELTA = _BASE * 3.0

# Score domain and the SPT stage thresholds within it.
_SCORE_MIN = 0.0
_SCORE_MAX = 100.0
# Lower edge of each level: Lv0 [0,8) Lv1 [8,22) Lv2 [22,45) Lv3 [45,72) Lv4 [72,100]
_LEVEL_EDGES = (0.0, 8.0, 22.0, 45.0, 72.0)
# Hysteresis: a level only drops once the score falls this far BELOW its lower
# edge, so one rough exchange doesn't visibly demote the relationship.
_HYSTERESIS = 4.0


class RelationshipLevel(IntEnum):
    """Social Penetration Theory stages as integer levels (0..4)."""

    ORIENTATION = 0  # 첫 만남·표면 잡담 (public scripts)
    EXPLORATORY = 1  # 초기 의견·취향 교환
    AFFECTIVE = 2  # 진짜 견해·가치관·관계 이야기
    STABLE = 3  # 친밀·신뢰, 사적 고민
    INTIMATE = 4  # 핵심 자아 (상한 운영 — 과몰입 방지)


@dataclass(frozen=True, slots=True)
class TurnAffect:
    """The minimal per-turn signal the score needs (from the affect layer)."""

    valence: Valence
    intensity: float  # 0..1


def affinity_delta(
    affect: TurnAffect,
    *,
    opened_disclosure: bool = False,
    is_reciprocity: bool = False,
    current_level: int = 0,
) -> float:
    """Score change for one *user* turn (Gottman emotional bank account).

    POSITIVE → small deposit scaled by intensity.
    NEGATIVE → heavy withdrawal (negativity bias, ~5x).
    NEUTRAL  → tiny deposit (presence is still connection).
    Plus SPT bonuses for self-disclosure and reciprocity.

    `current_level` gently shrinks deposits at higher levels (SPT: penetration
    is fast early, slow late) — withdrawals are NOT shrunk (trust is easier to
    lose than to build).
    """
    inten = min(1.0, max(0.0, affect.intensity))
    magnitude = _BASE * (0.5 + inten)

    if affect.valence == Valence.POSITIVE:
        delta = +magnitude
    elif affect.valence == Valence.NEGATIVE:
        delta = -magnitude * _NEGATIVITY_WEIGHT
    else:  # NEUTRAL
        delta = +_BASE * 0.15

    if opened_disclosure:
        delta += _DISCLOSURE_BONUS
    if is_reciprocity:
        delta += _RECIPROCITY_BONUS

    # Late-stage slowdown applies only to gains.
    if delta > 0 and current_level > 0:
        delta *= 1.0 / (1.0 + 0.15 * current_level)

    return _clamp(delta, -_MAX_ABS_DELTA, _MAX_ABS_DELTA)


def apply_delta(score: float, delta: float) -> float:
    """Add a delta to the running score, clamped to the score domain."""
    return _clamp(score + delta, _SCORE_MIN, _SCORE_MAX)


def level_for_score(score: float, *, current_level: int | None = None) -> RelationshipLevel:
    """Map a score to an SPT level, with downgrade hysteresis.

    Upgrades happen as soon as the score crosses an upper edge. Downgrades
    require the score to fall `_HYSTERESIS` below the current level's lower
    edge — so a single negative turn can't visibly demote the bond.
    """
    raw = _raw_level(score)
    if current_level is None:
        return RelationshipLevel(raw)
    if raw >= current_level:
        return RelationshipLevel(raw)
    # raw < current: only demote if we've fallen clearly below the edge.
    lower_edge = _LEVEL_EDGES[current_level]
    if score >= lower_edge - _HYSTERESIS:
        return RelationshipLevel(current_level)  # hold
    return RelationshipLevel(raw)


def _raw_level(score: float) -> int:
    lvl = 0
    for i, edge in enumerate(_LEVEL_EDGES):
        if score >= edge:
            lvl = i
    return lvl


def disclosure_target_level(current_level: int) -> int:
    """The depth a persona should aim for: Current Level + 1 (SPT), capped at 4.

    Questions/topics one step deeper than the current bond feel like a natural
    invitation; same-level is flat, two-steps-deeper feels invasive.
    """
    return min(int(RelationshipLevel.INTIMATE), max(0, current_level) + 1)


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))
