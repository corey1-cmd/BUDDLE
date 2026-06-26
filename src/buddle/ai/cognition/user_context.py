"""User context — factual self-disclosure extraction.

Resolves the tension between the bias-prevention contract and user profiling
by making the boundary explicit in code:

  - process_information(text) analyzes the CURRENT MESSAGE for intent/affect.
    Its signature enforces no-history, no-profiling (unchanged).

  - UserContextFact accumulates FACTS the user explicitly states about
    themselves (name, age, location, stated interests). These are never
    inferred from linguistic style or opinion — only parsed from
    unambiguous self-disclosure phrases.

  - The persona uses context for RELEVANCE ("you mentioned Seoul"), never to
    ADOPT the user's opinions, worldview, or speech patterns.
    synthesize_prompt_block() enforces this with an explicit instruction.

Allowed in UserContextFact   |  Forbidden (belongs in debias.py)
-----------------------------|----------------------------------
name, age, location           |  political/moral opinions
stated job or interests       |  generalization/bias signals
facts the user volunteers     |  inferred personality from style
                              |  speech pattern mimicry

Pure: no I/O, no LLM, no database.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UserContextFact:
    """Objective facts the user has explicitly stated about themselves.

    None = not yet disclosed. Values come ONLY from direct user statements,
    never from inference. The service layer accumulates these via merge_facts()
    across turns; the cognition pipeline never sees the accumulated version —
    it is injected into the prompt block at the service layer.
    """

    name: str | None = None
    age: int | None = None
    location: str | None = None
    occupation: str | None = None
    explicit_interests: tuple[str, ...] = ()


# ── Extraction patterns ────────────────────────────────────────────────────
# Conservative: require clear self-disclosure phrasing. We prefer false
# negatives (miss a fact) over false positives (wrongly attribute an opinion).

_NAME_KO = re.compile(
    r"(?:나는|저는|제\s*이름은|이름은|이름이)\s*([가-힣]{2,5})"
    r"(?:이야|야|이에요|예요|이라고|입니다|이고|이라\s|라\s)?",
)
_NAME_EN = re.compile(
    r"(?:I[''`]?m|I\s+am|my\s+name\s+is|call\s+me)\s+([A-Z][a-z]{1,20})\b",
    re.IGNORECASE,
)
_AGE_KO = re.compile(r"\b([1-9][0-9]{0,2})\s*살\b")
_AGE_EN = re.compile(r"\b([1-9][0-9]{0,2})\s*(?:years?\s*old|year-old)\b", re.IGNORECASE)
_LOCATION_KO = re.compile(r"([가-힣]{2,8})\s*(?:에\s*살아?|에서\s*살아?|에\s*거주|에\s*있어)")
_LOCATION_EN = re.compile(
    r"(?:live\s+in|living\s+in|based\s+in|I[''`]?m\s+in|I[''`]?m\s+from)\s+"
    r"([A-Za-z][A-Za-z\s]{1,30}?)(?:[.,\n]|$)",
    re.IGNORECASE,
)
_INTEREST_KO = re.compile(
    r"([가-힣A-Za-z]{2,10})(?:을|를)?\s*"
    r"(?:좋아해|좋아함|관심있어|관심\s*있어|즐겨|취미야|취미에요)",
)
_INTEREST_EN = re.compile(
    r"(?:I\s+like|I\s+love|I\s+enjoy|my\s+hobby\s+is|I[''`]?m\s+into)\s+"
    r"([A-Za-z][A-Za-z\s]{1,30}?)(?:[.,\n]|$)",
    re.IGNORECASE,
)
_OCC_KO = re.compile(
    r"(?:직업은|하는\s*일은|직업이)\s*([가-힣A-Za-z\s]{2,15})"
    r"(?:이야|야|이에요|예요|이라고|입니다|이고)?",
)
_OCC_EN = re.compile(
    r"(?:I\s+work\s+as\s+a?n?\s*|I[''`]?m\s+a\s+|I[''`]?m\s+an\s+)"
    r"([A-Za-z][A-Za-z\s]{1,20}?)(?:[.,\n]|$)",
    re.IGNORECASE,
)


def _first(pattern: re.Pattern[str], text: str) -> str | None:
    m = pattern.search(text)
    return m.group(1).strip() if m else None


def _all(pattern: re.Pattern[str], text: str) -> list[str]:
    return [m.group(1).strip() for m in pattern.finditer(text)]


def extract_facts(text: str) -> UserContextFact:
    """Extract explicit self-disclosure facts from a single message.

    Current-message-only — consistent with the process_information contract.
    Returns a UserContextFact with None/empty for anything not found in text.
    """
    if not text or not text.strip():
        return UserContextFact()

    name = _first(_NAME_KO, text) or _first(_NAME_EN, text)

    age: int | None = None
    age_str = _first(_AGE_KO, text) or _first(_AGE_EN, text)
    if age_str:
        try:
            v = int(age_str)
            if 1 <= v <= 120:
                age = v
        except (ValueError, TypeError):
            pass

    location = _first(_LOCATION_KO, text) or _first(_LOCATION_EN, text)
    occupation = _first(_OCC_KO, text) or _first(_OCC_EN, text)

    raw_interests = _all(_INTEREST_KO, text) + _all(_INTEREST_EN, text)
    interests = tuple(dict.fromkeys(raw_interests))

    return UserContextFact(
        name=name,
        age=age,
        location=location,
        occupation=occupation,
        explicit_interests=interests,
    )


def merge_facts(base: UserContextFact, update: UserContextFact) -> UserContextFact:
    """Merge a new fact extraction into the accumulated session context.

    Facts persist once stated: a later message with no name disclosure does
    NOT erase a previously stated name. New disclosures override old ones
    (user corrects themselves). Interests accumulate (set union, order-stable).
    """
    merged_interests = tuple(dict.fromkeys(base.explicit_interests + update.explicit_interests))
    return UserContextFact(
        name=update.name if update.name is not None else base.name,
        age=update.age if update.age is not None else base.age,
        location=update.location if update.location is not None else base.location,
        occupation=update.occupation if update.occupation is not None else base.occupation,
        explicit_interests=merged_interests,
    )


def render_context_block(ctx: UserContextFact) -> str:
    """Render factual context as a prompt block.

    The trailing instruction is the enforcement point: the persona receives
    user facts but is explicitly told not to adopt opinions or speech style.
    Returns empty string when no facts have been disclosed yet.
    """
    lines: list[str] = []
    if ctx.name:
        lines.append(f"이름: {ctx.name}")
    if ctx.age is not None:
        lines.append(f"나이: {ctx.age}살")
    if ctx.location:
        lines.append(f"거주지: {ctx.location}")
    if ctx.occupation:
        lines.append(f"직업: {ctx.occupation}")
    if ctx.explicit_interests:
        lines.append(f"관심사(직접 말함): {', '.join(ctx.explicit_interests)}")
    if not lines:
        return ""
    header = "[사용자 맥락 — 사용자가 직접 말한 사실]\n" + "\n".join(f"- {line}" for line in lines)
    note = (
        "- 위 정보는 대화 관련성을 높이는 데만 사용하세요. "
        "사용자의 의견·관점·말투는 채택하지 않으며, 편향은 흡수하지 않습니다."
    )
    return f"{header}\n{note}"
