"""Memory service — persistence and recall for persona long-term memory.

The DB half of the LTM (the pure half lives in ``buddle.ai.memory``):

  observe_turn()  — EKB Retention persisted. Extracts disclosure candidates
                    from one user turn; near-duplicates REINFORCE the existing
                    row (strength += 1 — re-disclosure is rehearsal, the
                    Atkinson-Shiffrin transfer mechanism) instead of inserting.
  recall()        — EKB Search served. pgvector cosine candidates re-ranked by
                    the Generative-Agents composite score (recency·importance·
                    relevance); recalled rows are reinforced (ACT-R: retrieval
                    raises base-level activation).
  Capacity bound  — a per-persona cap evicts the weakest rows (lowest
                    strength·importance, oldest access) when exceeded:
                    forgetting as an explicit, bounded operation rather than an
                    unbounded table.

Failure posture: memory must NEVER break a dialogue. Embedding failures fall
back (store without emb / recall by recency); callers additionally wrap these
entry points defensively.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import asc, select
from sqlalchemy.ext.asyncio import AsyncSession

from buddle.ai.embeddings import EmbeddingError, get_embedding_provider
from buddle.ai.memory import (
    MemoryCandidate,
    cosine_from_pgvector_distance,
    extract_candidates,
    memory_score,
)
from buddle.config import get_settings
from buddle.core.logging import get_logger
from buddle.db.models.persona_memory import PersonaMemory

log = get_logger(__name__)

# Near-duplicate threshold for dedup-as-reinforcement. With BGE-M3 this means
# "the same disclosure said again"; with the hashing stub it still catches
# token-identical re-statements (the stub is bag-of-tokens).
_DEDUP_COSINE = 0.92
# Candidate pool fetched from pgvector before composite re-ranking.
_CANDIDATE_POOL = 20


@dataclass(frozen=True, slots=True)
class RecalledMemory:
    """One memory surfaced for the current turn."""

    content: str
    kind: str
    score: float


async def _embed_or_none(text: str) -> list[float] | None:
    """Embed with graceful degradation (mirrors the mediator's posture)."""
    try:
        provider = get_embedding_provider()
        return await provider.embed_one(text)
    except EmbeddingError as e:
        log.warning("memory.embed_failed", error=str(e))
        return None


async def recall(
    db: AsyncSession,
    *,
    persona_id: uuid.UUID,
    query_text: str,
    k: int | None = None,
    now: datetime | None = None,
) -> list[RecalledMemory]:
    """Top-k memories for this turn, by recency·importance·relevance.

    Side effect (intentional, ACT-R): recalled rows get strength += 1 and a
    fresh last_accessed_at — retrieval itself slows their forgetting.
    """
    settings = get_settings()
    if not settings.memory_enabled:
        return []
    top_k = k if k is not None else settings.memory_recall_k
    if top_k <= 0:
        return []
    now = now or datetime.now(UTC)

    query_emb = await _embed_or_none(query_text)

    rows: list[tuple[PersonaMemory, float]]
    if query_emb is not None:
        distance = PersonaMemory.emb.cosine_distance(query_emb)
        stmt = (
            select(PersonaMemory, distance.label("dist"))
            .where(PersonaMemory.persona_id == persona_id, PersonaMemory.emb.isnot(None))
            .order_by(distance)
            .limit(_CANDIDATE_POOL)
        )
        rows = [(r[0], cosine_from_pgvector_distance(r[1])) for r in (await db.execute(stmt)).all()]
    else:
        # Recency-only fallback: no relevance signal available this turn.
        stmt2 = (
            select(PersonaMemory)
            .where(PersonaMemory.persona_id == persona_id)
            .order_by(PersonaMemory.last_accessed_at.desc())
            .limit(_CANDIDATE_POOL)
        )
        rows = [(m, 0.0) for m in (await db.execute(stmt2)).scalars().all()]

    if not rows:
        return []

    scored = sorted(
        (
            (
                m,
                memory_score(
                    cosine_sim=sim,
                    importance=float(m.importance),
                    strength=float(m.strength),
                    last_accessed_at=m.last_accessed_at,
                    now=now,
                ),
            )
            for m, sim in rows
        ),
        key=lambda t: t[1],
        reverse=True,
    )[:top_k]

    # Reinforce what was recalled (retrieval = rehearsal).
    for m, _ in scored:
        m.strength = float(m.strength) + 1.0
        m.last_accessed_at = now
    await db.commit()

    return [
        RecalledMemory(content=m.content, kind=str(m.kind.value), score=round(s, 4))
        for m, s in scored
    ]


async def observe_turn(
    db: AsyncSession,
    *,
    persona_id: uuid.UUID,
    user_text: str,
    session_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> int:
    """Persist this turn's disclosures (EKB Retention). Returns rows written
    or reinforced. Idempotent for repeated identical turns (dedup reinforces)."""
    settings = get_settings()
    if not settings.memory_enabled:
        return 0
    now = now or datetime.now(UTC)

    candidates: list[MemoryCandidate] = extract_candidates(user_text)
    if not candidates:
        return 0

    touched = 0
    for cand in candidates:
        emb = await _embed_or_none(cand.content)

        existing: PersonaMemory | None = None
        if emb is not None:
            distance = PersonaMemory.emb.cosine_distance(emb)
            stmt = (
                select(PersonaMemory, distance.label("dist"))
                .where(PersonaMemory.persona_id == persona_id, PersonaMemory.emb.isnot(None))
                .order_by(distance)
                .limit(1)
            )
            row = (await db.execute(stmt)).first()
            if row is not None and cosine_from_pgvector_distance(row[1]) >= _DEDUP_COSINE:
                existing = row[0]
        else:
            # Embedding-less mode: exact-content dedup still applies.
            stmt2 = select(PersonaMemory).where(
                PersonaMemory.persona_id == persona_id,
                PersonaMemory.content == cand.content,
            )
            existing = (await db.execute(stmt2)).scalars().first()

        if existing is not None:
            # Re-disclosure is rehearsal: strengthen, keep the higher importance.
            existing.strength = float(existing.strength) + 1.0
            existing.importance = max(float(existing.importance), cand.importance)
            existing.last_accessed_at = now
        else:
            db.add(
                PersonaMemory(
                    persona_id=persona_id,
                    kind=cand.kind,
                    content=cand.content,
                    emb=emb,
                    importance=cand.importance,
                    strength=1.0,
                    source_session_id=session_id,
                    created_at=now,
                    last_accessed_at=now,
                )
            )
        touched += 1

    await db.commit()
    await _enforce_capacity(db, persona_id=persona_id, cap=settings.memory_max_per_persona)
    return touched


async def _enforce_capacity(db: AsyncSession, *, persona_id: uuid.UUID, cap: int) -> None:
    """Bounded forgetting: evict the weakest rows beyond the per-persona cap.

    Eviction order = least-activated first (oldest access, lowest strength,
    lowest importance) — the rows the scoring function would rank last anyway.
    """
    if cap <= 0:
        return
    from sqlalchemy import func  # local: keep module imports lean

    count = (
        await db.execute(
            select(func.count(PersonaMemory.id)).where(PersonaMemory.persona_id == persona_id)
        )
    ).scalar_one()
    overflow = int(count) - cap
    if overflow <= 0:
        return

    victims = (
        (
            await db.execute(
                select(PersonaMemory)
                .where(PersonaMemory.persona_id == persona_id)
                .order_by(
                    asc(PersonaMemory.last_accessed_at),
                    asc(PersonaMemory.strength),
                    asc(PersonaMemory.importance),
                )
                .limit(overflow)
            )
        )
        .scalars()
        .all()
    )
    for v in victims:
        await db.delete(v)
    await db.commit()
    log.info("memory.evicted", persona_id=str(persona_id), evicted=len(victims))
