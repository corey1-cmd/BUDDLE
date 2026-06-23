"""Knowledge space routes — /v1: persona context + admin management (Layer B)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from fastapi import APIRouter, Query
from pydantic import BaseModel

from buddle.api.deps import DB, CurrentUser
from buddle.core.exceptions import NotFound
from buddle.db.models.persona import Persona
from buddle.services import knowledge_service

router = APIRouter(prefix="/personas/{persona_id}/context", tags=["knowledge"])


class ContextItemOut(BaseModel):
    unit_id: uuid.UUID
    gist: str
    topic_tags: str
    language: str


class ContextOut(BaseModel):
    topic: str
    related_topics: list[str]
    items: list[ContextItemOut]


async def _owned(db: DB, user_id: uuid.UUID, persona_id: uuid.UUID) -> Persona:
    p = await db.get(Persona, persona_id)
    if p is None or p.user_id != user_id:
        raise NotFound("Persona not found.")
    return p


@router.get("", response_model=ContextOut, summary="Reference material for a topic")
async def get_context(
    persona_id: uuid.UUID,
    user: CurrentUser,
    db: DB,
    topic: str = Query(min_length=1, max_length=64),
    limit: int = Query(default=8, ge=1, le=50),
) -> ContextOut:
    await _owned(db, user.id, persona_id)
    bundle = await knowledge_service.fetch_context(
        db, persona_id, topic=topic, requesting_persona_id=persona_id, limit=limit
    )
    return ContextOut(
        topic=bundle.topic,
        related_topics=bundle.related_topics,
        items=[
            ContextItemOut(
                unit_id=i.unit_id, gist=i.gist, topic_tags=i.topic_tags, language=i.language
            )
            for i in bundle.items
        ],
    )


class InsightOut(BaseModel):
    bundle_id: uuid.UUID
    topic: str
    summary: str
    language: str


@router.get("/insights", response_model=list[InsightOut], summary="Approved insights for a topic")
async def get_insights(
    persona_id: uuid.UUID,
    user: CurrentUser,
    db: DB,
    topic: str = Query(min_length=1, max_length=64),
) -> Sequence[InsightOut]:
    await _owned(db, user.id, persona_id)
    from sqlalchemy import select

    from buddle.db.models.insight_bundle import InsightBundle

    rows = (
        await db.execute(
            select(InsightBundle)
            .where(InsightBundle.topic == topic, InsightBundle.status == "approved")
            .order_by(InsightBundle.created_at.desc())
            .limit(10)
        )
    ).scalars()
    return [
        InsightOut(bundle_id=b.id, topic=b.topic, summary=b.summary, language=b.language)
        for b in rows
    ]
