"""Translator abstraction — same swap-in pattern as the ethics classifier.

A Translator turns one text into target-language versions. The stub is a
deterministic pass-through (marks the text) so the whole multilingual pipeline
can be wired + tested with no model. In production swap in an LLM/MT backend
behind the same protocol (translation_provider in config), Korean<->English
first.

Design note: persona voice should be PRESERVED across languages — translation
conveys the same thought/intent, not a literal word swap. The LLM adapter's
prompt makes that explicit; the stub just round-trips.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from buddle.ai.lang.languages import Language


class TranslationError(RuntimeError):
    """Raised when a translation backend fails."""


@runtime_checkable
class Translator(Protocol):
    async def translate(self, text: str, *, source: Language, target: Language) -> str: ...

    async def translate_many(
        self, text: str, *, source: Language, targets: list[Language]
    ) -> dict[Language, str]: ...


class StubTranslator:
    """Deterministic pass-through translator for dev/tests.

    Returns the same text for same-language, and a clearly-marked placeholder
    for cross-language, so tests can assert which versions were produced
    without depending on a real model.
    """

    async def translate(self, text: str, *, source: Language, target: Language) -> str:
        if source == target:
            return text
        return f"[{target.value}] {text}"

    async def translate_many(
        self, text: str, *, source: Language, targets: list[Language]
    ) -> dict[Language, str]:
        out: dict[Language, str] = {}
        for t in targets:
            out[t] = await self.translate(text, source=source, target=t)
        return out
