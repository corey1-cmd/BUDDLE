"""Debate routes — /v1/topics/{tag_id}/... (토론 대시보드 · 대립구조).

  GET  /v1/topics/{tag_id}/debate       토론 대시보드 (대화 축)
  GET  /v1/topics/{tag_id}/opposition   대립구조 기하 시각화
  POST /v1/topics/{tag_id}/stance       편 나눠 주장·근거 추가
  POST /v1/topics/by-name/stance        (이름으로) 편 나눠 주장·근거 추가 — 채팅 등
                                         tag_id 없이 화제 이름만 있는 화면용

Auth required; the data itself is public topic argumentation, already
leukocyte-screened at post time. Contributed stances are screened on submit.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from sqlalchemy import select

from buddle.api.deps import DB, CurrentUser
from buddle.core.exceptions import NotFound
from buddle.db.models.tag import Tag
from buddle.schemas.debate import (
    ArgumentGraphRead,
    DebateDashboardRead,
    OppositionRead,
    StanceAccepted,
    StanceContribution,
    StanceContributionByName,
)
from buddle.services import argument_service, leukocyte_service

router = APIRouter(prefix="/topics", tags=["debate"])


async def _require_tag(db: DB, tag_id: uuid.UUID) -> Tag:
    tag = (await db.execute(select(Tag).where(Tag.id == tag_id))).scalar_one_or_none()
    if tag is None:
        raise NotFound("topic not found")
    return tag


@router.post(
    "/by-name/stance",
    response_model=StanceAccepted,
    summary="화제 이름으로 편 나눠 주장·근거 추가 (채팅 등 tag_id 없는 화면용)",
)
async def contribute_stance_by_name(
    payload: StanceContributionByName, user: CurrentUser, db: DB
) -> StanceAccepted:
    # Registered ABOVE the /{tag_id}/... routes below: tag_id is a plain
    # string path segment at the routing layer (UUID validation happens
    # after matching), so "by-name" would otherwise be swallowed by
    # /{tag_id}/stance and 422 instead of reaching this route.
    screened_claim = (await leukocyte_service.screen_response(payload.claim)).content
    screened_grounds = [
        (await leukocyte_service.screen_response(g)).content for g in payload.grounds
    ]
    tag_id, added = await argument_service.add_stance_contribution_by_name(
        db,
        topic_name=payload.topic_name,
        stance=payload.stance,
        claim=screened_claim,
        grounds=screened_grounds,
        commit=True,
    )
    return StanceAccepted(tag_id=tag_id, units_added=added)


@router.get(
    "/{tag_id}/debate",
    response_model=DebateDashboardRead,
    summary="화제 토론 대시보드 조회",
)
async def read_topic_debate(tag_id: uuid.UUID, user: CurrentUser, db: DB) -> DebateDashboardRead:
    tag = await _require_tag(db, tag_id)
    view = await argument_service.build_dashboard(db, topic_tag_id=tag_id)
    return DebateDashboardRead.from_view(view, topic_name=tag.name)


@router.get(
    "/{tag_id}/opposition",
    response_model=OppositionRead,
    summary="화제 대립구조 기하 시각화 조회",
)
async def read_topic_opposition(tag_id: uuid.UUID, user: CurrentUser, db: DB) -> OppositionRead:
    tag = await _require_tag(db, tag_id)
    view = await argument_service.build_opposition(db, topic_tag_id=tag_id)
    return OppositionRead.from_view(view, topic_tag_id=tag_id, topic_name=tag.name)


@router.get(
    "/{tag_id}/graph",
    response_model=ArgumentGraphRead,
    summary="화제 논증 그래프 조회 (Kialo식 주장→근거→반박 트리)",
)
async def read_topic_graph(tag_id: uuid.UUID, user: CurrentUser, db: DB) -> ArgumentGraphRead:
    tag = await _require_tag(db, tag_id)
    view = await argument_service.build_argument_graph(db, topic_tag_id=tag_id)
    return ArgumentGraphRead.from_view(view, topic_tag_id=tag_id, topic_name=tag.name)


@router.post(
    "/{tag_id}/stance",
    response_model=StanceAccepted,
    summary="편을 정해 주장·근거 추가",
)
async def contribute_stance(
    tag_id: uuid.UUID, payload: StanceContribution, user: CurrentUser, db: DB
) -> StanceAccepted:
    await _require_tag(db, tag_id)
    # Output-side safety: screen the contributed claim + grounds before storing.
    screened_claim = (await leukocyte_service.screen_response(payload.claim)).content
    screened_grounds = [
        (await leukocyte_service.screen_response(g)).content for g in payload.grounds
    ]
    added = await argument_service.add_stance_contribution(
        db,
        topic_tag_id=tag_id,
        stance=payload.stance,
        claim=screened_claim,
        grounds=screened_grounds,
        commit=True,
    )
    return StanceAccepted(tag_id=tag_id, units_added=added)
