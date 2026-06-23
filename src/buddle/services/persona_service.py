"""Persona CRUD with quota enforcement and registry-backed model validation."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from buddle.ai.embeddings import EmbeddingError, get_embedding_provider
from buddle.config import get_settings
from buddle.core.exceptions import PersonaNotFound, QuotaExceeded, ValidationError
from buddle.core.logging import get_logger
from buddle.db.models.enums import UserTier
from buddle.db.models.persona import Persona
from buddle.db.models.tag import PersonaInterestTag, Tag
from buddle.db.models.user import User
from buddle.schemas.persona import PersonaCreate, PersonaQuotaInfo, PersonaUpdate
from buddle.services.persona_model_service import get_active_model_by_key

log = get_logger(__name__)


async def _compute_context_embedding(
    db: AsyncSession, persona_name: str, tag_ids: list[uuid.UUID]
) -> list[float] | None:
    """Embed a persona's 'interest profile' = name + its interest tag names.

    Returns None if embedding is unavailable (graceful — similarity-based
    distribution just won't match this persona until it's backfilled)."""
    tag_names: list[str] = []
    if tag_ids:
        rows = await db.execute(select(Tag.name).where(Tag.id.in_(tag_ids)))
        tag_names = [r[0] for r in rows.all()]

    profile = persona_name + " " + " ".join(tag_names)
    try:
        provider = get_embedding_provider()
        return await provider.embed_one(profile.strip())
    except EmbeddingError as e:
        log.warning("persona.embed_failed", error=str(e))
        return None


def _tier_quota(tier: UserTier) -> int:
    settings = get_settings()
    return {
        UserTier.FREE: settings.free_persona_quota,
        UserTier.PLUS: settings.plus_persona_quota,
        UserTier.PRO: settings.pro_persona_quota,
    }[tier]


async def _count_active_personas(db: AsyncSession, user_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count(Persona.id)).where(
            Persona.user_id == user_id,
            Persona.is_active.is_(True),
        )
    )
    return int(result.scalar_one())


async def get_quota_info(db: AsyncSession, user: User) -> PersonaQuotaInfo:
    current = await _count_active_personas(db, user.id)
    limit = _tier_quota(user.tier)
    return PersonaQuotaInfo(current=current, limit=limit, remaining=max(0, limit - current))


async def list_personas(db: AsyncSession, user: User) -> list[Persona]:
    result = await db.execute(
        select(Persona).where(Persona.user_id == user.id).order_by(Persona.created_at.desc())
    )
    return list(result.scalars().all())


async def get_persona(db: AsyncSession, user: User, persona_id: uuid.UUID) -> Persona:
    """Fetch a persona owned by the user. Raises PersonaNotFound otherwise."""
    result = await db.execute(
        select(Persona).where(Persona.id == persona_id, Persona.user_id == user.id)
    )
    persona = result.scalar_one_or_none()
    if not persona:
        raise PersonaNotFound()
    return persona


async def _validate_tag_ids(db: AsyncSession, tag_ids: list[uuid.UUID]) -> None:
    if not tag_ids:
        return
    result = await db.execute(select(Tag.id).where(Tag.id.in_(tag_ids)))
    found = {row[0] for row in result.all()}
    missing = [str(t) for t in tag_ids if t not in found]
    if missing:
        raise ValidationError(
            "One or more interest_tag_ids do not exist.",
            detail={"missing_tag_ids": missing},
        )


async def create_persona(db: AsyncSession, user: User, payload: PersonaCreate) -> Persona:
    """Create a persona, enforcing quota and validating the model_key."""
    current = await _count_active_personas(db, user.id)
    limit = _tier_quota(user.tier)
    if current >= limit:
        raise QuotaExceeded(
            f"Persona quota exceeded for tier '{user.tier.value}'.",
            detail={"current": current, "limit": limit, "tier": user.tier.value},
        )

    # Validate model_key against the registry (must exist + be active)
    await get_active_model_by_key(db, payload.model_key)
    await _validate_tag_ids(db, payload.interest_tag_ids)

    if payload.location_sharing and (payload.location_lat is None or payload.location_lon is None):
        raise ValidationError("lat and lon are required when location_sharing is enabled.")

    persona = Persona(
        user_id=user.id,
        name=payload.name,
        model_key=payload.model_key,
        context_emb=await _compute_context_embedding(db, payload.name, payload.interest_tag_ids),
        location_sharing=payload.location_sharing,
        location_lat=payload.location_lat,
        location_lon=payload.location_lon,
    )
    db.add(persona)
    await db.flush()

    if payload.interest_tag_ids:
        db.add_all(
            PersonaInterestTag(persona_id=persona.id, tag_id=tag_id)
            for tag_id in payload.interest_tag_ids
        )

    await db.commit()
    await db.refresh(persona)
    return persona


async def update_persona(
    db: AsyncSession,
    user: User,
    persona_id: uuid.UUID,
    payload: PersonaUpdate,
) -> Persona:
    persona = await get_persona(db, user, persona_id)

    if payload.name is not None:
        persona.name = payload.name

    if payload.model_key is not None:
        # Changing the underlying model is allowed only to active models.
        await get_active_model_by_key(db, payload.model_key)
        persona.model_key = payload.model_key

    if payload.is_active is not None:
        if not persona.is_active and payload.is_active:
            current = await _count_active_personas(db, user.id)
            limit = _tier_quota(user.tier)
            if current >= limit:
                raise QuotaExceeded(
                    "Cannot reactivate: quota exceeded.",
                    detail={"current": current, "limit": limit},
                )
        persona.is_active = payload.is_active

    if payload.interest_tag_ids is not None:
        await _validate_tag_ids(db, payload.interest_tag_ids)
        await db.execute(
            delete(PersonaInterestTag).where(PersonaInterestTag.persona_id == persona.id)
        )
        if payload.interest_tag_ids:
            db.add_all(
                PersonaInterestTag(persona_id=persona.id, tag_id=tag_id)
                for tag_id in payload.interest_tag_ids
            )

    # Recompute the interest embedding if name or tags changed.
    if payload.name is not None or payload.interest_tag_ids is not None:
        if payload.interest_tag_ids is not None:
            tag_ids = payload.interest_tag_ids
        else:
            rows = await db.execute(
                select(PersonaInterestTag.tag_id).where(PersonaInterestTag.persona_id == persona.id)
            )
            tag_ids = [r[0] for r in rows.all()]
        persona.context_emb = await _compute_context_embedding(db, persona.name, tag_ids)

    # Location-based chat fields (opt-in). Updated only when provided so a
    # caller changing just the name doesn't clear coordinates.
    if payload.location_sharing is not None:
        if payload.location_sharing:
            new_lat = payload.location_lat if payload.location_lat is not None else persona.location_lat
            new_lon = payload.location_lon if payload.location_lon is not None else persona.location_lon
            if new_lat is None or new_lon is None:
                raise ValidationError(
                    "lat and lon are required when location_sharing is enabled."
                )
            persona.location_lat = new_lat
            persona.location_lon = new_lon
        persona.location_sharing = payload.location_sharing
    else:
        if payload.location_lat is not None:
            persona.location_lat = payload.location_lat
        if payload.location_lon is not None:
            persona.location_lon = payload.location_lon

    await db.commit()
    await db.refresh(persona)
    return persona


async def delete_persona(db: AsyncSession, user: User, persona_id: uuid.UUID) -> None:
    """Soft-delete (is_active=False). Hard delete is admin-only."""
    persona = await get_persona(db, user, persona_id)
    persona.is_active = False
    await db.commit()


async def get_persona_with_interest_tags(
    db: AsyncSession, user: User, persona_id: uuid.UUID
) -> tuple[Persona, list[tuple[Tag, float]]]:
    persona = await get_persona(db, user, persona_id)
    result = await db.execute(
        select(Tag, PersonaInterestTag.weight)
        .join(PersonaInterestTag, PersonaInterestTag.tag_id == Tag.id)
        .where(PersonaInterestTag.persona_id == persona.id)
    )
    interests = [(row[0], float(row[1])) for row in result.all()]
    return persona, interests
