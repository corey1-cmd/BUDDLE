"""Persona routes — /v1/personas CRUD."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from buddle.api.deps import DB, CurrentUser
from buddle.schemas.persona import (
    PersonaCreate,
    PersonaDetail,
    PersonaInterestTagRead,
    PersonaQuotaInfo,
    PersonaRead,
    PersonaUpdate,
    TagBrief,
)
from buddle.services import persona_service

router = APIRouter(prefix="/personas", tags=["personas"])


@router.get("/quota", response_model=PersonaQuotaInfo, summary="Current persona quota info")
async def get_quota(user: CurrentUser, db: DB) -> PersonaQuotaInfo:
    return await persona_service.get_quota_info(db, user)


@router.get("", response_model=list[PersonaRead], summary="List my personas")
async def list_personas(user: CurrentUser, db: DB) -> list[PersonaRead]:
    personas = await persona_service.list_personas(db, user)
    return [PersonaRead.model_validate(p) for p in personas]


@router.post(
    "",
    response_model=PersonaDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create a persona",
)
async def create_persona(
    payload: PersonaCreate,
    user: CurrentUser,
    db: DB,
) -> PersonaDetail:
    persona = await persona_service.create_persona(db, user, payload)
    persona, interests = await persona_service.get_persona_with_interest_tags(db, user, persona.id)
    return _to_detail(persona, interests)


@router.get("/{persona_id}", response_model=PersonaDetail, summary="Get persona detail")
async def get_persona(
    persona_id: uuid.UUID,
    user: CurrentUser,
    db: DB,
) -> PersonaDetail:
    persona, interests = await persona_service.get_persona_with_interest_tags(db, user, persona_id)
    return _to_detail(persona, interests)


@router.patch("/{persona_id}", response_model=PersonaDetail, summary="Update a persona")
async def update_persona(
    persona_id: uuid.UUID,
    payload: PersonaUpdate,
    user: CurrentUser,
    db: DB,
) -> PersonaDetail:
    await persona_service.update_persona(db, user, persona_id, payload)
    persona, interests = await persona_service.get_persona_with_interest_tags(db, user, persona_id)
    return _to_detail(persona, interests)


@router.delete(
    "/{persona_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate a persona (soft delete)",
)
async def delete_persona(
    persona_id: uuid.UUID,
    user: CurrentUser,
    db: DB,
) -> None:
    await persona_service.delete_persona(db, user, persona_id)


def _to_detail(persona, interests) -> PersonaDetail:  # type: ignore[no-untyped-def]
    return PersonaDetail(
        id=persona.id,
        name=persona.name,
        model_key=persona.model_key,
        is_active=persona.is_active,
        created_at=persona.created_at,
        location_sharing=persona.location_sharing,
        interest_tags=[
            PersonaInterestTagRead(tag=TagBrief.model_validate(tag), weight=w)
            for tag, w in interests
        ],
    )
