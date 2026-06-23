"""Multilingual pipeline — languages + translator (Korean/English first)."""

from __future__ import annotations

from buddle.ai.lang.languages import (
    DEFAULT_LANGUAGES,
    Language,
    normalize_language,
)
from buddle.ai.lang.translator import StubTranslator, TranslationError, Translator
from buddle.config import get_settings


def get_translator() -> Translator:
    settings = get_settings()
    kind = settings.translation_provider
    if kind == "stub":
        return StubTranslator()
    if kind == "llm_endpoint":
        from buddle.ai.lang.llm_translator import LlmTranslator

        return LlmTranslator(
            {
                "endpoint_url": settings.translation_endpoint_url,
                "model": settings.translation_model_id or "qwen2.5:7b",
            }
        )
    raise TranslationError(f"Unknown translation_provider: {kind!r}")


__all__ = [
    "DEFAULT_LANGUAGES",
    "Language",
    "StubTranslator",
    "TranslationError",
    "Translator",
    "get_translator",
    "normalize_language",
]
