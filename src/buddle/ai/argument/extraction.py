"""Argument extraction — pure layer (no I/O, no LLM).

Theoretical grounding:

  * Toulmin (1958), *The Uses of Argument* — the six-element model (claim,
    data/grounds, warrant, backing, qualifier, rebuttal). The full six are
    hard to extract reliably from short social text.
  * Stab & Gurevych (2017), *Computational Linguistics* — the validated
    practical reduction: claim / premise plus support/attack relations. High
    annotation agreement and extraction accuracy come precisely from NOT
    trying to recover warrant/backing automatically.
  * Lawrence & Reed (2020) survey confirms the reduced scheme is the field
    standard for argument mining.

So buddle extracts a 4-way reduction — CLAIM, GROUND, REBUTTAL, QUESTION —
and a 3-way stance (PRO / CON / NEUTRAL). Warrant/backing are deferred (v2).

The stub here is rule-based: sentence segmentation + Korean/English discourse
markers ("왜냐하면 / 그래서 / 하지만 / ?"). Deterministic and offline, it gives
the dashboard real structure without a model; a guided-JSON LLM call can
replace `extract_arguments` behind the same dataclasses when models are wired
(the stub->real pattern used throughout the codebase).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from buddle.ai.lang.morph import extract_content_tokens

_MAX_UNITS_PER_POST = 6
_MIN_SENTENCE_CHARS = 6
_MAX_UNIT_CHARS = 240

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。…\n])\s+|(?<=[다요])\s+(?=[A-Z가-힣])")
_WS_RE = re.compile(r"\s+")


class ArgumentKind(StrEnum):
    """Toulmin-reduced unit kind (Stab & Gurevych 2017 scheme + question)."""

    CLAIM = "claim"  # 주장 — a position taken
    GROUND = "ground"  # 근거 — support/evidence/reason for a claim
    REBUTTAL = "rebuttal"  # 반박 — counter or objection
    QUESTION = "question"  # 질문 — opens an issue without asserting


class ArgumentStance(StrEnum):
    """Coarse stance toward the topic (the dashboard's pro/con/neutral split)."""

    PRO = "pro"
    CON = "con"
    NEUTRAL = "neutral"


@dataclass(frozen=True, slots=True)
class ArgumentUnit:
    """One extracted argumentative unit from a post."""

    kind: ArgumentKind
    stance: ArgumentStance
    text: str


# Discourse markers (Korean + English) signalling each role.
_GROUND_MARKERS = re.compile(
    r"(왜냐하면|때문|덕분|니까\b|어서\b|으로 인해|근거는|이유는"
    r"|because|since|due to|the reason)",
    re.IGNORECASE,
)
_REBUTTAL_MARKERS = re.compile(
    r"(하지만|그러나|반면|아니라|그렇지 않|반대로|틀렸|문제는|오히려"
    r"|however|but\b|on the contrary|disagree|wrong)",
    re.IGNORECASE,
)
_CLAIM_MARKERS = re.compile(
    r"(해야|되어야|이다\b|아니다\b|생각한다|주장|믿는다|분명|반드시|중요한 것은"
    r"|should|must|i think|i believe|clearly|the point is)",
    re.IGNORECASE,
)
_QUESTION_MARKERS = re.compile(r"(\?|까\?|나요\?|일까|할까|why\b|what if|how about)", re.IGNORECASE)

# Stance cues — deliberately conservative; most units are NEUTRAL.
_PRO_MARKERS = re.compile(
    r"(찬성|동의|맞다|좋다|지지|필요하다|옳다|해야 한다"
    r"|agree|support|in favor|yes\b|right\b)",
    re.IGNORECASE,
)
_CON_MARKERS = re.compile(
    r"(반대|반박|아니다|틀렸|문제|위험|안 된다|하지 말|우려"
    r"|oppose|against|no\b|wrong|risk|concern)",
    re.IGNORECASE,
)


def _canonical(sentence: str) -> str:
    return _WS_RE.sub(" ", sentence).strip()[:_MAX_UNIT_CHARS]


def _classify_kind(sentence: str) -> ArgumentKind:
    """Marker-priority classification. Order matters: a question marker wins,
    then rebuttal (explicit counter), then ground (explicit reason), else claim.
    Most declarative sentences are claims — the default in argument mining."""
    if _QUESTION_MARKERS.search(sentence):
        return ArgumentKind.QUESTION
    if _REBUTTAL_MARKERS.search(sentence):
        return ArgumentKind.REBUTTAL
    if _GROUND_MARKERS.search(sentence):
        return ArgumentKind.GROUND
    return ArgumentKind.CLAIM


# Strong, unambiguous stance cues — used for grounds, where incidental words
# (e.g. "위험" inside a supporting reason) must not flip the stance.
_STRONG_PRO = re.compile(r"(찬성|동의|지지한다|옳다\b|agree|support|in favor)", re.IGNORECASE)
_STRONG_CON = re.compile(r"(반대|반박한다|틀렸|oppose|against|disagree)", re.IGNORECASE)


def _classify_stance(sentence: str, kind: ArgumentKind) -> ArgumentStance:
    """Stance from cue words. Questions are neutral; rebuttals lean CON.

    Grounds default to NEUTRAL unless a STRONG cue is present: a reason's
    stance properly derives from the claim it supports, not from incidental
    words (e.g. "위험하기 때문이다" supporting a pro-claim shouldn't read CON).
    """
    if kind == ArgumentKind.QUESTION:
        return ArgumentStance.NEUTRAL
    if kind == ArgumentKind.REBUTTAL:
        return ArgumentStance.CON
    if kind == ArgumentKind.GROUND:
        spro = bool(_STRONG_PRO.search(sentence))
        scon = bool(_STRONG_CON.search(sentence))
        if spro and not scon:
            return ArgumentStance.PRO
        if scon and not spro:
            return ArgumentStance.CON
        return ArgumentStance.NEUTRAL
    pro = bool(_PRO_MARKERS.search(sentence))
    con = bool(_CON_MARKERS.search(sentence))
    if pro and not con:
        return ArgumentStance.PRO
    if con and not pro:
        return ArgumentStance.CON
    return ArgumentStance.NEUTRAL


def extract_arguments(text: str, *, max_units: int = _MAX_UNITS_PER_POST) -> list[ArgumentUnit]:
    """Extract Toulmin-reduced argument units from a post body.

    Deterministic. At most `max_units`, deduplicated by canonical text, each
    long enough to be a real argumentative sentence (not a fragment).
    """
    if not text or not text.strip():
        return []

    out: list[ArgumentUnit] = []
    seen: set[str] = set()
    for raw in _SENTENCE_SPLIT_RE.split(text):
        sentence = _canonical(raw)
        if len(sentence) < _MIN_SENTENCE_CHARS:
            continue
        # A unit needs at least one content token to be argumentative.
        if not extract_content_tokens(sentence):
            continue
        if sentence in seen:
            continue
        seen.add(sentence)
        kind = _classify_kind(sentence)
        stance = _classify_stance(sentence, kind)
        out.append(ArgumentUnit(kind=kind, stance=stance, text=sentence))
        if len(out) >= max_units:
            break
    return out
