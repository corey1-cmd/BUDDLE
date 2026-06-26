"""Translation service — produce + store language versions of a post.

When a post is published, the persona's authored text (post.content_transformed
in post.source_language) is translated into the other supported languages and
stored in post_translations. The mediator then delivers each recipient the
version in their preferred language — the same thought crossing the barrier.

Idempotent per (post, language): re-running won't duplicate. Fail-soft: if the
translator errors, we keep whatever versions succeeded (the source is always
available regardless).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from buddle.ai.lang import (
    DEFAULT_LANGUAGES,
    Language,
    TranslationError,
    get_translator,
    normalize_language,
)
from buddle.core.logging import get_logger
from buddle.db.models.post import Post
from buddle.db.models.post_translation import PostTranslation

log = get_logger(__name__)


async def _existing_languages(db: AsyncSession, post_id: uuid.UUID) -> set[str]:
    rows = (
        await db.execute(select(PostTranslation.language).where(PostTranslation.post_id == post_id))
    ).scalars()
    return set(rows)


async def translate_post(
    db: AsyncSession,
    post_id: uuid.UUID,
    *,
    targets: list[Language] | None = None,
    commit: bool = True,
) -> dict[str, str]:
    """Translate a post into target languages and store the versions.

    Returns {language: content} for languages newly created this call. Skips the
    source language and any language already stored (idempotent).
    """
    post = await db.get(Post, post_id)
    if post is None:
        return {}

    source = normalize_language(post.source_language)
    want = targets or list(DEFAULT_LANGUAGES)
    have = await _existing_languages(db, post_id)
    have.add(source.value)  # source needs no translation row

    to_make = [t for t in want if t.value not in have]
    if not to_make:
        return {}

    translator = get_translator()
    created: dict[str, str] = {}
    try:
        versions = await translator.translate_many(
            post.content_transformed, source=source, targets=to_make
        )
    except TranslationError as e:
        log.warning("translation.failed", post_id=str(post_id), error=str(e))
        return {}

    for lang, content in versions.items():
        db.add(PostTranslation(post_id=post_id, language=lang.value, content=content))
        created[lang.value] = content

    if commit and created:
        await db.commit()
    log.info("translation.created", post_id=str(post_id), langs=list(created))
    return created


async def get_post_in_language(
    db: AsyncSession, post_id: uuid.UUID, language: Language
) -> str | None:
    """Return the post body in `language`: the source text if it matches,
    otherwise the stored translation, or None if not available."""
    post = await db.get(Post, post_id)
    if post is None:
        return None
    if normalize_language(post.source_language) == language:
        return post.content_transformed
    row = (
        await db.execute(
            select(PostTranslation.content).where(
                PostTranslation.post_id == post_id,
                PostTranslation.language == language.value,
            )
        )
    ).scalar_one_or_none()
    return row
