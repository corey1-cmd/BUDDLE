"""Stage A — Information Processing (EKB).

Processes an incoming message through the five EKB information-processing
sub-stages, grounded in cognitive psychology:

  1. Exposure       — the stimulus is received (tokenize, detect language).
  2. Attention      — selective filter: not all stimuli are processed; extract
                      salient tokens and flag question/request/urgency.
                      (Attention as a limited-capacity selective filter,
                      Broadbent/Treisman.)
  3. Comprehension  — interpret meaning: classify communicative intent, read
                      affect (reusing ai/affect), extract topics.
  4. Acceptance     — judge clarity/relevance: how specific is the message;
                      should the response seek clarification.
  5. Retention      — transfer to long-term memory: build a compact summary +
                      salient points the Decision Process (and future turns)
                      can use.

Pure and rule-based: no LLM call, no I/O. Reads ONLY the current message
(bias-safety contract). A learned model could later replace the internals
behind InformationProcessingResult, but must keep the no-history contract.
"""

from __future__ import annotations

import re

from buddle.ai.affect.perception import Valence, perceive
from buddle.ai.cognition.signals import (
    AttentionResult,
    InformationProcessingResult,
    Intent,
)

_TOKEN_RE = re.compile(r"[A-Za-z가-힣0-9]+")
_HANGUL_RE = re.compile(r"[가-힣]")
_LATIN_RE = re.compile(r"[A-Za-z]")

# Generic stopwords for salience filtering (Attention). Intentionally small
# and generic — not tied to any user/group.
_STOPWORDS = frozenset(
    {
        "그",
        "저",
        "이",
        "것",
        "수",
        "등",
        "및",
        "는",
        "은",
        "가",
        "를",
        "을",
        "에",
        "의",
        "도",
        "고",
        "와",
        "과",
        "나",
        "너",
        "내",
        "거",
        "좀",
        "더",
        "the",
        "a",
        "an",
        "is",
        "are",
        "to",
        "of",
        "and",
        "or",
        "in",
        "on",
        "it",
        "i",
        "you",
        "me",
        "my",
        "so",
        "do",
        "be",
    }
)

# Markers used by the comprehension/attention sub-stages.
_REQUEST_MARKERS = frozenset(
    {
        "해줘",
        "해주",
        "부탁",
        "해줄",
        "해 줘",
        "줘",
        "주세요",
        "해주세요",
        "please",
        "can you",
        "could you",
        "help",
        "fix",
        "make",
    }
)
_URGENT_MARKERS = frozenset(
    {"급해", "빨리", "당장", "지금당장", "긴급", "asap", "urgent", "now", "immediately"}
)
_NEWS_MARKERS = frozenset(
    {"했어", "됐어", "됐다", "해냈", "합격", "성공", "끝냈", "got", "passed", "finished", "won"}
)
_SUPPORT_MARKERS = frozenset(
    {
        "힘들",
        "외로",
        "우울",
        "속상",
        "괴로",
        "지치",
        "불안",
        "포기",
        "lonely",
        "sad",
        "tired",
        "stressed",
    }
)


def _detect_language(text: str) -> str:
    has_ko = bool(_HANGUL_RE.search(text))
    has_en = bool(_LATIN_RE.search(text))
    if has_ko and has_en:
        return "mixed"
    if has_ko:
        return "ko"
    if has_en:
        return "en"
    return "unknown"


def _any_in(text_lower: str, markers: frozenset[str]) -> bool:
    return any(m in text_lower for m in markers)


def _exposure(text: str) -> tuple[list[str], str]:
    """Stage 1: receive the stimulus — tokenize + detect language."""
    tokens = _TOKEN_RE.findall(text)
    return tokens, _detect_language(text)


def _attention(text: str, tokens: list[str]) -> AttentionResult:
    """Stage 2: selective filter — salient tokens + structural flags."""
    lower = text.lower()
    salient = [t for t in tokens if t.lower() not in _STOPWORDS and len(t) > 1]
    # de-dup preserving order, cap to keep it focused (limited capacity)
    seen: set[str] = set()
    deduped: list[str] = []
    for t in salient:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(t)
    deduped = deduped[:12]

    is_question = "?" in text or "까" in lower or "나요" in lower or "어때" in lower
    is_request = _any_in(lower, _REQUEST_MARKERS)
    is_urgent = _any_in(lower, _URGENT_MARKERS)
    return AttentionResult(
        salient_tokens=deduped,
        is_question=is_question,
        is_request=is_request,
        is_urgent=is_urgent,
    )


def _comprehend_intent(text_lower: str, attention: AttentionResult, valence: Valence) -> Intent:
    """Stage 3 (part): classify communicative intent."""
    if attention.is_request:
        return Intent.REQUEST_ACTION
    if _any_in(text_lower, _SUPPORT_MARKERS) and valence == Valence.NEGATIVE:
        return Intent.SEEK_SUPPORT
    if _any_in(text_lower, _NEWS_MARKERS):
        return Intent.SHARE_NEWS
    if attention.is_question:
        return Intent.ASK_INFO
    if valence == Valence.NEUTRAL and not attention.salient_tokens:
        return Intent.REFLECT
    return Intent.MAKE_CONVERSATION


def _acceptance(text: str, attention: AttentionResult) -> tuple[float, bool]:
    """Stage 4: judge clarity/specificity.

    Clarity rises with concrete salient content and message length, and falls
    for very short, vague messages. Low clarity flags that the response may
    need to seek clarification (relevance/credibility judgment in EKB).
    """
    n_salient = len(attention.salient_tokens)
    length = len(text.strip())
    # Simple bounded heuristic.
    clarity = min(1.0, 0.2 + 0.12 * n_salient + min(length, 80) / 200.0)
    needs_clarification = clarity < 0.35 and not attention.is_question
    return round(clarity, 3), needs_clarification


def _retention(
    intent: Intent, topics: list[str], attention: AttentionResult
) -> tuple[str, list[str]]:
    """Stage 5: transfer to long-term memory — compact summary + salient pts."""
    topic_str = ", ".join(topics[:5]) if topics else "(주제 불명확)"
    summary = f"의도={intent.value}; 핵심={topic_str}"
    if attention.is_urgent:
        summary += "; 긴급"
    salient_points = attention.salient_tokens[:6]
    return summary, salient_points


def process_information(text: str) -> InformationProcessingResult:
    """Run the full EKB information-processing stage on a single message."""
    tokens, language = _exposure(text)
    attention = _attention(text, tokens)

    affect = perceive(text)  # reuse the affect module (no duplication)
    lower = text.lower()
    intent = _comprehend_intent(lower, attention, affect.valence)

    # Topics ≈ salient content tokens (transparent; a tagger could refine).
    topics = attention.salient_tokens[:8]

    clarity, needs_clarification = _acceptance(text, attention)
    retained_summary, salient_points = _retention(intent, topics, attention)

    return InformationProcessingResult(
        language=language,
        raw_len=len(text),
        attention=attention,
        intent=intent,
        affect=affect,
        topics=topics,
        clarity=clarity,
        needs_clarification=needs_clarification,
        retained_summary=retained_summary,
        salient_points=salient_points,
    )
