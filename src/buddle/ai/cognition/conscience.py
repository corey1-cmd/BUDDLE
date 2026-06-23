"""Leukocyte conscience gate inside the persona's cognition.

Where Part 2's ingestion runs the async ethics classifier to decide whether a
PUBLISHED post is suppressed, THIS gate operates inside the 1:1 dialogue
cognition: it reads risk signals in the incoming message and adjusts the
persona's RESPONSE so the reply is safe and caring — without blocking the
conversation. It never produces harmful content and refuses to give dangerous
information.

Two safety axes:
  1. Self-harm / crisis signals -> force a COMFORT-style, supportive response,
     never informational; surface a flag so the prompt block can add
     help-seeking guidance. (We do not name methods or give instructions.)
  2. Harm-to-others / illicit-instruction signals (violence, weapons, illegal
     how-to) -> the persona must decline to assist and redirect, never provide
     the requested dangerous detail.

Pure and synchronous (rule-based), so it stays inside the no-extra-LLM-call
cognition pipeline and is fully unit-testable. It mirrors the leukocyte's
intent (ethics monitoring + modulation) at the response-shaping layer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from buddle.ai.cognition.signals import ResponseStrategy

_TOKEN_RE = re.compile(r"[A-Za-z가-힣0-9]+")


class ConscienceFlag(StrEnum):
    """Safety condition detected in the incoming message."""

    NONE = "none"
    SELF_HARM = "self_harm"  # crisis / self-harm -> supportive, resourceful
    HARM_TO_OTHERS = "harm_to_others"  # violence/illicit how-to -> refuse + redirect


# Crisis / self-harm signals. We detect to CARE, never to instruct.
_SELF_HARM_MARKERS = frozenset(
    {
        "자살",
        "죽고싶",
        "죽고 싶",
        "자해",
        "목숨",
        "사라지고싶",
        "사라지고 싶",
        "살기싫",
        "살기 싫",
        "suicide",
        "kill myself",
        "self-harm",
        "self harm",
        "end my life",
        "want to die",
    }
)
# Harm-to-others / illicit-instruction signals -> persona must not assist.
_HARM_MARKERS = frozenset(
    {
        "폭탄",
        "사제폭탄",
        "총기제작",
        "무기제작",
        "독극물",
        "해킹방법",
        "마약제조",
        "사람을죽",
        "죽이는법",
        "죽이는 법",
        "테러",
        "bomb",
        "make a weapon",
        "build a bomb",
        "how to kill",
        "poison someone",
        "hack into",
        "synthesize drugs",
    }
)


@dataclass(frozen=True, slots=True)
class ConscienceResult:
    flag: ConscienceFlag
    # If set, the decision's chosen strategy must be overridden to this.
    forced_strategy: ResponseStrategy | None
    guidance: str  # extra system guidance appended for the persona
    signals: list[str] = field(default_factory=list)


def _hits(text_lower: str, lexicon: frozenset[str]) -> list[str]:
    return [m for m in lexicon if m in text_lower]


def inspect(text: str) -> ConscienceResult:
    """Inspect the incoming message for safety conditions (pure, synchronous)."""
    lower = " ".join(t.lower() for t in _TOKEN_RE.findall(text))
    # Also check the raw (markers may contain spaces collapsed above); use both.
    raw_lower = text.lower()

    sh = _hits(lower, _SELF_HARM_MARKERS) or _hits(raw_lower, _SELF_HARM_MARKERS)
    if sh:
        return ConscienceResult(
            flag=ConscienceFlag.SELF_HARM,
            forced_strategy=ResponseStrategy.COMFORT,
            guidance=(
                "[안전 안내] 사용자가 위기/자해 신호를 보입니다. 임상 위기개입 원칙을 따르세요: "
                "(1) 감정을 진심으로 인정하며 마음을 안정시키고, (2) 혼자가 아니라는 신뢰를 전하며, "
                "(3) 무엇이 힘든지 부드럽게 경청하되 방법은 절대 묻거나 알려주지 마세요. "
                "(4) 당장 실천할 수 있는 작은 대처(믿을 만한 사람에게 연락, 안전한 곳에 머물기)를 함께 떠올리고, "
                "(5) 전문 상담(자살예방상담 109, 정신건강위기상담 1577-0199)에 연결되도록 따뜻하게 권하세요. "
                "지시·진단·단정은 피하고, 대처 능력을 북돋는 어조를 유지하세요."
            ),
            signals=sorted(set(sh)),
        )

    ho = _hits(lower, _HARM_MARKERS) or _hits(raw_lower, _HARM_MARKERS)
    if ho:
        return ConscienceResult(
            flag=ConscienceFlag.HARM_TO_OTHERS,
            forced_strategy=ResponseStrategy.CLARIFY,
            guidance=(
                "[안전 안내] 타인에 대한 위해나 위험한 행위를 돕는 요청일 수 있습니다. "
                "위험한 정보나 방법은 절대 제공하지 말고, 정중히 도울 수 없음을 밝힌 뒤 "
                "안전하고 합법적인 방향으로 대화를 전환하세요."
            ),
            signals=sorted(set(ho)),
        )

    return ConscienceResult(flag=ConscienceFlag.NONE, forced_strategy=None, guidance="", signals=[])
