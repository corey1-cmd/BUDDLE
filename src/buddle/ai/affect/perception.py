"""Language affect perception — read the emotional tone and intent of a single
message so a persona can respond more humanely.

Evidence base (so the design isn't ad hoc):
  - Empathetic response = emotional understanding + validation + reflection
    (qualitative study of commercial mental-health chatbots, PMC12643404).
  - Active Constructive Responding (ACR): when someone shares good news,
    respond actively and positively — capitalization boosts wellbeing and
    relationship quality (Gable et al., 2004, JPSP).
  - Nonjudgmental active listening is the most-cited helpful trait of support
    chatbots (Vivibot/Woebot trials).

ANTI-BIAS DESIGN (a hard requirement):
  - Perception looks ONLY at the current message. It does NOT build a profile
    of the user, does NOT learn from or imitate the user's wording, and does
    NOT adapt to a group's style. So it cannot amplify or entrench bias from
    conversation history — there is no history input here by design.
  - It detects *affective signals* (valence, sharing-good-news, distress,
    question), not identity or demographics. Output is a neutral analysis used
    to pick a *response posture*, never to mirror content back.

This module is pure (no I/O, no model). It's a transparent, rule-based signal
extractor; a learned classifier could replace it later behind the same
PerceivedAffect interface, but it must keep the no-history, no-profiling
contract.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

_TOKEN_RE = re.compile(r"[A-Za-z가-힣0-9]+")


class Valence(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class ResponsePosture(StrEnum):
    """The humane response stance suggested for the persona."""

    CELEBRATE = "celebrate"  # ACR: amplify shared good news
    SUPPORT = "support"  # validate + gentle support for distress
    ENCOURAGE = "encourage"  # light encouragement for mild negativity
    ENGAGE = "engage"  # curious, answer a question / continue
    REFLECT = "reflect"  # neutral: reflect + open question


# Small, transparent lexicons. Deliberately generic affect words — NOT tied to
# any person or group. These are signal hints, not a sentiment model.
_POSITIVE = frozenset(
    {
        "기쁘",
        "행복",
        "좋",
        "최고",
        "신나",
        "감사",
        "고마",
        "사랑",
        "성공",
        "합격",
        "축하",
        "해냈",
        "즐거",
        "설레",
        "뿌듯",
        "happy",
        "great",
        "love",
        "excited",
        "thanks",
        "awesome",
        "win",
        "passed",
        "proud",
        "glad",
    }
)
_NEGATIVE = frozenset(
    {
        "슬프",
        "힘들",
        "우울",
        "외로",
        "지치",
        "불안",
        "화나",
        "짜증",
        "실패",
        "걱정",
        "두려",
        "속상",
        "괴로",
        "무서",
        "포기",
        "sad",
        "tired",
        "lonely",
        "anxious",
        "angry",
        "fail",
        "worried",
        "scared",
        "upset",
        "stressed",
    }
)
# Higher-intensity distress markers raise the posture from ENCOURAGE to SUPPORT.
_DISTRESS = frozenset(
    {"우울", "외로", "불안", "두려", "괴로", "포기", "lonely", "anxious", "depressed"}
)
# Markers that someone is sharing good news (capitalization opportunity).
_GOOD_NEWS = frozenset(
    {"합격", "성공", "해냈", "축하", "됐어", "됐다", "passed", "got", "won", "finished"}
)


@dataclass(frozen=True, slots=True)
class PerceivedAffect:
    valence: Valence
    posture: ResponsePosture
    is_question: bool
    intensity: float  # 0..1 rough magnitude of affect
    signals: list[str] = field(default_factory=list)


def _count_hits(tokens_joined: str, lexicon: frozenset[str]) -> tuple[int, list[str]]:
    hits = [w for w in lexicon if w in tokens_joined]
    return len(hits), hits


def perceive(text: str) -> PerceivedAffect:
    """Analyze a single message's affect. No history, no profiling."""
    joined = " ".join(t.lower() for t in _TOKEN_RE.findall(text))
    is_question = "?" in text or "까" in text or "나요" in text

    pos_n, pos_hits = _count_hits(joined, _POSITIVE)
    neg_n, neg_hits = _count_hits(joined, _NEGATIVE)
    _, good_hits = _count_hits(joined, _GOOD_NEWS)
    _, distress_hits = _count_hits(joined, _DISTRESS)

    total = pos_n + neg_n
    intensity = min(1.0, total / 3.0) if total else 0.0

    if pos_n > neg_n:
        valence = Valence.POSITIVE
    elif neg_n > pos_n:
        valence = Valence.NEGATIVE
    else:
        valence = Valence.NEUTRAL

    # Decide posture (evidence-aligned):
    if valence == Valence.POSITIVE and good_hits:
        posture = ResponsePosture.CELEBRATE  # ACR capitalization
    elif valence == Valence.NEGATIVE and distress_hits:
        posture = ResponsePosture.SUPPORT  # validate + support
    elif valence == Valence.NEGATIVE:
        posture = ResponsePosture.ENCOURAGE
    elif is_question:
        posture = ResponsePosture.ENGAGE
    elif valence == Valence.POSITIVE:
        posture = ResponsePosture.CELEBRATE
    else:
        posture = ResponsePosture.REFLECT

    signals = sorted({*pos_hits, *neg_hits})
    return PerceivedAffect(
        valence=valence,
        posture=posture,
        is_question=is_question,
        intensity=round(intensity, 3),
        signals=signals,
    )
