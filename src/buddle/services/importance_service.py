"""Importance service — append signed contributions and recompute the
normalized importance for a post.

Storage model (from Stage 1):
  importance_contributions : append-only log of signed deltas (source, delta)
  importance_scores        : per-post {raw_score, normalized, last_updated}

raw_score      = SUM(importance_contributions.delta)
normalized     = i_max * tanh(raw_score / kappa)

We keep both the append-only log (audit / explainability) and the materialized
score (fast reads for feed/mediator). The recompute sums from the log so the
materialized value can always be rebuilt from first principles.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from buddle.ai.importance import ImportanceParams, normalize
from buddle.config import get_settings
from buddle.db.models.importance import ImportanceContribution, ImportanceScore


def _params() -> ImportanceParams:
    s = get_settings()
    return ImportanceParams(i_max=s.importance_i_max, kappa=s.importance_kappa)


async def add_contribution(
    db: AsyncSession,
    post_id: uuid.UUID,
    *,
    source: str,
    delta: float,
    commit: bool = True,
) -> ImportanceScore:
    """Append a signed contribution and recompute the post's importance.

    source: short tag, e.g. 'mention' | 'like' | 'report' | 'ethics:high'
    delta:  signed magnitude (positive boosts, negative penalizes)
    commit: when False, the caller batches this into a larger transaction.
    """
    db.add(ImportanceContribution(post_id=post_id, source=source, delta=delta))
    await db.flush()

    raw = await db.scalar(
        select(func.coalesce(func.sum(ImportanceContribution.delta), 0.0)).where(
            ImportanceContribution.post_id == post_id
        )
    )
    raw_val = float(raw or 0.0)
    normalized = normalize(raw_val, _params())

    score = await db.get(ImportanceScore, post_id)
    if score is None:
        score = ImportanceScore(post_id=post_id, raw_score=raw_val, normalized=normalized)
        db.add(score)
    else:
        score.raw_score = raw_val
        score.normalized = normalized
        score.last_updated = func.now()

    if commit:
        await db.commit()
        await db.refresh(score)
    else:
        await db.flush()
    return score


async def get_normalized(db: AsyncSession, post_id: uuid.UUID) -> float:
    """Read the materialized normalized importance (0.0 if none)."""
    score = await db.get(ImportanceScore, post_id)
    return float(score.normalized) if score else 0.0


async def recompute(db: AsyncSession, post_id: uuid.UUID) -> ImportanceScore:
    """Rebuild raw + normalized from the contribution log (e.g. after edits)."""
    raw = await db.scalar(
        select(func.coalesce(func.sum(ImportanceContribution.delta), 0.0)).where(
            ImportanceContribution.post_id == post_id
        )
    )
    raw_val = float(raw or 0.0)
    normalized = normalize(raw_val, _params())

    score = await db.get(ImportanceScore, post_id)
    if score is None:
        score = ImportanceScore(post_id=post_id, raw_score=raw_val, normalized=normalized)
        db.add(score)
    else:
        score.raw_score = raw_val
        score.normalized = normalized
        score.last_updated = func.now()
    await db.commit()
    await db.refresh(score)
    return score
