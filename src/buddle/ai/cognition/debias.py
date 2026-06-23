"""Mediator debiasing inside the persona's cognition.

The mediator's broader role is restructuring/neutralizing content. Here, at the
response-shaping layer, it detects bias signals in the incoming message and
injects guidance so the persona's reply does not adopt or amplify them:
over-generalization ("everyone…", "those people always…"), group labeling, and
absolute/categorical claims.

Important: debiasing shapes the PERSONA'S RESPONSE guidance only. It does not
edit the user's words, does not profile the user, and reads only the current
message — so it cannot itself become a vector for bias. It nudges toward
balance and individuation, consistent with the mediator's neutralizing intent.

Pure and synchronous, rule-based, fully testable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_TOKEN_RE = re.compile(r"[A-Za-z가-힣0-9]+")

# Over-generalization / absolute quantifiers.
_GENERALIZATION_MARKERS = frozenset(
    {
        "다들",
        "모두가",
        "다그래",
        "다 그래",
        "항상",
        "맨날",
        "전부",
        "하나같이",
        "원래",
        "다똑같",
        "다 똑같",
        "늘",
        "절대",
        "무조건",
        "everyone",
        "always",
        "never",
        "all of them",
        "every single",
        "they all",
        "nobody",
    }
)
# Group-labeling cues (a group noun followed by a sweeping claim). We keep this
# generic and small — detecting the *pattern* of labeling, not specific groups.
_LABELING_MARKERS = frozenset(
    {
        "들은 다",
        "들은 원래",
        "들은 항상",
        "those people",
        "that kind of people",
        "그런 사람들",
        "그런것들",
        "그런 것들",
    }
)


@dataclass(frozen=True, slots=True)
class DebiasResult:
    has_bias_signal: bool
    guidance: str
    signals: list[str] = field(default_factory=list)


def _hits(text_lower: str, lexicon: frozenset[str]) -> list[str]:
    return [m for m in lexicon if m in text_lower]


def inspect(text: str) -> DebiasResult:
    """Detect bias signals and produce balancing guidance (pure, synchronous)."""
    lower = " ".join(t.lower() for t in _TOKEN_RE.findall(text))
    raw_lower = text.lower()

    gen = _hits(lower, _GENERALIZATION_MARKERS) or _hits(raw_lower, _GENERALIZATION_MARKERS)
    lab = _hits(raw_lower, _LABELING_MARKERS)

    signals = sorted(set(gen) | set(lab))
    if not signals:
        return DebiasResult(has_bias_signal=False, guidance="", signals=[])

    return DebiasResult(
        has_bias_signal=True,
        guidance=(
            "[편향 주의] 메시지에 일반화나 단정적 표현이 보입니다. 그 틀을 그대로 받아들이거나 "
            "강화하지 말고, 개별 사례로 바라보며 균형 잡힌 시각을 부드럽게 전하세요. "
            "특정 집단을 일반화하거나 낙인찍지 마세요."
        ),
        signals=signals,
    )
