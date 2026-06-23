"""Multilingual pipeline tests — languages + translator (no DB).

Verifies the Language enum, normalization, the stub translator's round-trip +
multi-target behavior, the LLM adapter's config guard, and translation_service
signatures. DB-backed translate_post/get_post_in_language run in CI.
"""

from __future__ import annotations

import pytest

from buddle.ai.lang import (
    DEFAULT_LANGUAGES,
    Language,
    StubTranslator,
    normalize_language,
)

# ── Language enum ──────────────────────────────────────────────────────────


def test_default_languages_are_ko_en():
    assert DEFAULT_LANGUAGES == (Language.KO, Language.EN)


def test_language_names():
    assert Language.KO.korean_name == "한국어"
    assert Language.EN.korean_name == "영어"
    assert Language.KO.english_name == "Korean"


def test_normalize_locale_variants():
    assert normalize_language("ko-KR") == Language.KO
    assert normalize_language("EN") == Language.EN
    assert normalize_language("en_US") == Language.EN


def test_normalize_unknown_falls_back():
    assert normalize_language("fr") == Language.KO  # default fallback
    assert normalize_language(None) == Language.KO
    assert normalize_language("zh", fallback=Language.EN) == Language.EN


# ── stub translator ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stub_same_language_roundtrips():
    t = StubTranslator()
    out = await t.translate("안녕", source=Language.KO, target=Language.KO)
    assert out == "안녕"


@pytest.mark.asyncio
async def test_stub_cross_language_marks():
    t = StubTranslator()
    out = await t.translate("안녕", source=Language.KO, target=Language.EN)
    assert out.startswith("[en]")


@pytest.mark.asyncio
async def test_stub_translate_many():
    t = StubTranslator()
    out = await t.translate_many("생각", source=Language.KO, targets=[Language.KO, Language.EN])
    assert out[Language.KO] == "생각"
    assert out[Language.EN].startswith("[en]")


# ── LLM adapter config guard ───────────────────────────────────────────────


def test_llm_translator_requires_endpoint():
    from buddle.ai.lang.llm_translator import LlmTranslator
    from buddle.ai.lang.translator import TranslationError

    with pytest.raises(TranslationError):
        LlmTranslator({})


# ── factory ─────────────────────────────────────────────────────────────────


def test_factory_returns_stub_by_default():
    from buddle.ai.lang import get_translator

    assert isinstance(get_translator(), StubTranslator)


# ── service signatures ──────────────────────────────────────────────────────


def test_translation_service_signatures():
    import inspect

    from buddle.services import translation_service

    p1 = inspect.signature(translation_service.translate_post).parameters
    assert "targets" in p1 and "commit" in p1
    p2 = inspect.signature(translation_service.get_post_in_language).parameters
    assert "language" in p2


def test_post_has_source_language_and_translation_model():
    from buddle.db.models.post import Post
    from buddle.db.models.post_translation import PostTranslation

    assert "source_language" in Post.__table__.columns
    cols = set(PostTranslation.__table__.columns.keys())
    assert {"post_id", "language", "content"} <= cols
    # one row per (post, language)
    uniques = [
        c
        for c in PostTranslation.__table__.constraints
        if c.__class__.__name__ == "UniqueConstraint"
    ]
    assert any({col.name for col in u.columns} == {"post_id", "language"} for u in uniques)
