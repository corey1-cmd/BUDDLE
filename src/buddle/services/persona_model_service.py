"""Persona model registry service — admin CRUD + end-user discovery."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from buddle.core.exceptions import Conflict, NotFound
from buddle.db.models.enums import PersonaModelStatus
from buddle.db.models.persona import Persona
from buddle.db.models.persona_model import PersonaModel
from buddle.schemas.persona_model import (
    PersonaModelCreate,
    PersonaModelUpdate,
)

# ── End-user (active models only) ─────────────────────────────────────────


async def list_active_models(db: AsyncSession) -> list[PersonaModel]:
    """Models a regular user can pick when creating a persona."""
    result = await db.execute(
        select(PersonaModel)
        .where(PersonaModel.status == PersonaModelStatus.ACTIVE)
        .order_by(PersonaModel.is_default.desc(), PersonaModel.display_name.asc())
    )
    return list(result.scalars().all())


async def get_active_model_by_key(db: AsyncSession, template_key: str) -> PersonaModel:
    """Find an ACTIVE model by key. Raises NotFound if missing or not active."""
    result = await db.execute(select(PersonaModel).where(PersonaModel.template_key == template_key))
    model = result.scalar_one_or_none()
    if not model or model.status != PersonaModelStatus.ACTIVE:
        raise NotFound(
            "Persona model is not available.",
            detail={"template_key": template_key},
        )
    return model


async def get_model_by_key(db: AsyncSession, template_key: str) -> PersonaModel | None:
    """Find any model by key regardless of status. None if missing."""
    result = await db.execute(select(PersonaModel).where(PersonaModel.template_key == template_key))
    return result.scalar_one_or_none()


# ── Admin ─────────────────────────────────────────────────────────────────


async def admin_list_models(db: AsyncSession) -> list[PersonaModel]:
    result = await db.execute(select(PersonaModel).order_by(PersonaModel.created_at.desc()))
    return list(result.scalars().all())


async def admin_get_model(db: AsyncSession, model_id: uuid.UUID) -> PersonaModel:
    model = await db.get(PersonaModel, model_id)
    if not model:
        raise NotFound("Persona model not found.")
    return model


def _validate_backend_url(backend_kind: object, backend_config: dict | None) -> None:  # type: ignore[type-arg]
    """SSRF-validate any outbound endpoint URL in a backend config.

    Remote backends (vllm_endpoint) carry an endpoint_url the server will call;
    that URL is checked against the SSRF guard so a registered model can't make
    buddle reach internal infra or cloud metadata.
    """
    if not backend_config:
        return
    from buddle.core.ssrf import validate_outbound_url

    url = backend_config.get("endpoint_url")
    if isinstance(url, str) and url:
        validate_outbound_url(url)


async def _validate_backend_url_audited(backend_kind: object, backend_config: dict | None) -> None:  # type: ignore[type-arg]
    """SSRF-validate, recording a security event if a URL is refused."""
    from buddle.core.ssrf import SSRFValidationError
    from buddle.services import security_event_service as sec

    try:
        _validate_backend_url(backend_kind, backend_config)
    except SSRFValidationError as e:
        url = (backend_config or {}).get("endpoint_url")
        await sec.record(
            sec.SSRF_BLOCKED,
            severity="critical",
            extra={"endpoint_url": str(url), "reason": str(e)},
        )
        raise


async def admin_create_model(db: AsyncSession, payload: PersonaModelCreate) -> PersonaModel:
    await _validate_backend_url_audited(payload.backend_kind, payload.backend_config)
    model = PersonaModel(
        template_key=payload.template_key,
        display_name=payload.display_name,
        description=payload.description,
        version=payload.version,
        backend_kind=payload.backend_kind,
        backend_config=payload.backend_config,
        system_prompt=payload.system_prompt,
        status=payload.status,
        is_default=payload.is_default,
    )
    db.add(model)
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise Conflict(
            "A persona model with this template_key already exists.",
            detail={"template_key": payload.template_key},
        ) from e
    await db.refresh(model)
    return model


async def admin_update_model(
    db: AsyncSession, model_id: uuid.UUID, payload: PersonaModelUpdate
) -> PersonaModel:
    model = await admin_get_model(db, model_id)

    if payload.backend_config is not None:
        await _validate_backend_url_audited(
            payload.backend_kind or model.backend_kind, payload.backend_config
        )

    for field in (
        "display_name",
        "description",
        "version",
        "backend_kind",
        "backend_config",
        "system_prompt",
        "status",
        "is_default",
    ):
        value = getattr(payload, field)
        if value is not None:
            setattr(model, field, value)

    await db.commit()
    await db.refresh(model)
    return model


async def admin_delete_model(db: AsyncSession, model_id: uuid.UUID) -> None:
    """Hard delete. Blocked by FK if any personas reference this model.

    To remove a model in active use: PATCH status to 'retired' instead.
    """
    model = await admin_get_model(db, model_id)

    # Pre-check: any persona referencing this model_key?
    ref_count = await db.scalar(
        select(Persona.id).where(Persona.model_key == model.template_key).limit(1)
    )
    if ref_count is not None:
        raise Conflict(
            "Cannot delete a persona model that is in use. Retire it instead.",
            detail={"template_key": model.template_key},
        )

    await db.delete(model)
    await db.commit()
