"""Supported languages for buddle's multilingual pipeline.

Built on two axes first — Korean and English — since the app is being built
Korean-first while English has far more training data/tooling, making English
buildout cheap. The StrEnum is intentionally open so more languages slot in
later without touching call sites.
"""

from __future__ import annotations

from enum import StrEnum


class Language(StrEnum):
    KO = "ko"
    EN = "en"

    @property
    def korean_name(self) -> str:
        return {"ko": "한국어", "en": "영어"}[self.value]

    @property
    def english_name(self) -> str:
        return {"ko": "Korean", "en": "English"}[self.value]


# The two axes we build/translate across by default.
DEFAULT_LANGUAGES: tuple[Language, ...] = (Language.KO, Language.EN)


def normalize_language(value: str | None, *, fallback: Language = Language.KO) -> Language:
    """Coerce an arbitrary locale-ish string ('ko-KR', 'EN', None) to a Language."""
    if not value:
        return fallback
    head = value.strip().lower().replace("_", "-").split("-")[0]
    try:
        return Language(head)
    except ValueError:
        return fallback
