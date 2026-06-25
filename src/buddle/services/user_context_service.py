"""LLM-backed user-context fact extraction.

The pure regex extractor (``user_context.extract_facts``) is high-recall but
low-precision: it will read "나는 행복해" as name="행복", "회사에 있어" as
location="회사". We therefore use the regex ONLY as a cheap gate — if it finds
nothing plausibly disclosed in the message, we skip the network call entirely.
When it does flag a candidate, we ask the persona LLM endpoint (OpenAI-compat,
e.g. Gemini) to extract ONLY clearly-stated facts, which correctly rejects
emotions, adjectives, and common nouns.

Bias-safety contract is preserved: the prompt extracts FACTS only —
name/age/location/occupation/interests — never opinions, worldview, or speech
style. On any failure, or when no endpoint is configured, we return an empty
``UserContextFact`` (prefer false negatives over wrong facts), consistent with
``user_context.py``'s stated philosophy.

The cognition package stays pure (no I/O); all network work lives here.
"""

from __future__ import annotations

import json
import re

import httpx

from buddle.ai.cognition.user_context import UserContextFact, extract_facts
from buddle.core.logging import get_logger

log = get_logger(__name__)

_TIMEOUT = 12.0

_SYSTEM = (
    "당신은 대화에서 사용자가 자신에 대해 '명시적으로 진술한 객관적 사실'만 "
    "추출하는 추출기입니다. 의견·감정·가치관·말투·성격은 절대 포함하지 마세요.\n\n"
    "규칙:\n"
    "- name: 사용자가 자기 이름을 분명히 밝힌 경우만(예: '제 이름은 민수'). "
    "감정·형용사·일반명사('행복','학생','배고파')는 이름이 아닙니다. 아니면 null.\n"
    "- age: 사용자가 자기 나이를 숫자로 밝힌 경우만. 아니면 null.\n"
    "- location: 사용자가 자기 거주지/출신지를 밝힌 경우만(지명). "
    "'회사','집' 같은 일반어는 제외. 아니면 null.\n"
    "- occupation: 사용자가 자기 직업을 밝힌 경우만. 아니면 null.\n"
    "- interests: 사용자가 직접 좋아한다고 말한 구체적 대상만 배열로. 없으면 [].\n\n"
    "주어가 사용자 본인이 아니면(타인·일반론) 모두 null/[]. "
    "다음 JSON으로만 응답하세요(코드블록 없이):\n"
    '{"name": null, "age": null, "location": null, "occupation": null, "interests": []}'
)


def _has_any(fact: UserContextFact) -> bool:
    return bool(
        fact.name
        or fact.age is not None
        or fact.location
        or fact.occupation
        or fact.explicit_interests
    )


async def extract_facts_llm(text: str, *, settings: object) -> UserContextFact:
    """Extract self-disclosed facts from a single message via the LLM endpoint.

    Returns an empty ``UserContextFact`` when nothing is disclosed, when no
    endpoint is configured, or on any error — never raises.
    """
    if not text or not text.strip():
        return UserContextFact()

    # Cheap high-recall gate: skip the network call when nothing is even
    # plausibly disclosed. False positives here only cost an LLM check; the
    # LLM then makes the precise judgement.
    if not _has_any(extract_facts(text)):
        return UserContextFact()

    endpoint_url = getattr(settings, "persona_endpoint_url", "")
    if not endpoint_url:
        # Safe degrade: no facts rather than the buggy regex's wrong facts.
        return UserContextFact()

    api_key = getattr(settings, "persona_endpoint_api_key", "")
    model = getattr(settings, "persona_model", "gemini-2.0-flash")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": text},
        ],
        "temperature": 0.0,
        "max_tokens": 200,
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    url = endpoint_url.rstrip("/") + "/chat/completions"

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        log.warning("user_context.llm_error", error=str(e))
        return UserContextFact()

    return _parse(content)


def _parse(text: str) -> UserContextFact:
    """Parse the LLM JSON response into a UserContextFact; empty on bad JSON."""
    try:
        clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
        data = json.loads(clean)
    except (json.JSONDecodeError, ValueError, AttributeError):
        return UserContextFact()
    if not isinstance(data, dict):
        return UserContextFact()

    raw_name = data.get("name")
    name = str(raw_name).strip() if raw_name else None

    age: int | None = None
    raw_age = data.get("age")
    if raw_age is not None:
        try:
            v = int(raw_age)
            if 1 <= v <= 120:
                age = v
        except (ValueError, TypeError):
            pass

    raw_loc = data.get("location")
    location = str(raw_loc).strip() if raw_loc else None
    raw_occ = data.get("occupation")
    occupation = str(raw_occ).strip() if raw_occ else None

    raw_interests = data.get("interests") or []
    if isinstance(raw_interests, list):
        interests = tuple(
            dict.fromkeys(str(i).strip() for i in raw_interests if str(i).strip())
        )[:10]
    else:
        interests = ()

    return UserContextFact(
        name=name or None,
        age=age,
        location=location or None,
        occupation=occupation or None,
        explicit_interests=interests,
    )
