"""MediatorService — the real (Stage 3) mediator AI.

Responsibilities:
  1. tag_and_restructure: keyword tagging + compute a content embedding.
  2. select_distribution_targets: rank candidate personas by

        relevance = alpha * tag_overlap
                  + beta  * content_similarity   (cosine via pgvector)
                  + gamma * user_growth_potential

     using the persisted MediatorPolicy weights, dropping targets below
     min_relevance, and capping at max_targets.

Graceful degradation: if the embedding provider fails, beta is effectively
zeroed (no embedding) and ranking falls back to tag overlap + growth only.
"""

from __future__ import annotations

import re
import uuid
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from buddle.ai.embeddings import EmbeddingError, get_embedding_provider
from buddle.ai.interfaces import DistributionTarget, MediatorTagging
from buddle.core.logging import get_logger
from buddle.db.models.persona import Persona
from buddle.db.models.tag import PersonaInterestTag, Tag

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class PolicyValues:
    """Snapshot of the mediator distribution weights, passed in by the caller
    (loaded from MediatorPolicy). Kept here so the AI layer doesn't depend on
    the service layer."""

    alpha: float
    beta: float
    gamma: float
    max_targets: int
    min_relevance: float


_TOKEN_RE = re.compile(r"[A-Za-z가-힣0-9]{2,}")
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


def _extract_keywords(text: str, top_k: int = 5) -> list[str]:
    tokens = [t.lower() for t in _TOKEN_RE.findall(text)]
    tokens = [t for t in tokens if t not in _STOPWORDS and len(t) >= 2]
    if not tokens:
        return []
    return [w for w, _ in Counter(tokens).most_common(top_k)]


class MediatorService:
    """Embedding-aware mediator. Construct per-request with a DB session and
    the current policy values."""

    def __init__(self, db: AsyncSession, policy: PolicyValues):
        self._db = db
        self._policy = policy

    # ── tagging + embedding ───────────────────────────────────────────────

    async def tag_and_restructure(
        self,
        *,
        content_transformed: str,
        existing_tags: list[str],
    ) -> MediatorTagging:
        derived = _extract_keywords(content_transformed)
        seen: set[str] = set()
        merged: list[str] = []
        for t in [*existing_tags, *derived]:
            tl = t.lower()
            if tl not in seen:
                seen.add(tl)
                merged.append(tl)

        embedding: list[float] | None = None
        try:
            provider = get_embedding_provider()
            embedding = await provider.embed_one(content_transformed)
        except EmbeddingError as e:
            log.warning("mediator.embed_failed", error=str(e))

        return MediatorTagging(
            tag_names=merged[:8],
            summary=content_transformed,
            content_embedding=embedding,
        )

    # ── distribution ──────────────────────────────────────────────────────

    async def select_distribution_targets(
        self,
        *,
        source_persona_id: uuid.UUID,
        content_transformed: str,
        tag_names: list[str],
        content_embedding: list[float] | None = None,
        max_targets: int | None = None,
    ) -> list[DistributionTarget]:
        cap = max_targets if max_targets is not None else self._policy.max_targets

        # Candidate set: active personas (excluding source) that either share a
        # tag or are simply active (so embedding-only matches are possible).
        tag_overlap = await self._tag_overlap_scores(source_persona_id, tag_names)
        sim_scores = await self._similarity_scores(
            source_persona_id, content_embedding, limit=cap * 4
        )

        candidate_ids = set(tag_overlap) | set(sim_scores)
        if not candidate_ids:
            return []

        growth = await self._growth_scores(candidate_ids)

        a, b, g = self._policy.alpha, self._policy.beta, self._policy.gamma
        ranked: list[DistributionTarget] = []
        for pid in candidate_ids:
            relevance = (
                a * tag_overlap.get(pid, 0.0)
                + b * sim_scores.get(pid, 0.0)
                + g * growth.get(pid, 0.0)
            )
            if relevance >= self._policy.min_relevance:
                ranked.append(
                    DistributionTarget(target_persona_id=pid, relevance_score=round(relevance, 4))
                )

        ranked.sort(key=lambda t: t.relevance_score, reverse=True)
        return ranked[:cap]

    # ── score components ──────────────────────────────────────────────────

    async def _tag_overlap_scores(
        self, source_persona_id: uuid.UUID, tag_names: list[str]
    ) -> dict[uuid.UUID, float]:
        """Normalized tag-overlap count in [0, 1] per candidate persona."""
        if not tag_names:
            return {}

        tag_rows = await self._db.execute(select(Tag.id).where(Tag.name.in_(tag_names)))
        tag_ids = [r[0] for r in tag_rows.all()]
        if not tag_ids:
            return {}

        stmt = (
            select(
                Persona.id,
                func.count(PersonaInterestTag.tag_id).label("overlap"),
            )
            .join(PersonaInterestTag, PersonaInterestTag.persona_id == Persona.id)
            .where(
                PersonaInterestTag.tag_id.in_(tag_ids),
                Persona.id != source_persona_id,
                Persona.is_active.is_(True),
            )
            .group_by(Persona.id)
        )
        rows = (await self._db.execute(stmt)).all()
        if not rows:
            return {}
        max_overlap = max(int(r[1]) for r in rows)
        denom = max(max_overlap, 1)
        return {r[0]: int(r[1]) / denom for r in rows}

    async def _similarity_scores(
        self,
        source_persona_id: uuid.UUID,
        content_embedding: list[float] | None,
        *,
        limit: int,
    ) -> dict[uuid.UUID, float]:
        """Cosine similarity of the post embedding to each persona's context
        embedding, in [0, 1]. Returns {} if no embedding available."""
        if content_embedding is None:
            return {}

        # pgvector cosine distance operator <=> returns distance in [0, 2];
        # similarity = 1 - distance/2 maps to [0, 1] (1 = identical direction).
        distance = Persona.context_emb.cosine_distance(content_embedding)
        stmt = (
            select(Persona.id, distance.label("dist"))
            .where(
                Persona.id != source_persona_id,
                Persona.is_active.is_(True),
                Persona.context_emb.isnot(None),
            )
            .order_by(distance)
            .limit(limit)
        )
        rows = (await self._db.execute(stmt)).all()
        return {r[0]: max(0.0, 1.0 - float(r[1]) / 2.0) for r in rows}

    async def _growth_scores(self, candidate_ids: set[uuid.UUID]) -> dict[uuid.UUID, float]:
        """User-growth potential proxy in [0, 1].

        Stage 3 heuristic: personas belonging to users with fewer personas get
        a higher score (spread engagement to less-active users). Replace with a
        real activity/recency signal later.
        """
        if not candidate_ids:
            return {}

        # personas per owning user, among candidates
        stmt = select(Persona.id, Persona.user_id).where(Persona.id.in_(candidate_ids))
        rows = (await self._db.execute(stmt)).all()
        user_of = {r[0]: r[1] for r in rows}

        # Count active personas per user (global), for the involved users
        user_ids = set(user_of.values())
        if not user_ids:
            return {}
        count_rows = await self._db.execute(
            select(Persona.user_id, func.count(Persona.id))
            .where(Persona.user_id.in_(user_ids), Persona.is_active.is_(True))
            .group_by(Persona.user_id)
        )
        per_user = {r[0]: int(r[1]) for r in count_rows.all()}
        max_count = max(per_user.values()) if per_user else 1

        # Fewer personas -> higher growth score
        scores: dict[uuid.UUID, float] = {}
        for pid, uid in user_of.items():
            c = per_user.get(uid, 1)
            scores[pid] = 1.0 - (c - 1) / max(max_count, 1)
        return scores
