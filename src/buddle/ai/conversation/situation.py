"""Conversation situation + mood — pure layer.

Situation (the *purpose* of a turn) decides which response principles apply;
mood (the recent *energy*) decides how strongly the persona should react.
They are deliberately separate axes — "what the user is trying to do" vs.
"the emotional weather of the last few turns" — because matching energy
(Gottman/affect) is independent of matching purpose.

Situation reuses the existing EKB `Intent` taxonomy (no new classifier — one
extraction lineage), and mood aggregates the affect layer's per-turn
valence/intensity over the recent window with an EWMA, so the most recent
turns weigh most (recency-biased working set / locality of reference).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from buddle.ai.affect.perception import Valence
from buddle.ai.cognition.signals import Intent


class ConversationSituation(StrEnum):
    """Why the user is speaking — gates which conversation principles apply."""

    EMPATHIC = "empathic"  # 공감 필요 (sharing distress or joy)
    OBJECTIVE = "objective"  # 사실·정보·피드백 요청 (facts are fine here)
    ASSERTIVE = "assertive"  # 주장·의견 개진
    REFLECTIVE = "reflective"  # 생각 정리 중
    SOCIAL = "social"  # 일상 소통·관계 유지


# Map the EKB intent (already classified upstream) onto a situation. Keeps a
# single classification lineage instead of adding a parallel classifier.
_INTENT_TO_SITUATION: dict[Intent, ConversationSituation] = {
    Intent.SEEK_SUPPORT: ConversationSituation.EMPATHIC,
    Intent.SHARE_NEWS: ConversationSituation.EMPATHIC,
    Intent.ASK_INFO: ConversationSituation.OBJECTIVE,
    Intent.REQUEST_ACTION: ConversationSituation.OBJECTIVE,
    Intent.REFLECT: ConversationSituation.REFLECTIVE,
    Intent.MAKE_CONVERSATION: ConversationSituation.SOCIAL,
}


def situation_for(intent: Intent, *, valence: Valence) -> ConversationSituation:
    """Resolve the conversation situation from EKB intent + affect.

    SHARE_NEWS is empathic only when affect-laden; neutral news is just social
    continuation (sharing a fact ≠ seeking an emotional response).
    """
    base = _INTENT_TO_SITUATION.get(intent, ConversationSituation.SOCIAL)
    if intent == Intent.SHARE_NEWS and valence == Valence.NEUTRAL:
        return ConversationSituation.SOCIAL
    return base


@dataclass(frozen=True, slots=True)
class Mood:
    """Recent emotional weather of the conversation (the window's working set).

    valence: -1..1 (recent positive/negative lean)
    energy:   0..1 (recent affect magnitude — what the persona matches)
    """

    valence: float
    energy: float

    @property
    def label(self) -> str:
        if self.energy < 0.15:
            return "차분함"
        if self.valence > 0.25:
            return "밝음"
        if self.valence < -0.25:
            return "가라앉음"
        return "잔잔함"


# EWMA weight for the newest turn when folding the window (recency bias).
_MOOD_ALPHA = 0.4


def aggregate_mood(window: list[TurnAffect]) -> Mood:
    """EWMA-fold per-turn affect over the recent window (oldest→newest).

    Most recent turns dominate (locality of reference): a conversation that
    just turned heavy reads as heavy even if it opened light.
    """
    if not window:
        return Mood(valence=0.0, energy=0.0)

    val = 0.0
    eng = 0.0
    for i, ta in enumerate(window):
        v = _valence_sign(ta.valence) * min(1.0, max(0.0, ta.intensity))
        e = min(1.0, max(0.0, ta.intensity))
        if i == 0:
            val, eng = v, e
        else:
            val = (1 - _MOOD_ALPHA) * val + _MOOD_ALPHA * v
            eng = (1 - _MOOD_ALPHA) * eng + _MOOD_ALPHA * e
    return Mood(valence=round(val, 3), energy=round(eng, 3))


def _valence_sign(v: Valence) -> float:
    if v == Valence.POSITIVE:
        return 1.0
    if v == Valence.NEGATIVE:
        return -1.0
    return 0.0


# Lightweight Korean/English cue sets for the principle-11-21 signals. These are
# deterministic heuristics (no LLM): they only RAISE guidance, never block, so
# false positives cost at most an extra gentle nudge in the prompt.
_DISTRESS_CUES = (
    "힘들",
    "지쳐",
    "지친",
    "우울",
    "불안",
    "외로",
    "괴로",
    "막막",
    "못 자",
    "못자",
    "스트레스",
    "버겁",
    "포기",
    "tired",
    "exhausted",
    "anxious",
    "lonely",
    "depress",
)
_REQUEST_CUES = (
    "어떻게",
    "방법",
    "어떡",
    "추천",
    "조언",
    "help",
    "how do",
    "how to",
    "should i",
    "what should",
)
_FAREWELL_CUES = (
    "잘 자",
    "잘자",
    "안녕",
    "다음에",
    "이만",
    "가볼게",
    "자야",
    "수고",
    "bye",
    "good night",
    "talk later",
    "gotta go",
    "그만",
)
_DECLINE_CUES = (
    "안 돼",
    "안돼",
    "어려울",
    "못 해",
    "못해",
    "거절",
    "힘들 것 같",
    "곤란",
    "can't",
    "cannot",
    "won't be able",
    "decline",
)


def detect_distress(text: str) -> bool:
    """True if the text carries an emotional-distress cue."""
    return any(c in text for c in _DISTRESS_CUES)


def is_request(text: str) -> bool:
    """True if the text reads as an info/advice/solution request."""
    return any(c in text for c in _REQUEST_CUES) or text.rstrip().endswith("?")


def detect_winding_down(text: str) -> bool:
    """True if the user's message looks like a wind-down / farewell."""
    stripped = text.strip()
    if any(c in stripped for c in _FAREWELL_CUES):
        return True
    # Very short, low-content closers ("ㅇㅇ", "그렇구나") also signal trailing off.
    return len(stripped) <= 4 and not stripped.endswith("?")


def detect_decline_needed(text: str) -> bool:
    """True if the user is asking for something the persona may need to decline.

    Heuristic: a request framed as wanting the persona to do/meet/commit. We keep
    this conservative — it only nudges the persona to decline *gracefully* if it
    declines at all; it never forces a refusal.
    """
    invite = ("만나", "와줘", "와 줘", "해줘", "해 줘", "약속", "meet", "come", "promise")
    return any(c in text for c in invite)


# Re-export TurnAffect from the relationship module so callers have one import
# point for the per-turn signal shape.
from buddle.ai.conversation.relationship import TurnAffect  # noqa: E402

__all__ = [
    "ConversationSituation",
    "Mood",
    "TurnAffect",
    "aggregate_mood",
    "detect_decline_needed",
    "detect_distress",
    "detect_winding_down",
    "is_request",
    "situation_for",
]
