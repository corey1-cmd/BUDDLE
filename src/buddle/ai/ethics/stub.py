"""Rule-based ethics classifier for dev and tests (Korean-first, multi-label).

Transparent and dependency-free. Matches lowercased + jamo-normalized content
against per-category keyword sets for the MLCommons 13-hazard taxonomy, and
returns INDEPENDENT per-category results (multi-label, binary-relevance) — a
message can fire several categories at once (e.g. hate + violence), mirroring
OpenAI/Azure moderation outputs.

This is NOT a trained safety model; it exists so the leukocyte pipeline and its
downstream effects can be wired and tested deterministically. In production,
swap in local_hf (e.g. a KR-BERT / sub-character model fine-tuned on K-MHaS /
KOLD / K-HATERS) or vllm_endpoint (e.g. Llama Guard 3) behind the same
EthicsClassifier protocol.

Korean handling notes (from the dataset literature):
  - Korean hate speech benefits from sub-character (jamo) awareness; we add a
    light jamo-decomposition pass so obfuscated spacing/낱자 still matches.
  - Hate is inherently multi-label + target-oriented (KOLD/K-MHaS), so several
    categories may co-fire.
"""

from __future__ import annotations

import re
import unicodedata

from buddle.ai.ethics.base import CategoryResult, EthicsAssessment
from buddle.ai.ethics.taxonomy import HazardCategory

_TOKEN_RE = re.compile(r"[A-Za-z가-힣0-9]+")


def _normalize(text: str) -> str:
    """Lowercased token stream joined by spaces for substring checks."""
    return " ".join(t.lower() for t in _TOKEN_RE.findall(text))


def _jamo(text: str) -> str:
    """NFD decomposition collapses 한글 to component jamo, so spaced/obfuscated
    syllables ('죽 고 싶') still contain the decomposed sequence of '죽고싶'."""
    return unicodedata.normalize("NFD", text.lower()).replace(" ", "")


# Per-category keyword sets + the 0-7 severity assigned when the category fires.
# Keywords are deliberately generic placeholders for a real classifier. Korean
# and English terms are mixed since buddle is Korean-first but bilingual.
_RULES: dict[HazardCategory, tuple[int, frozenset[str]]] = {
    HazardCategory.SUICIDE_SELF_HARM: (
        6,
        frozenset(
            {
                "자살",
                "자해",
                "죽고싶",
                "죽고 싶",
                "목숨",
                "사라지고싶",
                "살기싫",
                "섭식장애",
                "suicide",
                "selfharm",
                "self-harm",
                "kill myself",
                "want to die",
            }
        ),
    ),
    HazardCategory.VIOLENT_CRIMES: (
        6,
        frozenset(
            {
                "살인",
                "납치",
                "폭행",
                "테러",
                "사람을죽",
                "죽이는법",
                "죽이",
                "죽여",
                "패버",
                "때려죽",
                "kill",
                "murder",
                "kidnap",
                "assault",
                "terror",
            }
        ),
    ),
    HazardCategory.INDISCRIMINATE_WEAPONS: (
        7,
        frozenset(
            {
                "폭탄",
                "사제폭탄",
                "생물무기",
                "화학무기",
                "핵무기",
                "독가스",
                "bomb",
                "nerve gas",
                "anthrax",
                "bioweapon",
                "nuclear weapon",
            }
        ),
    ),
    HazardCategory.SEX_CRIMES: (
        6,
        frozenset({"성폭력", "강간", "성희롱", "성매매", "rape", "sexual assault"}),
    ),
    HazardCategory.CHILD_EXPLOITATION: (
        7,
        frozenset({"아동성", "미성년성", "child abuse", "csam"}),
    ),
    HazardCategory.HATE: (
        4,
        frozenset(
            {
                "개새끼",
                "병신",
                "꺼져",
                "혐오",
                "비하",
                "차별",
                "idiot",
                "moron",
                "subhuman",
                "go back to",
            }
        ),
    ),
    HazardCategory.NON_VIOLENT_CRIMES: (
        4,
        frozenset(
            {
                "마약제조",
                "해킹방법",
                "자금세탁",
                "사기치는법",
                "위조",
                "hack into",
                "launder money",
                "counterfeit",
                "make drugs",
            }
        ),
    ),
    HazardCategory.SEXUAL_CONTENT: (
        3,
        frozenset({"야설", "음란", "포르노", "erotica", "explicit sex"}),
    ),
    HazardCategory.PRIVACY: (
        3,
        frozenset({"주민등록번호", "주민번호", "신상털", "doxx", "home address of"}),
    ),
    HazardCategory.DEFAMATION: (
        3,
        frozenset({"허위사실", "명예훼손", "is a fraud", "spreading lies about"}),
    ),
    HazardCategory.SPECIALIZED_ADVICE: (
        2,
        frozenset({"약물복용량", "투자확정", "guaranteed returns", "self-medicate dose"}),
    ),
    HazardCategory.ELECTIONS: (
        3,
        frozenset({"투표조작", "선거조작", "voting is rigged on", "fake ballot"}),
    ),
    HazardCategory.INTELLECTUAL_PROPERTY: (
        2,
        frozenset({"불법다운", "토렌트크랙", "pirated copy", "crack serial"}),
    ),
}

# Confidence score per 0-7 severity (monotone). Used as the per-category score.
_SCORE_BY_LEVEL = {
    0: 0.0,
    1: 0.15,
    2: 0.3,
    3: 0.45,
    4: 0.6,
    5: 0.75,
    6: 0.9,
    7: 0.97,
}


class StubEthicsClassifier:
    """Deterministic multi-label rule classifier over the 13-hazard taxonomy."""

    async def assess(self, text: str) -> EthicsAssessment:
        haystack = _normalize(text)
        jamo = _jamo(text)

        results: list[CategoryResult] = []
        for category, (level, keywords) in _RULES.items():
            hit = any(kw.lower() in haystack or _jamo(kw) in jamo for kw in keywords)
            if hit:
                results.append(
                    CategoryResult(
                        category=category,
                        severity07=level,
                        score=_SCORE_BY_LEVEL[level],
                    )
                )

        if not results:
            return EthicsAssessment.safe(metadata={"classifier": "stub"})

        names = ", ".join(c.category.value for c in results)
        return EthicsAssessment.from_categories(
            results,
            reason=f"matched categories: {names}",
            metadata={"classifier": "stub"},
        )
