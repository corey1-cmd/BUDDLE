"""Backfill embeddings for posts and personas that lack them.

Run after enabling a real embedding provider, or after importing data created
while embeddings were disabled. Idempotent: only rows with NULL embeddings
are processed. Safe to re-run.

Usage:
    uv run python scripts/backfill_embeddings.py
    docker compose exec api python scripts/backfill_embeddings.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import select

from buddle.ai.embeddings import EmbeddingError, get_embedding_provider
from buddle.db.models.persona import Persona
from buddle.db.models.post import Post
from buddle.db.models.tag import PersonaInterestTag, Tag
from buddle.db.session import AsyncSessionLocal, engine

_BATCH = 64


async def _persona_profile(session, persona: Persona) -> str:  # type: ignore[no-untyped-def]
    rows = await session.execute(
        select(Tag.name)
        .join(PersonaInterestTag, PersonaInterestTag.tag_id == Tag.id)
        .where(PersonaInterestTag.persona_id == persona.id)
    )
    tag_names = [r[0] for r in rows.all()]
    return (persona.name + " " + " ".join(tag_names)).strip()


async def backfill_personas(session, provider) -> int:  # type: ignore[no-untyped-def]
    result = await session.execute(
        select(Persona).where(Persona.context_emb.is_(None))
    )
    personas = list(result.scalars().all())
    if not personas:
        return 0

    profiles = [await _persona_profile(session, p) for p in personas]
    for i in range(0, len(personas), _BATCH):
        chunk = personas[i : i + _BATCH]
        chunk_profiles = profiles[i : i + _BATCH]
        vecs = await provider.embed(chunk_profiles)
        for persona, vec in zip(chunk, vecs, strict=True):
            persona.context_emb = vec
    await session.commit()
    return len(personas)


async def backfill_posts(session, provider) -> int:  # type: ignore[no-untyped-def]
    result = await session.execute(select(Post).where(Post.content_emb.is_(None)))
    posts = list(result.scalars().all())
    if not posts:
        return 0

    for i in range(0, len(posts), _BATCH):
        chunk = posts[i : i + _BATCH]
        texts = [p.content_transformed for p in chunk]
        vecs = await provider.embed(texts)
        for post, vec in zip(chunk, vecs, strict=True):
            post.content_emb = vec
    await session.commit()
    return len(posts)


async def main() -> None:
    print("backfilling embeddings...")
    try:
        provider = get_embedding_provider()
    except EmbeddingError as e:
        print(f"  embedding provider unavailable: {e}")
        return

    async with AsyncSessionLocal() as session:
        n_personas = await backfill_personas(session, provider)
        n_posts = await backfill_posts(session, provider)

    await engine.dispose()
    print(f"  personas embedded: {n_personas}")
    print(f"  posts embedded:    {n_posts}")
    print("done.")


if __name__ == "__main__":
    asyncio.run(main())
