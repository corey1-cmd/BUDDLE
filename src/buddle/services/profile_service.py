"""Profile service — observation + the four sovereignty rights.

Observation sources (both zero-extra-cost):
  * dialogue turns  → trait signals (lexicon estimator, runs after the reply
                      is sent, same place as memory observation)
  * post pipeline   → interest centroid (reuses the content embedding the
                      mediator already computed)

Sovereignty enforcement order inside every observer:
  opt-out → no-op;  user-edited → trait updates frozen (interests continue:
  the user edited their *traits*, not their topical footprint — and interests
  also stop under opt-out). The rights API (api/v1/profile.py) maps 1:1 onto
  get/update/delete here.

Failure posture: profiling must never break a dialogue or a post — observers
swallow nothing themselves but every caller wraps them defensively, matching
the memory layer's contract.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from buddle.ai.profile import (
    TraitSignals,
    centroid_update,
    confidence_from_evidence,
    estimate_trait_signals,
    ewma_update,
)
from buddle.config import get_settings
from buddle.core.logging import get_logger
from buddle.db.models.user_profile import UserProfile

log = get_logger(__name__)

_TRAIT_FIELDS = ("o", "c", "e", "a", "n")


async def get_profile(db: AsyncSession, user_id: uuid.UUID) -> UserProfile | None:
    return (
        await db.execute(select(UserProfile).where(UserProfile.user_id == user_id))
    ).scalar_one_or_none()


async def _get_or_create(db: AsyncSession, user_id: uuid.UUID) -> UserProfile:
    profile = await get_profile(db, user_id)
    if profile is None:
        profile = UserProfile(user_id=user_id)
        db.add(profile)
        await db.flush()
    return profile


async def observe_text(db: AsyncSession, *, user_id: uuid.UUID, text: str) -> bool:
    """Trait observation from one utterance. Returns True when applied.

    Honors opt-out (skip entirely) and user-edit freeze (traits untouched).
    Evidence/confidence advance only when at least one trait signal fired —
    silence about personality is not evidence of personality.
    """
    if not get_settings().profile_enabled:
        return False
    signals: TraitSignals = estimate_trait_signals(text)
    if not signals.any():
        return False

    profile = await _get_or_create(db, user_id)
    if profile.profile_opt_out:
        return False
    if profile.is_user_edited:
        return False  # 수정권: the user's word is final; auto-updates freeze.

    for field in _TRAIT_FIELDS:
        observed = getattr(signals, field)
        if observed is None:
            continue
        setattr(profile, field, ewma_update(float(getattr(profile, field)), float(observed)))
    profile.evidence_count = int(profile.evidence_count) + 1
    profile.confidence = confidence_from_evidence(profile.evidence_count)
    await db.commit()
    return True


async def observe_interest_embedding(
    db: AsyncSession, *, user_id: uuid.UUID, embedding: list[float], commit: bool = True
) -> bool:
    """Interest-centroid observation from a post's existing content embedding.

    `commit=False` lets the post pipeline carry this update inside its own
    atomic transaction (rollback rolls the profile back too — correct)."""
    if not get_settings().profile_enabled or not embedding:
        return False
    profile = await _get_or_create(db, user_id)
    if profile.profile_opt_out:
        return False
    current = list(profile.interests_emb) if profile.interests_emb is not None else None
    profile.interests_emb = centroid_update(current, [float(v) for v in embedding])
    if commit:
        await db.commit()
    return True


async def update_profile(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    traits: dict[str, float] | None = None,
    profile_opt_out: bool | None = None,
) -> UserProfile:
    """수정권 + 거부권. Setting any trait marks the profile user-edited
    (automatic trait updates freeze) and pins confidence to 1.0 — a
    self-report outranks every inference (it is the criterion the inference
    literature validates against)."""
    profile = await _get_or_create(db, user_id)
    if traits:
        for field, value in traits.items():
            if field in _TRAIT_FIELDS and value is not None:
                setattr(profile, field, min(1.0, max(0.0, float(value))))
        profile.is_user_edited = True
        profile.confidence = 1.0
    if profile_opt_out is not None:
        profile.profile_opt_out = bool(profile_opt_out)
    await db.commit()
    await db.refresh(profile)
    return profile


async def delete_profile(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """삭제권: drop the row entirely. Recreated lazily only if observation
    resumes (i.e. the user keeps using the product without opting out)."""
    profile = await get_profile(db, user_id)
    if profile is None:
        return False
    await db.delete(profile)
    await db.commit()
    return True
