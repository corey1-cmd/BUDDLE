"""Admin routes for the persona model registry — /v1/admin/persona-models.

This is the runtime endpoint for registering newly-trained persona models.
Workflow:
  1. Train a persona model offline (e.g., LoRA adapter for Qwen3-7B).
  2. Upload artifacts to model storage (S3, HF Hub, ...).
  3. POST here with backend_kind + backend_config pointing at the artifact.
  4. status='draft' -> 'staging' (admin testing) -> 'active' (visible to users).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from buddle.api.deps import DB, CurrentAdmin
from buddle.schemas.persona_model import (
    PersonaModelAdmin,
    PersonaModelCreate,
    PersonaModelUpdate,
)
from buddle.services import persona_model_service

router = APIRouter(prefix="/persona-models", tags=["admin:persona-models"])


@router.get(
    "",
    response_model=list[PersonaModelAdmin],
    summary="List all persona models (any status)",
)
async def list_models(_: CurrentAdmin, db: DB) -> list[PersonaModelAdmin]:
    models = await persona_model_service.admin_list_models(db)
    return [PersonaModelAdmin.model_validate(m) for m in models]


@router.post(
    "",
    response_model=PersonaModelAdmin,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new persona model",
)
async def create_model(
    payload: PersonaModelCreate,
    _: CurrentAdmin,
    db: DB,
) -> PersonaModelAdmin:
    model = await persona_model_service.admin_create_model(db, payload)
    return PersonaModelAdmin.model_validate(model)


@router.get(
    "/{model_id}",
    response_model=PersonaModelAdmin,
    summary="Get a persona model by id",
)
async def get_model(
    model_id: uuid.UUID,
    _: CurrentAdmin,
    db: DB,
) -> PersonaModelAdmin:
    model = await persona_model_service.admin_get_model(db, model_id)
    return PersonaModelAdmin.model_validate(model)


@router.patch(
    "/{model_id}",
    response_model=PersonaModelAdmin,
    summary="Update a persona model (e.g., bump version, change status, swap backend)",
)
async def update_model(
    model_id: uuid.UUID,
    payload: PersonaModelUpdate,
    _: CurrentAdmin,
    db: DB,
) -> PersonaModelAdmin:
    model = await persona_model_service.admin_update_model(db, model_id, payload)
    return PersonaModelAdmin.model_validate(model)


@router.delete(
    "/{model_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Hard-delete a persona model (blocked if any personas reference it)",
)
async def delete_model(
    model_id: uuid.UUID,
    _: CurrentAdmin,
    db: DB,
) -> None:
    await persona_model_service.admin_delete_model(db, model_id)
