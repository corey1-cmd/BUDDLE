"""Public persona model discovery — users see ACTIVE models when creating personas."""

from __future__ import annotations

from fastapi import APIRouter

from buddle.api.deps import DB, CurrentUser
from buddle.schemas.persona_model import PersonaModelPublic
from buddle.services import persona_model_service

router = APIRouter(prefix="/persona-models", tags=["persona-models"])


@router.get(
    "",
    response_model=list[PersonaModelPublic],
    summary="List active persona models (selectable when creating a persona)",
)
async def list_active_models(_: CurrentUser, db: DB) -> list[PersonaModelPublic]:
    models = await persona_model_service.list_active_models(db)
    return [PersonaModelPublic.model_validate(m) for m in models]
