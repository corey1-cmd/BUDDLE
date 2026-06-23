"""Mediator policy service — read/update the singleton distribution weights."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from buddle.ai.mediator.service import PolicyValues
from buddle.core.exceptions import NotFound, ValidationError
from buddle.db.models.mediator_policy import MediatorPolicy


async def get_policy(db: AsyncSession) -> MediatorPolicy:
    row = await db.get(MediatorPolicy, 1)
    if row is None:
        # Self-heal: the singleton should be seeded by migration 0003.
        row = MediatorPolicy(id=1)
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


async def get_policy_values(db: AsyncSession) -> PolicyValues:
    row = await get_policy(db)
    return PolicyValues(
        alpha=float(row.alpha),
        beta=float(row.beta),
        gamma=float(row.gamma),
        max_targets=int(row.max_targets),
        min_relevance=float(row.min_relevance),
    )


async def update_policy(
    db: AsyncSession,
    *,
    alpha: float | None = None,
    beta: float | None = None,
    gamma: float | None = None,
    max_targets: int | None = None,
    min_relevance: float | None = None,
) -> MediatorPolicy:
    row = await db.get(MediatorPolicy, 1)
    if row is None:
        raise NotFound("Mediator policy not initialized.")

    if alpha is not None:
        row.alpha = alpha
    if beta is not None:
        row.beta = beta
    if gamma is not None:
        row.gamma = gamma
    if max_targets is not None:
        if max_targets < 1:
            raise ValidationError("max_targets must be >= 1.")
        row.max_targets = max_targets
    if min_relevance is not None:
        if not (0.0 <= min_relevance <= 1.0):
            raise ValidationError("min_relevance must be in [0, 1].")
        row.min_relevance = min_relevance

    await db.commit()
    await db.refresh(row)
    return row
