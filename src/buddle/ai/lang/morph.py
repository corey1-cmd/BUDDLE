"""Korean-aware content-token extraction (single canonical tokenizer).

Why this module exists: the LTM extractor (and, later, other keyword paths)
needs Korean noun handling better than "regex word + stopword filter". A
2-char noun fused with a particle ("산에", "집은") is invisible to pure regex
tokenization — the known Phase-3 issue.

Two paths, same contract (deterministic, pure, no I/O):

  1. kiwipiepy (optional extra ``pip install -e ".[korean]"``): a real
     morphological analyzer. We keep general/proper nouns (NNG/NNP) and
     foreign-alphabet tokens (SL), which is exactly the "content word"
     inventory the memory layer cares about.
  2. Fallback (no install): regex tokens + a bounded JOSA-strip rule. For
     tokens of length >= 3 we strip one trailing single-char particle; for the
     problematic 2-char case ("산에" -> "산") we strip only the unambiguous
     locative/object particles, allowing a 1-char noun to survive. This is the
     deterministic 80% fix; kiwipiepy is the 100% fix.

The module is import-safe when kiwipiepy is absent (graceful degradation,
matching the codebase's stub->real philosophy).
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

_TOKEN_RE = re.compile(r"[A-Za-z가-힣0-9]{2,}")
_HANGUL_RE = re.compile(r"^[가-힣]+$")

# Particles that may trail a noun. For length>=3 tokens we strip any of these;
# for length==2 tokens we strip only the high-precision subset (locative /
# object / topic markers) so "산에"->"산" works without mangling real 2-char
# nouns like "사과".
_JOSA_ANY = frozenset("은는이가을를에의도만와과로서께")
_JOSA_2CHAR_SAFE = frozenset("에을를은는도")

_STOPWORDS = frozenset(
    {
        "그리고",
        "그러나",
        "하지만",
        "그래서",
        "이것",
        "저것",
        "그것",
        "여기",
        "저기",
        "거기",
        "정말",
        "진짜",
        "조금",
        "많이",
        "너무",
        "오늘",
        "내일",
        "어제",
        "지금",
        "나는",
        "너는",
        "우리",
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "have",
        "you",
        "are",
        "but",
        "not",
        "all",
        "can",
        "was",
        "were",
    }
)


@lru_cache(maxsize=1)
def _kiwi() -> Any | None:
    """Load the kiwipiepy analyzer once, or None when not installed."""
    try:
        from kiwipiepy import Kiwi  # mypy override: optional [korean] extra
    except Exception:  # ImportError or native-lib load failure
        return None
    try:
        return Kiwi()
    except Exception:  # pragma: no cover - defensive: model load failure
        return None


def kiwi_available() -> bool:
    """True when the optional morphological analyzer is usable."""
    return _kiwi() is not None


def _strip_josa(token: str) -> str:
    """Deterministic particle stripping for the regex fallback path."""
    if not _HANGUL_RE.match(token):
        return token
    if len(token) >= 3 and token[-1] in _JOSA_ANY:
        return token[:-1]
    if len(token) == 2 and token[-1] in _JOSA_2CHAR_SAFE:
        return token[:-1]  # "산에" -> "산" (1-char noun allowed here only)
    return token


def _fallback_tokens(text: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in _TOKEN_RE.findall(text):
        tok = _strip_josa(raw.lower())
        if not tok or tok in _STOPWORDS:
            continue
        if tok not in seen:
            seen.add(tok)
            out.append(tok)
    return out


def _kiwi_tokens(text: str) -> list[str]:
    kiwi = _kiwi()
    assert kiwi is not None  # caller guards
    out: list[str] = []
    seen: set[str] = set()
    for token in kiwi.tokenize(text):
        # NNG: common noun, NNP: proper noun, SL: foreign (latin) word.
        if token.tag not in {"NNG", "NNP", "SL"}:
            continue
        form = str(token.form).lower()
        if len(form) < 1 or form in _STOPWORDS:
            continue
        if form not in seen:
            seen.add(form)
            out.append(form)
    return out


def extract_content_tokens(text: str) -> list[str]:
    """Content words of *text* (dedup, input order), Korean-aware.

    Uses kiwipiepy when installed, the josa-strip fallback otherwise. Both
    paths are deterministic for identical input.
    """
    if not text or not text.strip():
        return []
    if kiwi_available():
        tokens = _kiwi_tokens(text)
        if tokens:
            return tokens
        # Analyzer produced nothing (e.g. emoji-only) -> fall through.
    return _fallback_tokens(text)
