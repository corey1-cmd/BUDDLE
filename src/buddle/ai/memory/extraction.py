"""LTM extraction — the persistence source for the EKB Retention stage.

EKB (Engel, Kollat & Blackwell 1968; Blackwell, Miniard & Engel, *Consumer
Behavior*) models information processing as Exposure → Attention →
Comprehension → Acceptance → **Retention**, with Retention transferring into
long-term memory that the next decision's **Search** step consults. Stage A of
the cognition pipeline (`buddle.ai.cognition.information`) already implements
the five steps and emits a per-turn retention summary — but nothing persisted
it. This module closes that loop: it turns one user turn into zero or more
durable MemoryCandidates.

Design choices (deliberate, conservative):

  * Reuses Stage A (`process_information`) for affect/intent/salience instead
    of introducing a fourth keyword pipeline — single extraction lineage.
  * Stores *disclosures*, not transcripts: preferences, relations, personal
    facts, lived events. Questions are not disclosures and are skipped.
  * Memorability gate: an importance estimate in [0, 1] must clear
    MIN_IMPORTANCE. Fewer, denser memories beat exhaustive logging (cost: a
    smaller table, fewer prompt tokens; quality: less retrieval noise).
  * Importance blends a kind prior with the message's affect intensity —
    emotionally charged moments are better retained (flashbulb-memory effect,
    Brown & Kulik 1977) — plus a small specificity bonus.
  * Pure + deterministic: same text in, same candidates out (idempotency at
    the service layer builds on this).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from buddle.ai.cognition.information import process_information
from buddle.ai.lang.morph import extract_content_tokens
from buddle.db.models.enums import MemoryKind

MAX_CANDIDATES_PER_TURN = 3
MIN_IMPORTANCE = 0.35
_MIN_SENTENCE_CHARS = 6
_MAX_CONTENT_CHARS = 200

_SENTENCE_SPLIT_RE = re.compile(r"[.!?…\n]+")
_WS_RE = re.compile(r"\s+")

_QUESTION_RE = re.compile(r"(\?|어때|일까|할까|나요|까요|습니까|뭐야|뭘까)\s*$")
_PREFERENCE_RE = re.compile(
    r"(싶다|싶어|좋아해|좋아한다|좋아함|사랑해|싫어해|싫어|싫다|즐겨|제일 좋|최애"
    r"|favorite|love|hate|enjoy|prefer)",
    re.IGNORECASE,
)
_RELATION_RE = re.compile(
    r"(친구|엄마|아빠|어머니|아버지|부모|동생|형|누나|언니|오빠|아내|남편|딸|아들"
    r"|동료|룸메|선배|후배|반려|고양이|강아지)"
)
_EVENT_RE = re.compile(r"(었|았|였|했|갔|왔|봤|더라|다녀)")
_SELF_RE = re.compile(
    r"(나는|내가|내 |나도|나 |저는|제가|제 |저도|우리 |\bi\b|\bmy\b)", re.IGNORECASE
)
_FACT_STATE_RE = re.compile(
    r"(이야|예요|이에요|입니다|이다|살고|사는 |다니|전공|직업|취미|이름은|살이|학년)"
)

_KIND_BASE_IMPORTANCE: dict[MemoryKind, float] = {
    MemoryKind.PREFERENCE: 0.55,
    MemoryKind.RELATION: 0.50,
    MemoryKind.FACT: 0.50,
    MemoryKind.EVENT: 0.40,
}


@dataclass(frozen=True, slots=True)
class MemoryCandidate:
    """One durable memory proposed from a single dialogue turn."""

    kind: MemoryKind
    content: str
    importance: float  # [0, 1] — memorability estimate


def _canonical(sentence: str) -> str:
    return _WS_RE.sub(" ", sentence).strip()[:_MAX_CONTENT_CHARS]


def _classify(sentence: str) -> MemoryKind | None:
    """Disclosure-kind classification; None = not memorable as a disclosure."""
    if _QUESTION_RE.search(sentence):
        return None  # asking is not disclosing
    if _PREFERENCE_RE.search(sentence):
        return MemoryKind.PREFERENCE
    if _RELATION_RE.search(sentence):
        return MemoryKind.RELATION
    if _SELF_RE.search(sentence) and _FACT_STATE_RE.search(sentence):
        return MemoryKind.FACT
    if _EVENT_RE.search(sentence):
        return MemoryKind.EVENT
    return None


def extract_candidates(
    text: str, *, max_candidates: int = MAX_CANDIDATES_PER_TURN
) -> list[MemoryCandidate]:
    """Extract durable-memory candidates from one user turn.

    Deterministic. Returns at most *max_candidates*, each clearing
    MIN_IMPORTANCE, deduplicated by canonical content.
    """
    if not text or not text.strip():
        return []

    # EKB Stage A on the whole message: one affect/salience read, shared by
    # every sentence below (no per-sentence re-analysis — cost discipline).
    info = process_information(text)
    affect_boost = 0.30 * min(1.0, max(0.0, info.affect.intensity))

    out: list[MemoryCandidate] = []
    seen: set[str] = set()
    for raw in _SENTENCE_SPLIT_RE.split(text):
        sentence = _canonical(raw)
        if len(sentence) < _MIN_SENTENCE_CHARS:
            continue
        kind = _classify(sentence)
        if kind is None:
            continue

        specificity = 0.10 if len(extract_content_tokens(sentence)) >= 3 else 0.0
        importance = min(1.0, _KIND_BASE_IMPORTANCE[kind] + affect_boost + specificity)
        if importance < MIN_IMPORTANCE:
            continue

        if sentence in seen:
            continue
        seen.add(sentence)
        out.append(MemoryCandidate(kind=kind, content=sentence, importance=round(importance, 4)))
        if len(out) >= max_candidates:
            break
    return out
